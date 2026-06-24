"""
EHR integration service — Phase 1.

Supports Epic (FHIR R4) with stubs for Cerner and Athenahealth.

Key design decisions:
- All HTTP calls are synchronous (httpx.Client) so this module can be imported
  from both sync and async contexts without event-loop conflicts.
- We use a short-lived OAuth2 client_credentials token per request; tokens are
  cached in a module-level dict keyed by clinic_id with a 55-minute TTL (Epic
  tokens expire after 60 min).
- HIPAA minimum-necessary: we only fetch name, DOB, gender, phone, email and
  most-recent encounter date — never full chart notes.
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.db.models import Appointment, EHRConfiguration, EMRPatient, EMRSyncLog, EMRAppointment
from backend.db.crud import get_ehr_configuration, update_ehr_configuration

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# ── OAuth token cache ─────────────────────────────────────────────────────────
# {clinic_id: {"token": str, "expires_at": float (unix ts)}}
_TOKEN_CACHE: dict[int, dict] = {}
_TOKEN_TTL_SECONDS = 55 * 60  # refresh 5 min before Epic's 60-min expiry


def _get_epic_token(config: EHRConfiguration, clinic_id: int) -> Optional[str]:
    """
    Fetch (or return cached) an Epic SMART backend-services OAuth2 token.
    Uses client_credentials grant with client_id + api_key (treated as client_secret).
    """
    cached = _TOKEN_CACHE.get(clinic_id)
    if cached and cached["expires_at"] > time.time():
        return cached["token"]

    token_url = config.api_endpoint.rstrip("/") + "/oauth2/token"
    try:
        r = httpx.post(
            token_url,
            data={
                "grant_type":    "client_credentials",
                "client_id":     config.client_id,
                "client_secret": config.api_key,
                "scope":         "system/Patient.read system/Appointment.read system/Appointment.write system/Slot.read",
            },
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        body = r.json()
        token = body["access_token"]
        _TOKEN_CACHE[clinic_id] = {
            "token":      token,
            "expires_at": time.time() + _TOKEN_TTL_SECONDS,
        }
        logger.debug("Epic OAuth token fetched for clinic %d", clinic_id)
        return token
    except Exception as exc:
        logger.error("Epic OAuth token fetch failed for clinic %d: %s", clinic_id, exc)
        return None


def _fhir_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/fhir+json",
        "Content-Type":  "application/fhir+json",
    }


def _log_sync(
    db: Session,
    clinic_id: int,
    ehr_system: str,
    operation: str,
    direction: str = "outbound",
    status: str = "success",
    appointment_id: Optional[int] = None,
    ehr_resource_id: str = "",
    error_code: str = "",
    error_message: str = "",
    http_status: int = 0,
    duration_ms: int = 0,
) -> None:
    try:
        entry = EMRSyncLog(
            clinic_id=clinic_id,
            ehr_system=ehr_system,
            operation=operation,
            direction=direction,
            status=status,
            appointment_id=appointment_id,
            ehr_resource_id=ehr_resource_id,
            error_code=error_code,
            error_message=error_message,
            http_status=http_status,
            duration_ms=duration_ms,
        )
        db.add(entry)
        db.commit()
    except Exception:
        logger.exception("EMRSyncLog write failed")


# ── Public API: appointment sync ──────────────────────────────────────────────

def sync_appointment_to_ehr(
    clinic_id: int,
    appointment: Appointment,
    db: Session,
) -> bool:
    """
    Push a booked appointment to the clinic's EHR as a FHIR Appointment resource.
    Returns True if sync succeeded or was not needed, False on error.
    """
    config = get_ehr_configuration(db, clinic_id)
    if not config or not config.auto_sync:
        return True
    if not config.ehr_system or not config.api_endpoint:
        logger.debug("EHR not configured for clinic %d", clinic_id)
        return True

    system = config.ehr_system.lower()
    t0 = time.monotonic()

    try:
        if system == "epic":
            success, ehr_id = _sync_epic(config, clinic_id, appointment)
        elif system == "cerner":
            success, ehr_id = _sync_cerner(config, clinic_id, appointment)
        elif system == "athenahealth":
            success, ehr_id = _sync_athenahealth(config, clinic_id, appointment)
        else:
            logger.warning("Unknown EHR system: %s", config.ehr_system)
            return False

        duration_ms = int((time.monotonic() - t0) * 1000)

        if success:
            update_ehr_configuration(db, clinic_id, {
                "last_sync_at":  datetime.utcnow(),
                "sync_status":   "active",
                "error_message": "",
            })
            _log_sync(db, clinic_id, system, "appt_sync", "outbound", "success",
                      appointment_id=appointment.id, ehr_resource_id=ehr_id,
                      duration_ms=duration_ms)
            logger.info("Appointment synced to EHR: clinic=%d conf=%s ehr_id=%s",
                        clinic_id, appointment.confirmation_number, ehr_id)
        else:
            update_ehr_configuration(db, clinic_id, {
                "sync_status":   "error",
                "error_message": "Failed to sync appointment",
            })
            _log_sync(db, clinic_id, system, "appt_sync", "outbound", "error",
                      appointment_id=appointment.id, duration_ms=duration_ms)

        return success

    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.error("EHR sync error for clinic %d: %s", clinic_id, exc)
        update_ehr_configuration(db, clinic_id, {
            "sync_status":   "error",
            "error_message": str(exc),
        })
        _log_sync(db, clinic_id, config.ehr_system.lower(), "appt_sync", "outbound", "error",
                  appointment_id=appointment.id, error_message=str(exc), duration_ms=duration_ms)
        return False


# ── Public API: patient lookup ────────────────────────────────────────────────

def lookup_patient(
    clinic_id: int,
    patient_name: str,
    date_of_birth: str,
    db: Session,
) -> Optional[dict]:
    """
    Look up a patient in the clinic's EHR by name + DOB.
    Returns a dict with demographic + last-visit info, or None on miss.
    Caches the result in emr_patients for 24 h.
    """
    config = get_ehr_configuration(db, clinic_id)
    if not config or not config.ehr_system or not config.api_endpoint:
        return None

    system = config.ehr_system.lower()

    # Check local cache first
    now = datetime.utcnow()
    cached = (
        db.query(EMRPatient)
        .filter(
            EMRPatient.clinic_id == clinic_id,
            EMRPatient.full_name.ilike(f"%{patient_name.strip()}%"),
            EMRPatient.date_of_birth == date_of_birth,
            EMRPatient.expires_at > now,
        )
        .first()
    )
    if cached:
        logger.debug("Patient cache hit: clinic=%d name=%s", clinic_id, patient_name)
        return _emr_patient_to_dict(cached)

    t0 = time.monotonic()
    try:
        if system == "epic":
            patient_data = _fetch_patient_epic(config, clinic_id, patient_name, date_of_birth)
        elif system == "cerner":
            patient_data = _fetch_patient_cerner(config, clinic_id, patient_name, date_of_birth)
        elif system == "athenahealth":
            patient_data = _fetch_patient_athenahealth(config, clinic_id, patient_name, date_of_birth)
        else:
            return None
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.error("Patient lookup error clinic=%d: %s", clinic_id, exc)
        _log_sync(db, clinic_id, system, "patient_lookup", "inbound", "error",
                  error_message=str(exc), duration_ms=duration_ms)
        return None

    duration_ms = int((time.monotonic() - t0) * 1000)

    if not patient_data:
        _log_sync(db, clinic_id, system, "patient_lookup", "inbound", "skipped",
                  duration_ms=duration_ms)
        return None

    # Upsert into local cache
    _upsert_emr_patient(db, clinic_id, system, patient_data)
    _log_sync(db, clinic_id, system, "patient_lookup", "inbound", "success",
              ehr_resource_id=patient_data.get("ehr_patient_id", ""), duration_ms=duration_ms)
    return patient_data


# ── Public API: slot availability ─────────────────────────────────────────────

def get_available_slots(
    clinic_id: int,
    appointment_type: str,
    date_start: str,
    date_end: str,
    provider_name: Optional[str],
    db: Session,
) -> list[dict]:
    """
    Fetch open appointment slots from the clinic's EHR.
    Returns a list of slot dicts suitable for Aria to present to the patient.
    Caches results in emr_appointments for 15 min.
    """
    config = get_ehr_configuration(db, clinic_id)
    if not config or not config.ehr_system or not config.api_endpoint:
        return []

    system = config.ehr_system.lower()
    now = datetime.utcnow()

    # Return cached slots if fresh
    cached_slots = (
        db.query(EMRAppointment)
        .filter(
            EMRAppointment.clinic_id == clinic_id,
            EMRAppointment.status == "free",
            EMRAppointment.expires_at > now,
        )
        .all()
    )
    if cached_slots:
        logger.debug("Slot cache hit: clinic=%d count=%d", clinic_id, len(cached_slots))
        return [_emr_slot_to_dict(s) for s in cached_slots]

    t0 = time.monotonic()
    try:
        if system == "epic":
            slots = _fetch_slots_epic(config, clinic_id, appointment_type, date_start, date_end, provider_name)
        elif system == "cerner":
            slots = _fetch_slots_cerner(config, clinic_id, appointment_type, date_start, date_end, provider_name)
        elif system == "athenahealth":
            slots = _fetch_slots_athenahealth(config, clinic_id, appointment_type, date_start, date_end, provider_name)
        else:
            return []
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.error("Slot fetch error clinic=%d: %s", clinic_id, exc)
        _log_sync(db, clinic_id, system, "slot_fetch", "inbound", "error",
                  error_message=str(exc), duration_ms=duration_ms)
        return []

    duration_ms = int((time.monotonic() - t0) * 1000)
    _log_sync(db, clinic_id, system, "slot_fetch", "inbound", "success",
              duration_ms=duration_ms)

    # Cache the slots
    _upsert_emr_slots(db, clinic_id, system, slots)
    return slots


# ── Epic FHIR R4 adapter ──────────────────────────────────────────────────────

def _sync_epic(
    config: EHRConfiguration,
    clinic_id: int,
    appointment: Appointment,
) -> tuple[bool, str]:
    """
    Create a FHIR Appointment resource in Epic.
    Returns (success, epic_appointment_id).
    """
    token = _get_epic_token(config, clinic_id)
    if not token:
        return False, ""

    base = config.api_endpoint.rstrip("/")
    fhir_appt = {
        "resourceType": "Appointment",
        "status":       "booked",
        "serviceType": [{
            "coding": [{"display": appointment.appointment_type}],
            "text":   appointment.appointment_type,
        }],
        "description": appointment.chief_complaint or appointment.appointment_type,
        "start":       _human_to_iso(appointment.appointment_datetime),
        "participant": [
            {
                "actor":  {"display": appointment.patient_name},
                "status": "accepted",
                "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                                      "code": "PART"}]}],
            },
            *(
                [{
                    "actor":  {"display": appointment.provider},
                    "status": "accepted",
                    "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                                          "code": "PPRF"}]}],
                }]
                if appointment.provider else []
            ),
        ],
        "comment": f"Booked via Aria AI — conf #{appointment.confirmation_number}",
    }

    try:
        r = httpx.post(
            f"{base}/Appointment",
            json=fhir_appt,
            headers=_fhir_headers(token),
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        ehr_id = r.json().get("id", "")
        logger.debug("Epic Appointment created: %s", ehr_id)
        return True, ehr_id
    except httpx.HTTPStatusError as exc:
        logger.error("Epic FHIR POST /Appointment failed: %s %s", exc.response.status_code, exc.response.text[:200])
        return False, ""
    except Exception as exc:
        logger.error("Epic sync error: %s", exc)
        return False, ""


def _fetch_patient_epic(
    config: EHRConfiguration,
    clinic_id: int,
    patient_name: str,
    date_of_birth: str,
) -> Optional[dict]:
    """
    Search Epic for a patient by family name + DOB using FHIR Patient search.
    Returns a normalized patient dict or None.
    """
    token = _get_epic_token(config, clinic_id)
    if not token:
        return None

    # Split "First Last" → family name for FHIR search
    parts = patient_name.strip().split()
    family = parts[-1] if parts else patient_name
    given  = parts[0]  if len(parts) > 1 else ""

    base = config.api_endpoint.rstrip("/")
    params: dict = {"family": family, "birthdate": date_of_birth, "_count": "5"}
    if given:
        params["given"] = given

    try:
        r = httpx.get(
            f"{base}/Patient",
            params=params,
            headers=_fhir_headers(token),
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        bundle = r.json()
    except Exception as exc:
        logger.error("Epic Patient search failed: %s", exc)
        return None

    entries = bundle.get("entry", [])
    if not entries:
        return None

    # Take first match
    resource = entries[0].get("resource", {})
    return _parse_fhir_patient(resource, "epic")


def _fetch_slots_epic(
    config: EHRConfiguration,
    clinic_id: int,
    appointment_type: str,
    date_start: str,
    date_end: str,
    provider_name: Optional[str],
) -> list[dict]:
    """
    Query Epic FHIR Slot resources for free slots in the date range.
    """
    token = _get_epic_token(config, clinic_id)
    if not token:
        return []

    base = config.api_endpoint.rstrip("/")
    params = {
        "status": "free",
        "start":  f"ge{date_start}",
        "end":    f"le{date_end}",
        "_count": "50",
    }

    try:
        r = httpx.get(
            f"{base}/Slot",
            params=params,
            headers=_fhir_headers(token),
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        bundle = r.json()
    except Exception as exc:
        logger.error("Epic Slot search failed: %s", exc)
        return []

    slots = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        slot = _parse_fhir_slot(resource, "epic", appointment_type)
        if slot:
            slots.append(slot)
    return slots


# ── Cerner adapter (Phase 2 — stubs for now) ─────────────────────────────────

def _sync_cerner(
    config: EHRConfiguration,
    clinic_id: int,
    appointment: Appointment,
) -> tuple[bool, str]:
    logger.debug("Cerner sync stub: clinic=%d conf=%s", clinic_id, appointment.confirmation_number)
    return True, "cerner-stub"


def _fetch_patient_cerner(
    config: EHRConfiguration,
    clinic_id: int,
    patient_name: str,
    date_of_birth: str,
) -> Optional[dict]:
    logger.debug("Cerner patient lookup stub: clinic=%d name=%s", clinic_id, patient_name)
    return None


def _fetch_slots_cerner(
    config: EHRConfiguration,
    clinic_id: int,
    appointment_type: str,
    date_start: str,
    date_end: str,
    provider_name: Optional[str],
) -> list[dict]:
    logger.debug("Cerner slot fetch stub: clinic=%d", clinic_id)
    return []


# ── Athenahealth adapter (Phase 2 — stubs for now) ───────────────────────────

def _sync_athenahealth(
    config: EHRConfiguration,
    clinic_id: int,
    appointment: Appointment,
) -> tuple[bool, str]:
    logger.debug("Athenahealth sync stub: clinic=%d conf=%s", clinic_id, appointment.confirmation_number)
    return True, "athena-stub"


def _fetch_patient_athenahealth(
    config: EHRConfiguration,
    clinic_id: int,
    patient_name: str,
    date_of_birth: str,
) -> Optional[dict]:
    logger.debug("Athenahealth patient lookup stub: clinic=%d name=%s", clinic_id, patient_name)
    return None


def _fetch_slots_athenahealth(
    config: EHRConfiguration,
    clinic_id: int,
    appointment_type: str,
    date_start: str,
    date_end: str,
    provider_name: Optional[str],
) -> list[dict]:
    logger.debug("Athenahealth slot fetch stub: clinic=%d", clinic_id)
    return []


# ── FHIR resource parsers ─────────────────────────────────────────────────────

def _parse_fhir_patient(resource: dict, ehr_system: str) -> dict:
    """Normalize a FHIR Patient resource to our internal dict format."""
    name_block = resource.get("name", [{}])[0]
    family  = name_block.get("family", "")
    given   = " ".join(name_block.get("given", []))
    full_name = f"{given} {family}".strip() if (given or family) else ""

    phone = ""
    email = ""
    for telecom in resource.get("telecom", []):
        if telecom.get("system") == "phone" and not phone:
            phone = telecom.get("value", "")
        if telecom.get("system") == "email" and not email:
            email = telecom.get("value", "")

    return {
        "ehr_patient_id":  resource.get("id", ""),
        "ehr_system":      ehr_system,
        "full_name":       full_name,
        "date_of_birth":   resource.get("birthDate", ""),
        "gender":          resource.get("gender", ""),
        "phone":           phone,
        "email":           email,
        "last_visit_date": "",
        "last_visit_type": "",
        "primary_provider": "",
    }


def _parse_fhir_slot(resource: dict, ehr_system: str, appointment_type: str) -> Optional[dict]:
    """Normalize a FHIR Slot resource to our internal dict format."""
    status = resource.get("status", "")
    if status != "free":
        return None

    start_iso = resource.get("start", "")
    if not start_iso:
        return None

    try:
        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None

    return {
        "ehr_slot_id":       resource.get("id", ""),
        "ehr_system":        ehr_system,
        "provider_name":     "",
        "slot_datetime":     dt,
        "slot_date_str":     dt.strftime("%Y-%m-%d"),
        "slot_time_str":     dt.strftime("%I:%M %p").lstrip("0"),
        "duration_minutes":  30,
        "appointment_type":  appointment_type,
        "status":            "free",
    }


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _upsert_emr_patient(db: Session, clinic_id: int, ehr_system: str, data: dict) -> None:
    expires = datetime.utcnow() + timedelta(hours=24)
    existing = (
        db.query(EMRPatient)
        .filter(EMRPatient.clinic_id == clinic_id,
                EMRPatient.ehr_patient_id == data["ehr_patient_id"])
        .first()
    )
    if existing:
        for k, v in data.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
        existing.fetched_at = datetime.utcnow()
        existing.expires_at = expires
    else:
        db.add(EMRPatient(
            clinic_id=clinic_id,
            ehr_system=ehr_system,
            expires_at=expires,
            **{k: v for k, v in data.items() if k not in ("ehr_system",)},
        ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("EMRPatient upsert failed")


def _upsert_emr_slots(db: Session, clinic_id: int, ehr_system: str, slots: list[dict]) -> None:
    expires = datetime.utcnow() + timedelta(minutes=15)
    for slot in slots:
        ehr_slot_id = slot.get("ehr_slot_id", "")
        if not ehr_slot_id:
            continue
        existing = (
            db.query(EMRAppointment)
            .filter(EMRAppointment.clinic_id == clinic_id,
                    EMRAppointment.ehr_slot_id == ehr_slot_id)
            .first()
        )
        if existing:
            existing.status     = slot.get("status", "free")
            existing.fetched_at = datetime.utcnow()
            existing.expires_at = expires
        else:
            db.add(EMRAppointment(
                clinic_id=clinic_id,
                ehr_system=ehr_system,
                ehr_slot_id=ehr_slot_id,
                provider_name=slot.get("provider_name", ""),
                slot_datetime=slot.get("slot_datetime"),
                slot_date_str=slot.get("slot_date_str", ""),
                slot_time_str=slot.get("slot_time_str", ""),
                duration_minutes=slot.get("duration_minutes", 30),
                appointment_type=slot.get("appointment_type", ""),
                status=slot.get("status", "free"),
                expires_at=expires,
            ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("EMRAppointment upsert failed")


def _emr_patient_to_dict(row: EMRPatient) -> dict:
    return {
        "ehr_patient_id":  row.ehr_patient_id,
        "ehr_system":      row.ehr_system,
        "full_name":       row.full_name,
        "date_of_birth":   row.date_of_birth,
        "gender":          row.gender,
        "phone":           row.phone,
        "email":           row.email,
        "last_visit_date": row.last_visit_date,
        "last_visit_type": row.last_visit_type,
        "primary_provider": row.primary_provider,
    }


def _emr_slot_to_dict(row: EMRAppointment) -> dict:
    return {
        "ehr_slot_id":       row.ehr_slot_id,
        "ehr_system":        row.ehr_system,
        "provider_name":     row.provider_name,
        "slot_date_str":     row.slot_date_str,
        "slot_time_str":     row.slot_time_str,
        "duration_minutes":  row.duration_minutes,
        "appointment_type":  row.appointment_type,
        "status":            row.status,
    }


# ── Utility ───────────────────────────────────────────────────────────────────

def _human_to_iso(human_datetime: str) -> str:
    """
    Convert Aria's human-readable datetime ("Monday, June 9 at 10:00 AM") to ISO 8601.
    Falls back to original string on parse failure so the FHIR POST still goes through.
    """
    formats = [
        "%A, %B %d at %I:%M %p",
        "%A, %B %d, %Y at %I:%M %p",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(human_datetime.strip(), fmt)
            if dt.year < 2000:
                dt = dt.replace(year=datetime.utcnow().year)
            return dt.strftime("%Y-%m-%dT%H:%M:00")
        except ValueError:
            continue
    return human_datetime


def test_ehr_connection(config: EHRConfiguration, clinic_id: int = 0) -> tuple[bool, str]:
    """
    Test EHR connection by fetching an OAuth token (Epic) or a lightweight
    metadata endpoint (Cerner / Athenahealth).
    Returns (success, message).
    """
    if not config.ehr_system or not config.api_endpoint:
        return False, "EHR configuration incomplete (system and endpoint required)"

    system = config.ehr_system.lower()

    try:
        if system == "epic":
            token = _get_epic_token(config, clinic_id)
            if token:
                return True, "Epic connection OK — OAuth token acquired"
            return False, "Epic OAuth token fetch failed — check client_id and api_key"

        elif system == "cerner":
            base = config.api_endpoint.rstrip("/")
            r = httpx.get(f"{base}/metadata", timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            return True, "Cerner FHIR metadata OK"

        elif system == "athenahealth":
            base = config.api_endpoint.rstrip("/")
            r = httpx.get(f"{base}/", timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            return True, "Athenahealth connection OK"

        else:
            return False, f"Unknown EHR system: {config.ehr_system}"

    except Exception as exc:
        return False, f"Connection test failed: {exc}"


def get_supported_ehr_systems() -> list[str]:
    return ["epic", "cerner", "athenahealth"]
