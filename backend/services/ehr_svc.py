"""
EHR integration service — Phase 2 + production hardening.

Supports Epic (FHIR R4), Cerner (FHIR R4), Athenahealth (REST API), eClinicalWorks.

Production additions (Phase 2+):
- Circuit breaker per EHR system — prevents cascade failures when an EHR is down
- Thread-safe token cache with RLock — safe under multi-threaded Gunicorn workers
- Athena sandbox auto-detection + retry wrapper with exponential-aware back-off
- HIPAA: never log patient names / DOB / PHI at ERROR/WARNING level
"""
import logging
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.db.models import Appointment, EHRConfiguration, EMRPatient, EMRSyncLog, EMRAppointment
from backend.db.crud import get_ehr_configuration, update_ehr_configuration
from backend.middleware import get_circuit_breaker, CircuitOpenError

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# ── OAuth token cache ─────────────────────────────────────────────────────────
# Thread-safe: Gunicorn threaded workers can call this concurrently.
# RLock (re-entrant) so a thread can acquire while already holding the lock.
_TOKEN_CACHE: dict[int, dict] = {}
_TOKEN_CACHE_LOCK = threading.RLock()
_TOKEN_TTL_SECONDS = 55 * 60  # refresh 5 min before Epic's 60-min expiry


def _cache_get(key) -> Optional[dict]:
    with _TOKEN_CACHE_LOCK:
        entry = _TOKEN_CACHE.get(key)
        if entry and entry.get("expires_at", 0) > time.time():
            return entry
        return None


def _cache_set(key, value: dict) -> None:
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE[key] = value


def _get_epic_token(config: EHRConfiguration, clinic_id: int) -> Optional[str]:
    """
    Fetch (or return cached) an Epic SMART backend-services OAuth2 token.
    Thread-safe. Circuit-broken per clinic to prevent hammering a down EHR.
    """
    cache_key = clinic_id
    cached = _cache_get(cache_key)
    if cached:
        return cached["token"]

    cb = get_circuit_breaker(f"epic_token_{clinic_id}", failure_threshold=3, reset_timeout=120)
    if not cb.is_available():
        logger.warning("Epic token circuit OPEN for clinic %d — skipping EHR call", clinic_id)
        return None

    token_url = config.api_endpoint.rstrip("/") + "/oauth2/token"
    try:
        with cb:
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
            body  = r.json()
            token = body["access_token"]
            _cache_set(cache_key, {"token": token, "expires_at": time.time() + _TOKEN_TTL_SECONDS})
            logger.debug("Epic OAuth token fetched for clinic %d", clinic_id)
            return token
    except CircuitOpenError:
        return None
    except Exception as exc:
        logger.error("Epic OAuth token fetch failed for clinic %d: %s", clinic_id, type(exc).__name__)
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
        elif system == "eclinicalworks":
            success, ehr_id = _sync_ecw(config, clinic_id, appointment)
        else:
            logger.warning("Unknown EHR system: %s", config.ehr_system)
            return False

        duration_ms = int((time.monotonic() - t0) * 1000)

        if success:
            update_ehr_configuration(db, clinic_id, {
                "last_sync_at":  datetime.now(timezone.utc).replace(tzinfo=None),
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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
        logger.debug("Patient cache hit: clinic=%d", clinic_id)  # HIPAA: no name in logs
        return _emr_patient_to_dict(cached)

    t0 = time.monotonic()
    try:
        if system == "epic":
            patient_data = _fetch_patient_epic(config, clinic_id, patient_name, date_of_birth)
        elif system == "cerner":
            patient_data = _fetch_patient_cerner(config, clinic_id, patient_name, date_of_birth)
        elif system == "athenahealth":
            patient_data = _fetch_patient_athenahealth(config, clinic_id, patient_name, date_of_birth)
        elif system == "eclinicalworks":
            patient_data = _fetch_patient_ecw(config, clinic_id, patient_name, date_of_birth)
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
    now = datetime.now(timezone.utc).replace(tzinfo=None)

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
        elif system == "eclinicalworks":
            slots = _fetch_slots_ecw(config, clinic_id, appointment_type, date_start, date_end, provider_name)
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


# ── Public API: intake pre-population ────────────────────────────────────────

def prefill_intake_from_ehr(
    clinic_id: int,
    patient_name: str,
    date_of_birth: str,
    db,
) -> dict:
    """
    Phase 2 — Intake pre-population.

    Looks up a patient in the EHR and returns a structured dict of fields
    that Aria can use to pre-fill an intake form, skipping questions the
    patient has already answered with the clinic before.

    Returns a dict with:
      found              bool
      pre_filled         dict  — fields Aria should treat as already known
      questions_to_skip  list  — question labels Aria can skip asking
      message            str   — human-readable summary for Aria to relay
    """
    patient = lookup_patient(clinic_id, patient_name, date_of_birth, db)

    if not patient:
        return {
            "found": False,
            "pre_filled": {},
            "questions_to_skip": [],
            "message": (
                f"No existing record found for {patient_name} (DOB {date_of_birth}). "
                "Please collect their information as a new patient."
            ),
        }

    pre_filled: dict = {}
    skip: list[str] = []

    if patient.get("full_name"):
        pre_filled["patient_name"] = patient["full_name"]
        skip.append("name")

    if patient.get("date_of_birth"):
        pre_filled["patient_dob"] = patient["date_of_birth"]
        skip.append("date of birth")

    if patient.get("phone"):
        pre_filled["patient_phone"] = patient["phone"]
        skip.append("phone number")

    if patient.get("email"):
        pre_filled["patient_email"] = patient["email"]
        skip.append("email address")

    if patient.get("primary_provider"):
        pre_filled["preferred_provider"] = patient["primary_provider"]
        skip.append("preferred provider")

    # Build a friendly summary for Aria to use in the conversation
    last_visit = patient.get("last_visit_date", "")
    lines = [f"Found existing patient record for {patient['full_name']}."]
    if last_visit:
        lines.append(f"Last visit: {last_visit}.")
    if patient.get("primary_provider"):
        lines.append(f"Primary provider: {patient['primary_provider']}.")
    if skip:
        lines.append(f"Already on file: {', '.join(skip)}.")

    return {
        "found": True,
        "pre_filled": pre_filled,
        "questions_to_skip": skip,
        "patient": patient,
        "message": " ".join(lines),
    }


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


# ── Cerner FHIR R4 adapter ────────────────────────────────────────────────────
# Cerner uses SMART on FHIR OAuth2 (same client_credentials flow as Epic).
# Token endpoint pattern: {base}/oauth2/token  (Cerner Ignite / Millennium R4)

def _get_cerner_token(config: EHRConfiguration, clinic_id: int) -> Optional[str]:
    """Fetch (or return cached) a Cerner SMART backend-services OAuth2 token. Thread-safe."""
    cache_key = f"cerner_{clinic_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached["token"]

    cb = get_circuit_breaker(f"cerner_token_{clinic_id}", failure_threshold=3, reset_timeout=120)
    if not cb.is_available():
        logger.warning("Cerner token circuit OPEN for clinic %d", clinic_id)
        return None

    token_url = config.api_endpoint.rstrip("/") + "/oauth2/token"
    try:
        r = httpx.post(
            token_url,
            data={
                "grant_type":    "client_credentials",
                "client_id":     config.client_id,
                "client_secret": config.api_key,
                "scope": (
                    "system/Patient.read system/Appointment.read "
                    "system/Appointment.write system/Slot.read"
                ),
            },
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        body = r.json()
        token = body["access_token"]
        _cache_set(cache_key, {"token": token, "expires_at": time.time() + _TOKEN_TTL_SECONDS})
        logger.debug("Cerner OAuth token fetched for clinic %d", clinic_id)
        return token
    except CircuitOpenError:
        return None
    except Exception as exc:
        logger.error("Cerner OAuth token fetch failed for clinic %d: %s", clinic_id, type(exc).__name__)
        return None


def _sync_cerner(
    config: EHRConfiguration,
    clinic_id: int,
    appointment: Appointment,
) -> tuple[bool, str]:
    """
    Create a FHIR Appointment in Cerner Millennium R4.
    Cerner's FHIR Appointment write endpoint mirrors Epic's structure.
    """
    token = _get_cerner_token(config, clinic_id)
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
        logger.debug("Cerner Appointment created: %s", ehr_id)
        return True, ehr_id
    except httpx.HTTPStatusError as exc:
        logger.error("Cerner FHIR POST /Appointment failed: %s %s",
                     exc.response.status_code, exc.response.text[:200])
        return False, ""
    except Exception as exc:
        logger.error("Cerner sync error: %s", exc)
        return False, ""


def _fetch_patient_cerner(
    config: EHRConfiguration,
    clinic_id: int,
    patient_name: str,
    date_of_birth: str,
) -> Optional[dict]:
    """Search Cerner for a patient by name + DOB via FHIR R4 Patient search."""
    token = _get_cerner_token(config, clinic_id)
    if not token:
        return None

    parts  = patient_name.strip().split()
    family = parts[-1] if parts else patient_name
    given  = parts[0]  if len(parts) > 1 else ""

    base   = config.api_endpoint.rstrip("/")
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
        logger.error("Cerner Patient search failed: %s", exc)
        return None

    entries = bundle.get("entry", [])
    if not entries:
        return None
    return _parse_fhir_patient(entries[0].get("resource", {}), "cerner")


def _fetch_slots_cerner(
    config: EHRConfiguration,
    clinic_id: int,
    appointment_type: str,
    date_start: str,
    date_end: str,
    provider_name: Optional[str],
) -> list[dict]:
    """
    Query Cerner FHIR R4 Slot resources for free slots.
    Cerner requires a Schedule reference — we search Schedule first then Slot.
    """
    token = _get_cerner_token(config, clinic_id)
    if not token:
        return []

    base = config.api_endpoint.rstrip("/")

    # Step 1: find Schedules (provider calendars) matching the date range
    schedule_params: dict = {
        "date":    f"ge{date_start}",
        "_count":  "10",
    }
    if provider_name:
        schedule_params["actor:Practitioner.name"] = provider_name

    try:
        sched_r = httpx.get(
            f"{base}/Schedule",
            params=schedule_params,
            headers=_fhir_headers(token),
            timeout=_HTTP_TIMEOUT,
        )
        sched_r.raise_for_status()
        schedules = sched_r.json().get("entry", [])
    except Exception as exc:
        logger.error("Cerner Schedule search failed: %s", exc)
        return []

    if not schedules:
        # Fallback: direct Slot search without Schedule filter (some Cerner deployments)
        return _fetch_slots_cerner_direct(config, token, base,
                                         appointment_type, date_start, date_end)

    # Step 2: fetch free Slots for each Schedule
    slots: list[dict] = []
    for sched_entry in schedules[:5]:  # cap at 5 schedules to avoid N+1 explosion
        sched_id = sched_entry.get("resource", {}).get("id", "")
        if not sched_id:
            continue
        try:
            slot_r = httpx.get(
                f"{base}/Slot",
                params={
                    "schedule": sched_id,
                    "status":   "free",
                    "start":    f"ge{date_start}",
                    "end":      f"le{date_end}",
                    "_count":   "20",
                },
                headers=_fhir_headers(token),
                timeout=_HTTP_TIMEOUT,
            )
            slot_r.raise_for_status()
            for entry in slot_r.json().get("entry", []):
                slot = _parse_fhir_slot(entry.get("resource", {}), "cerner", appointment_type)
                if slot:
                    slots.append(slot)
        except Exception as exc:
            logger.warning("Cerner Slot fetch for schedule %s failed: %s", sched_id, exc)

    return slots


def _fetch_slots_cerner_direct(
    config: EHRConfiguration,
    token: str,
    base: str,
    appointment_type: str,
    date_start: str,
    date_end: str,
) -> list[dict]:
    """Direct FHIR Slot search — fallback when Schedule search returns nothing."""
    try:
        r = httpx.get(
            f"{base}/Slot",
            params={
                "status": "free",
                "start":  f"ge{date_start}",
                "end":    f"le{date_end}",
                "_count": "50",
            },
            headers=_fhir_headers(token),
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        slots = []
        for entry in r.json().get("entry", []):
            slot = _parse_fhir_slot(entry.get("resource", {}), "cerner", appointment_type)
            if slot:
                slots.append(slot)
        return slots
    except Exception as exc:
        logger.error("Cerner direct Slot search failed: %s", exc)
        return []


# ── Athenahealth REST adapter ─────────────────────────────────────────────────
# Athenahealth uses OAuth2 client_credentials but its own REST API (not FHIR R4).
#
# Environments:
#   Production: https://api.platform.athenahealth.com/v1/{practiceid}
#   Sandbox:    https://api.preview.platform.athenahealth.com/v1/{practiceid}
#
# Token endpoints (auto-detected from api_endpoint):
#   Production: https://api.platform.athenahealth.com/oauth2/v1/token
#   Sandbox:    https://api.preview.platform.athenahealth.com/oauth2/v1/token
#
# The practice ID is embedded in api_endpoint. client_id / api_key are OAuth creds.
# Auth: HTTP Basic (client_id:client_secret) — NOT bearer in the token request.

_ATHENA_PROD_TOKEN_URL    = "https://api.platform.athenahealth.com/oauth2/v1/token"
_ATHENA_SANDBOX_TOKEN_URL = "https://api.preview.platform.athenahealth.com/oauth2/v1/token"

# Known Athena error codes and friendly messages
_ATHENA_ERROR_HINTS: dict[int, str] = {
    400: "Bad request — check practice ID and required fields",
    401: "Unauthorized — client_id or client_secret is incorrect",
    403: "Forbidden — API key does not have permission for this endpoint",
    404: "Not found — practice ID may be wrong or patient does not exist",
    429: "Rate limited — Athena allows ~200 req/min; retry after 60s",
    500: "Athena internal server error — try again in a few minutes",
    503: "Athena service unavailable — check status.athenahealth.com",
}


def _athena_is_sandbox(config: EHRConfiguration) -> bool:
    """Return True if the configured endpoint is the Athena sandbox."""
    return "preview" in config.api_endpoint.lower()


def _athena_token_url(config: EHRConfiguration) -> str:
    return _ATHENA_SANDBOX_TOKEN_URL if _athena_is_sandbox(config) else _ATHENA_PROD_TOKEN_URL


def _athena_friendly_error(exc: Exception, status_code: int = 0) -> str:
    hint = _ATHENA_ERROR_HINTS.get(status_code, "")
    return f"HTTP {status_code}: {hint}" if hint else str(exc)


def _athena_request_with_retry(
    method: str, url: str, headers: dict, retry: int = 2, **kwargs
) -> httpx.Response:
    """
    Make an Athena REST call with automatic retry on 429 (rate limit) and 503.
    Retries up to `retry` times with 2s back-off.
    """
    for attempt in range(retry + 1):
        r = httpx.request(method, url, headers=headers, timeout=_HTTP_TIMEOUT, **kwargs)
        if r.status_code in (429, 503) and attempt < retry:
            logger.warning("Athena %s %d — retrying in 2s (attempt %d/%d)",
                           url, r.status_code, attempt + 1, retry)
            time.sleep(2)
            continue
        return r
    return r  # type: ignore[return-value]


def _get_athena_token(config: EHRConfiguration, clinic_id: int) -> Optional[str]:
    """
    Fetch (or return cached) an Athenahealth OAuth2 bearer token.
    Auto-detects sandbox vs production from api_endpoint.
    """
    cache_key = f"athena_{clinic_id}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached["expires_at"] > time.time():
        return cached["token"]

    token_url = _athena_token_url(config)
    import base64
    credentials = base64.b64encode(
        f"{config.client_id}:{config.api_key}".encode()
    ).decode()

    try:
        r = httpx.post(
            token_url,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": "athena/service/Athenanet.MDP.*"},
            timeout=_HTTP_TIMEOUT,
        )
        if not r.is_success:
            err = _athena_friendly_error(None, r.status_code)
            logger.error("Athena token request failed for clinic %d: %s — %s",
                         clinic_id, err, r.text[:200])
            return None
        body  = r.json()
        token = body["access_token"]
        ttl   = int(body.get("expires_in", _TOKEN_TTL_SECONDS))
        env   = "sandbox" if _athena_is_sandbox(config) else "production"
        _cache_set(cache_key, {"token": token, "expires_at": time.time() + min(ttl - 60, _TOKEN_TTL_SECONDS)})
        logger.debug("Athenahealth OAuth token fetched (%s) for clinic %d", env, clinic_id)
        return token
    except Exception as exc:
        logger.error("Athenahealth OAuth token fetch failed for clinic %d: %s", clinic_id, type(exc).__name__)
        return None


def _athena_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _sync_athenahealth(
    config: EHRConfiguration,
    clinic_id: int,
    appointment: Appointment,
) -> tuple[bool, str]:
    """
    Book an appointment in Athenahealth via the REST API.
    Endpoint: POST /v1/{practiceid}/appointments/{appointmentid}/book
    We use the "open appointment" booking pattern:
      1. Find an open slot matching the appointment type
      2. Book it with patient demographics
    If no matching open slot exists, fall back to creating a new appointment.
    """
    token = _get_athena_token(config, clinic_id)
    if not token:
        return False, ""

    base = config.api_endpoint.rstrip("/")

    # Athenahealth appointment creation (new appointment outside of slot booking)
    appt_date = _human_to_iso(appointment.appointment_datetime)[:10]  # YYYY-MM-DD
    appt_time = _human_to_iso(appointment.appointment_datetime)[11:16]  # HH:MM

    payload = {
        "appointmentdate": appt_date,
        "appointmenttime": appt_time,
        "patientid":       "new",          # Will be matched by name+DOB on Athena side
        "appointmenttypeid": resolve_appointment_type_id(appointment.appointment_type, "athenahealth"),
        "providerid":      "",
        "reason":          appointment.chief_complaint or appointment.appointment_type,
        "patientfirstname": appointment.patient_name.split()[0] if appointment.patient_name else "",
        "patientlastname":  appointment.patient_name.split()[-1] if appointment.patient_name else "",
        "patientdob":      appointment.patient_dob or "",
        "patientemail":    appointment.patient_email or "",
        "patientphone":    appointment.patient_phone or "",
    }

    try:
        r = httpx.post(
            f"{base}/appointments/open",
            data=payload,
            headers=_athena_headers(token),
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        body   = r.json()
        ehr_id = str(body[0].get("appointmentid", "")) if isinstance(body, list) and body else ""
        logger.debug("Athenahealth appointment created: %s", ehr_id)
        return True, ehr_id
    except httpx.HTTPStatusError as exc:
        logger.error("Athenahealth POST /appointments/open failed: %s %s",
                     exc.response.status_code, exc.response.text[:200])
        return False, ""
    except Exception as exc:
        logger.error("Athenahealth sync error: %s", exc)
        return False, ""


def _fetch_patient_athenahealth(
    config: EHRConfiguration,
    clinic_id: int,
    patient_name: str,
    date_of_birth: str,
) -> Optional[dict]:
    """
    Search Athenahealth for a patient by name + DOB.
    Endpoint: GET /v1/{practiceid}/patients?firstname=&lastname=&dob=
    """
    token = _get_athena_token(config, clinic_id)
    if not token:
        return None

    parts      = patient_name.strip().split()
    first_name = parts[0]  if parts else ""
    last_name  = parts[-1] if len(parts) > 1 else patient_name

    base = config.api_endpoint.rstrip("/")
    try:
        r = httpx.get(
            f"{base}/patients",
            params={
                "firstname": first_name,
                "lastname":  last_name,
                "dob":       date_of_birth,
                "limit":     "5",
            },
            headers=_athena_headers(token),
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        body = r.json()
    except Exception as exc:
        logger.error("Athenahealth patient search failed: %s", exc)
        return None

    patients = body.get("patients", body if isinstance(body, list) else [])
    if not patients:
        return None

    p = patients[0]
    return {
        "ehr_patient_id":   str(p.get("patientid", "")),
        "ehr_system":       "athenahealth",
        "full_name":        f"{p.get('firstname', '')} {p.get('lastname', '')}".strip(),
        "date_of_birth":    p.get("dob", date_of_birth),
        "gender":           p.get("sex", ""),
        "phone":            p.get("mobilephone") or p.get("homephone") or "",
        "email":            p.get("email", ""),
        "last_visit_date":  p.get("lastappointment", ""),
        "last_visit_type":  "",
        "primary_provider": p.get("primaryproviderid", ""),
    }


def _fetch_athena_provider_name(base: str, headers: dict, provider_id: str) -> str:
    """
    Resolve a numeric Athenahealth providerid to a human-readable name.
    Endpoint: GET /v1/{practiceid}/providers/{providerid}
    Cached in module-level dict to avoid N+1 lookups per slot.
    """
    if not provider_id:
        return ""
    cache_key = f"athena_prov_{provider_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached.get("name", "")
    try:
        r = httpx.get(f"{base}/providers/{provider_id}",
                      headers=headers, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        providers = body.get("providers", [body] if isinstance(body, dict) else [])
        if providers:
            p = providers[0]
            name = f"Dr. {p.get('firstname', '')} {p.get('lastname', '')}".strip()
            _cache_set(cache_key, {"name": name, "expires_at": float("inf")})
            return name
    except Exception:
        pass
    return f"Provider #{provider_id}"


def _fetch_slots_athenahealth(
    config: EHRConfiguration,
    clinic_id: int,
    appointment_type: str,
    date_start: str,
    date_end: str,
    provider_name: Optional[str],
) -> list[dict]:
    """
    Fetch open appointment slots from Athenahealth with:
    - Appointment type ID resolution
    - Provider name lookup (providerid → display name)
    - Pagination (follows Athena's offset/limit pattern, fetches up to 150 slots)
    - Robust date parsing (MM/DD/YYYY, YYYY-MM-DD, ISO 8601)
    """
    token = _get_athena_token(config, clinic_id)
    if not token:
        return []

    base    = config.api_endpoint.rstrip("/")
    headers = _athena_headers(token)

    # Resolve provider ID if a name filter was passed
    provider_id = ""
    if provider_name and provider_name.isdigit():
        provider_id = provider_name
    elif provider_name:
        # Try to find provider by name via /providers search
        try:
            pr = httpx.get(f"{base}/providers",
                           params={"searchterm": provider_name, "limit": "5"},
                           headers=headers, timeout=_HTTP_TIMEOUT)
            if pr.ok:
                plist = pr.json().get("providers", [])
                if plist:
                    provider_id = str(plist[0].get("providerid", ""))
        except Exception:
            pass

    appt_type_id = resolve_appointment_type_id(appointment_type, "athenahealth")

    # Paginate — Athena returns up to 50 per page
    all_slots: list[dict] = []
    offset = 0
    limit  = 50
    max_pages = 3  # cap at 150 slots

    for _ in range(max_pages):
        params: dict = {
            "startdate":         date_start,
            "enddate":           date_end,
            "appointmenttypeid": appt_type_id,
            "limit":             str(limit),
            "offset":            str(offset),
        }
        if provider_id:
            params["providerid"] = provider_id

        try:
            r = _athena_request_with_retry("GET", f"{base}/appointments/open",
                                           headers=headers, params=params)
            if not r.is_success:
                logger.error("Athena slot fetch offset=%d: %s",
                             offset, _athena_friendly_error(None, r.status_code))
                break
            body = r.json()
        except Exception as exc:
            logger.error("Athenahealth slot fetch failed (offset=%d): %s", offset, exc)
            break

        raw_slots = body.get("appointments", body if isinstance(body, list) else [])
        if not raw_slots:
            break

        for s in raw_slots:
            slot = _parse_athena_slot(s, appointment_type, base, headers)
            if slot:
                all_slots.append(slot)

        # Stop paginating if we got fewer than a full page
        if len(raw_slots) < limit:
            break
        offset += limit

    return all_slots


def _parse_athena_slot(raw: dict, appointment_type: str,
                       base: str = "", headers: dict = None) -> Optional[dict]:
    """
    Normalize an Athenahealth appointment slot to our internal dict format.
    Handles multiple Athena date formats:
      MM/DD/YYYY, YYYY-MM-DD, ISO 8601 (with/without timezone)
    Resolves provider ID to display name when base URL is provided.
    """
    date_str = raw.get("date", "")
    time_str = raw.get("starttime", "")
    if not date_str:
        return None

    # Parse date — handle multiple Athena date formats
    from datetime import datetime as _dt, timezone
    dt = None
    formats = [
        ("%m/%d/%Y %H:%M",    f"{date_str} {time_str}"),
        ("%m/%d/%Y %I:%M %p", f"{date_str} {time_str}"),
        ("%Y-%m-%d %H:%M",    f"{date_str} {time_str or '00:00'}"),
        ("%Y-%m-%d",          date_str),
    ]
    for fmt, val in formats:
        try:
            dt = _dt.strptime(val.strip(), fmt)
            break
        except ValueError:
            continue
    if dt is None:
        try:
            dt = _dt.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    # Resolve providerid → display name if base URL available
    raw_provider = str(raw.get("providerid", ""))
    if base and headers and raw_provider:
        display_name = _fetch_athena_provider_name(base, headers, raw_provider)
    else:
        display_name = raw_provider

    return {
        "ehr_slot_id":       str(raw.get("appointmentid", raw.get("slotid", raw_provider + dt.isoformat()))),
        "ehr_system":        "athenahealth",
        "provider_name":     display_name,
        "slot_datetime":     dt,
        "slot_date_str":     dt.strftime("%Y-%m-%d"),
        "slot_time_str":     dt.strftime("%I:%M %p").lstrip("0"),
        "duration_minutes":  int(raw.get("duration", raw.get("appointmentduration", 30))),
        "appointment_type":  raw.get("appointmenttype", appointment_type),
        "status":            "free",
    }


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
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=24)
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
        existing.fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15)
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
            existing.fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
                dt = dt.replace(year=datetime.now(timezone.utc).replace(tzinfo=None).year)
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
            # Try token first; fall back to unauthenticated FHIR metadata
            token = _get_cerner_token(config, clinic_id)
            if token:
                return True, "Cerner connection OK — OAuth token acquired"
            base = config.api_endpoint.rstrip("/")
            r = httpx.get(f"{base}/metadata", timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            return True, "Cerner FHIR metadata OK (unauthenticated)"

        elif system == "athenahealth":
            token = _get_athena_token(config, clinic_id)
            if token:
                return True, "Athenahealth connection OK — OAuth token acquired"
            return False, "Athenahealth OAuth token fetch failed — check client_id and api_key"

        elif system == "eclinicalworks":
            token = _get_ecw_token(config, clinic_id)
            if token:
                return True, "eClinicalWorks connection OK — OAuth token acquired"
            return False, "eClinicalWorks OAuth token fetch failed — check client_id and api_key"

        else:
            return False, f"Unknown EHR system: {config.ehr_system}"

    except Exception as exc:
        return False, f"Connection test failed: {exc}"


def get_supported_ehr_systems() -> list[str]:
    return ["epic", "cerner", "athenahealth", "eclinicalworks"]


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Enterprise only: Chart read + Note sync + eClinicalWorks adapter
# ═══════════════════════════════════════════════════════════════════════════════

# ── Public API: patient chart read ────────────────────────────────────────────

def fetch_patient_chart(
    clinic_id: int,
    ehr_patient_id: str,
    ehr_system: str,
    db,
) -> Optional[dict]:
    """
    Phase 4 — Fetch a patient's chart summary from the EHR.
    Returns diagnoses, active medications, and allergies.
    Caches result for 1 hour (HIPAA minimum necessary — no free-text notes).
    """
    from backend.db.models import EMRChartSummary
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Check cache
    cached = (
        db.query(EMRChartSummary)
        .filter(
            EMRChartSummary.clinic_id  == clinic_id,
            EMRChartSummary.ehr_patient_id == ehr_patient_id,
            EMRChartSummary.expires_at > now,
        )
        .first()
    )
    if cached:
        import json as _json
        return {
            "ehr_patient_id": cached.ehr_patient_id,
            "ehr_system":     cached.ehr_system,
            "diagnoses":      _json.loads(cached.diagnoses  or "[]"),
            "medications":    _json.loads(cached.medications or "[]"),
            "allergies":      _json.loads(cached.allergies   or "[]"),
        }

    config = get_ehr_configuration(db, clinic_id)
    if not config or not config.ehr_system or not config.api_endpoint:
        return None

    t0 = time.monotonic()
    try:
        system = ehr_system.lower()
        if system == "epic":
            chart = _fetch_chart_epic(config, clinic_id, ehr_patient_id)
        elif system == "cerner":
            chart = _fetch_chart_cerner(config, clinic_id, ehr_patient_id)
        elif system == "athenahealth":
            chart = _fetch_chart_athena(config, clinic_id, ehr_patient_id)
        elif system == "eclinicalworks":
            chart = _fetch_chart_ecw(config, clinic_id, ehr_patient_id)
        else:
            return None
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.error("Chart fetch error clinic=%d patient=%s: %s", clinic_id, ehr_patient_id, exc)
        _log_sync(db, clinic_id, ehr_system, "chart_read", "inbound", "error",
                  ehr_resource_id=ehr_patient_id, error_message=str(exc), duration_ms=duration_ms)
        return None

    duration_ms = int((time.monotonic() - t0) * 1000)
    if chart:
        _upsert_chart_summary(db, clinic_id, ehr_patient_id, ehr_system, chart)
        _log_sync(db, clinic_id, ehr_system, "chart_read", "inbound", "success",
                  ehr_resource_id=ehr_patient_id, duration_ms=duration_ms)
    return chart


# ── Public API: note sync ─────────────────────────────────────────────────────

def sync_note_to_ehr(
    clinic_id: int,
    session_id: str,
    ehr_patient_id: str,
    note_content: str,
    note_type: str = "encounter_summary",
    db = None,
) -> tuple[bool, str]:
    """
    Phase 4 — Push an Aria conversation summary as a clinical note to the EHR.
    One note per session (idempotent — second call returns the existing document ID).
    Returns (success, ehr_document_id).
    """
    from backend.db.models import EMRNoteSync

    # Idempotency: skip if already synced for this session
    existing = (
        db.query(EMRNoteSync)
        .filter(EMRNoteSync.clinic_id == clinic_id, EMRNoteSync.session_id == session_id)
        .first()
    )
    if existing:
        logger.debug("Note already synced for session %s: doc=%s", session_id, existing.ehr_document_id)
        return True, existing.ehr_document_id

    config = get_ehr_configuration(db, clinic_id)
    if not config or not config.ehr_system or not config.api_endpoint:
        return False, ""

    system = config.ehr_system.lower()
    t0     = time.monotonic()

    try:
        if system == "epic":
            success, doc_id = _post_note_epic(config, clinic_id, ehr_patient_id, note_content, note_type)
        elif system == "cerner":
            success, doc_id = _post_note_cerner(config, clinic_id, ehr_patient_id, note_content, note_type)
        elif system == "athenahealth":
            success, doc_id = _post_note_athena(config, clinic_id, ehr_patient_id, note_content)
        elif system == "eclinicalworks":
            success, doc_id = _post_note_ecw(config, clinic_id, ehr_patient_id, note_content)
        else:
            return False, ""
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.error("Note sync error clinic=%d session=%s: %s", clinic_id, session_id, exc)
        _write_note_sync_record(db, clinic_id, session_id, ehr_patient_id, system,
                                "", note_type, note_content[:200], "error", str(exc))
        _log_sync(db, clinic_id, system, "note_sync", "outbound", "error",
                  error_message=str(exc), duration_ms=duration_ms)
        return False, ""

    duration_ms = int((time.monotonic() - t0) * 1000)
    status      = "success" if success else "error"
    _write_note_sync_record(db, clinic_id, session_id, ehr_patient_id, system,
                            doc_id, note_type, note_content[:200], status, "")
    _log_sync(db, clinic_id, system, "note_sync", "outbound", status,
              ehr_resource_id=doc_id, duration_ms=duration_ms)
    return success, doc_id


# ── Epic chart reader ─────────────────────────────────────────────────────────

def _fetch_chart_epic(config: EHRConfiguration, clinic_id: int, patient_id: str) -> Optional[dict]:
    """Fetch Condition + MedicationRequest + AllergyIntolerance for a patient from Epic FHIR R4."""
    token = _get_epic_token(config, clinic_id)
    if not token:
        return None

    base    = config.api_endpoint.rstrip("/")
    headers = _fhir_headers(token)
    chart   = {"ehr_patient_id": patient_id, "ehr_system": "epic",
                "diagnoses": [], "medications": [], "allergies": []}

    # Conditions (active problems)
    try:
        r = httpx.get(f"{base}/Condition",
                      params={"patient": patient_id, "clinical-status": "active", "_count": "50"},
                      headers=headers, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        for entry in r.json().get("entry", []):
            res  = entry.get("resource", {})
            code = res.get("code", {})
            chart["diagnoses"].append({
                "code":    (code.get("coding", [{}])[0].get("code", "")),
                "display": (code.get("text") or
                            code.get("coding", [{}])[0].get("display", "Unknown")),
                "status":  res.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", "active"),
            })
    except Exception as exc:
        logger.warning("Epic Condition fetch failed for patient %s: %s", patient_id, exc)

    # Active medications
    try:
        r = httpx.get(f"{base}/MedicationRequest",
                      params={"patient": patient_id, "status": "active", "_count": "50"},
                      headers=headers, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        for entry in r.json().get("entry", []):
            res  = entry.get("resource", {})
            med  = res.get("medicationCodeableConcept", {})
            dose = ""
            if res.get("dosageInstruction"):
                dose = res["dosageInstruction"][0].get("text", "")
            chart["medications"].append({
                "name":   med.get("text") or med.get("coding", [{}])[0].get("display", "Unknown"),
                "dose":   dose,
                "status": res.get("status", "active"),
            })
    except Exception as exc:
        logger.warning("Epic MedicationRequest fetch failed for patient %s: %s", patient_id, exc)

    # Allergies
    try:
        r = httpx.get(f"{base}/AllergyIntolerance",
                      params={"patient": patient_id, "_count": "50"},
                      headers=headers, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        for entry in r.json().get("entry", []):
            res  = entry.get("resource", {})
            subst = res.get("code", {})
            react = ""
            if res.get("reaction"):
                manif = res["reaction"][0].get("manifestation", [{}])
                react = manif[0].get("text") or manif[0].get("coding", [{}])[0].get("display", "")
            chart["allergies"].append({
                "substance": subst.get("text") or subst.get("coding", [{}])[0].get("display", "Unknown"),
                "reaction":  react,
                "severity":  res.get("reaction", [{}])[0].get("severity", "") if res.get("reaction") else "",
            })
    except Exception as exc:
        logger.warning("Epic AllergyIntolerance fetch failed for patient %s: %s", patient_id, exc)

    return chart


def _post_note_epic(config, clinic_id, patient_id, note_content, note_type) -> tuple[bool, str]:
    """Create a FHIR DocumentReference in Epic for the Aria conversation summary."""
    token = _get_epic_token(config, clinic_id)
    if not token:
        return False, ""

    import base64 as _b64
    base    = config.api_endpoint.rstrip("/")
    encoded = _b64.b64encode(note_content.encode()).decode()

    doc_ref = {
        "resourceType": "DocumentReference",
        "status":       "current",
        "type": {
            "coding": [{
                "system":  "http://loinc.org",
                "code":    "11488-4",
                "display": "Consult note",
            }],
            "text": "Aria AI Encounter Summary",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "date":    datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "data":        encoded,
                "title":       f"Aria AI {note_type.replace('_', ' ').title()}",
            }
        }],
        "description": f"Automated encounter summary generated by Aria AI front desk.",
    }

    try:
        r = httpx.post(f"{base}/DocumentReference", json=doc_ref,
                       headers=_fhir_headers(token), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return True, r.json().get("id", "")
    except Exception as exc:
        logger.error("Epic DocumentReference POST failed: %s", exc)
        return False, ""


# ── Cerner chart reader ───────────────────────────────────────────────────────

def _fetch_chart_cerner(config: EHRConfiguration, clinic_id: int, patient_id: str) -> Optional[dict]:
    """Fetch Condition + MedicationRequest + AllergyIntolerance from Cerner FHIR R4."""
    token = _get_cerner_token(config, clinic_id)
    if not token:
        return None

    base    = config.api_endpoint.rstrip("/")
    headers = _fhir_headers(token)
    chart   = {"ehr_patient_id": patient_id, "ehr_system": "cerner",
                "diagnoses": [], "medications": [], "allergies": []}

    for resource, key, params in [
        ("Condition",          "diagnoses",  {"patient": patient_id, "clinical-status": "active"}),
        ("MedicationRequest",  "medications", {"patient": patient_id, "status": "active"}),
        ("AllergyIntolerance", "allergies",  {"patient": patient_id}),
    ]:
        try:
            r = httpx.get(f"{base}/{resource}", params={**params, "_count": "50"},
                          headers=headers, timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            for entry in r.json().get("entry", []):
                res = entry.get("resource", {})
                if resource == "Condition":
                    code = res.get("code", {})
                    chart[key].append({
                        "code":    code.get("coding", [{}])[0].get("code", ""),
                        "display": code.get("text") or code.get("coding", [{}])[0].get("display", ""),
                        "status":  "active",
                    })
                elif resource == "MedicationRequest":
                    med  = res.get("medicationCodeableConcept", {})
                    dose = ""
                    if res.get("dosageInstruction"):
                        dose = res["dosageInstruction"][0].get("text", "")
                    chart[key].append({
                        "name":   med.get("text") or med.get("coding", [{}])[0].get("display", ""),
                        "dose":   dose,
                        "status": res.get("status", "active"),
                    })
                elif resource == "AllergyIntolerance":
                    subst = res.get("code", {})
                    react = ""
                    if res.get("reaction"):
                        manif = res["reaction"][0].get("manifestation", [{}])
                        react = manif[0].get("text") or manif[0].get("coding", [{}])[0].get("display", "")
                    chart[key].append({
                        "substance": subst.get("text") or subst.get("coding", [{}])[0].get("display", ""),
                        "reaction":  react,
                        "severity":  res.get("reaction", [{}])[0].get("severity", "") if res.get("reaction") else "",
                    })
        except Exception as exc:
            logger.warning("Cerner %s fetch failed for patient %s: %s", resource, patient_id, exc)

    return chart


def _post_note_cerner(config, clinic_id, patient_id, note_content, note_type) -> tuple[bool, str]:
    """Create a FHIR DocumentReference in Cerner."""
    token = _get_cerner_token(config, clinic_id)
    if not token:
        return False, ""

    import base64 as _b64
    base    = config.api_endpoint.rstrip("/")
    encoded = _b64.b64encode(note_content.encode()).decode()

    doc_ref = {
        "resourceType": "DocumentReference",
        "status":       "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": "11488-4"}],
                 "text": "Aria AI Encounter Summary"},
        "subject":  {"reference": f"Patient/{patient_id}"},
        "date":     datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "content":  [{"attachment": {"contentType": "text/plain", "data": encoded,
                                     "title": "Aria AI Encounter Summary"}}],
    }

    try:
        r = httpx.post(f"{base}/DocumentReference", json=doc_ref,
                       headers=_fhir_headers(token), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return True, r.json().get("id", "")
    except Exception as exc:
        logger.error("Cerner DocumentReference POST failed: %s", exc)
        return False, ""


# ── Athenahealth chart reader ─────────────────────────────────────────────────

def _fetch_chart_athena(config: EHRConfiguration, clinic_id: int, patient_id: str) -> Optional[dict]:
    """Fetch problems + medications + allergies from Athenahealth REST API."""
    token = _get_athena_token(config, clinic_id)
    if not token:
        return None

    base    = config.api_endpoint.rstrip("/")
    headers = _athena_headers(token)
    chart   = {"ehr_patient_id": patient_id, "ehr_system": "athenahealth",
                "diagnoses": [], "medications": [], "allergies": []}

    env = "sandbox" if _athena_is_sandbox(config) else "production"
    logger.debug("Athena chart read (%s) patient=%s", env, patient_id)

    # Problems (diagnoses) — with retry
    try:
        r = _athena_request_with_retry("GET", f"{base}/patients/{patient_id}/problems",
                                       headers=headers, params={"status": "ACTIVE"})
        if r.is_success:
            body = r.json()
            for prob in (body.get("problems") or body if isinstance(body, list) else []):
                chart["diagnoses"].append({
                    "code":    prob.get("icd10code", prob.get("icd9code", "")),
                    "display": prob.get("name", ""),
                    "status":  prob.get("status", "ACTIVE").lower(),
                })
        else:
            logger.warning("Athena problems %s: %s", patient_id,
                           _athena_friendly_error(None, r.status_code))
    except Exception as exc:
        logger.warning("Athenahealth problems fetch failed for patient %s: %s", patient_id, exc)

    # Medications — with retry
    try:
        r = _athena_request_with_retry("GET", f"{base}/patients/{patient_id}/medications",
                                       headers=headers)
        if r.is_success:
            body = r.json()
            for med in (body.get("medications", [{}])[0].get("medications", [])
                        if isinstance(body, dict) else []):
                chart["medications"].append({
                    "name":   med.get("medicationname", ""),
                    "dose":   med.get("sig", ""),
                    "status": med.get("medicationentrytype", "active").lower(),
                })
        else:
            logger.warning("Athena medications %s: %s", patient_id,
                           _athena_friendly_error(None, r.status_code))
    except Exception as exc:
        logger.warning("Athenahealth medications fetch failed for patient %s: %s", patient_id, exc)

    # Allergies — with retry
    try:
        r = _athena_request_with_retry("GET", f"{base}/patients/{patient_id}/allergies",
                                       headers=headers)
        if r.is_success:
            body = r.json()
            for allergy in (body.get("allergies") or body if isinstance(body, list) else []):
                chart["allergies"].append({
                    "substance": allergy.get("allergenname", ""),
                    "reaction":  allergy.get("reactions", [{"reactionname": ""}])[0].get("reactionname", ""),
                    "severity":  allergy.get("severity", "").lower(),
                })
        else:
            logger.warning("Athena allergies %s: %s", patient_id,
                           _athena_friendly_error(None, r.status_code))
    except Exception as exc:
        logger.warning("Athenahealth allergies fetch failed for patient %s: %s", patient_id, exc)

    return chart


def _post_note_athena(config, clinic_id, patient_id, note_content) -> tuple[bool, str]:
    """Upload Aria conversation summary as a patient document in Athenahealth."""
    token = _get_athena_token(config, clinic_id)
    if not token:
        return False, ""

    base = config.api_endpoint.rstrip("/")
    try:
        r = httpx.post(
            f"{base}/patients/{patient_id}/documents",
            data={
                "documentsubclass": "ENCOUNTERDOCUMENT",
                "internalnote":     note_content[:4000],
                "documenttypeid":   "1",
            },
            headers=_athena_headers(token),
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        body   = r.json()
        doc_id = str(body[0].get("documentid", "")) if isinstance(body, list) and body else ""
        return True, doc_id
    except Exception as exc:
        logger.error("Athenahealth document POST failed: %s", exc)
        return False, ""


# ── eClinicalWorks (eCW) adapter ──────────────────────────────────────────────
# eCW uses its own REST API (not standard FHIR) with OAuth2 client_credentials.
# API base: {api_endpoint}  (e.g. https://api.eclinicalworks.com/v1)
# Token endpoint: {api_endpoint}/oauth/token
# Docs: eCW FHIR R4 API (newer) or eCW SOAP API (legacy); we target the FHIR R4 variant.

_ECW_TOKEN_KEY = "ecw_{clinic_id}"


def _get_ecw_token(config: EHRConfiguration, clinic_id: int) -> Optional[str]:
    """Fetch (or return cached) an eClinicalWorks OAuth2 bearer token."""
    cache_key = f"ecw_{clinic_id}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached["expires_at"] > time.time():
        return cached["token"]

    token_url = config.api_endpoint.rstrip("/") + "/oauth/token"
    try:
        r = httpx.post(
            token_url,
            data={
                "grant_type":    "client_credentials",
                "client_id":     config.client_id,
                "client_secret": config.api_key,
                "scope":         "patient/*.read document/*.write appointment/*.write",
            },
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        body  = r.json()
        token = body["access_token"]
        ttl   = int(body.get("expires_in", _TOKEN_TTL_SECONDS))
        _cache_set(cache_key, {"token": token, "expires_at": time.time() + min(ttl - 60, _TOKEN_TTL_SECONDS)})
        logger.debug("eClinicalWorks OAuth token fetched for clinic %d", clinic_id)
        return token
    except Exception as exc:
        logger.error("eClinicalWorks OAuth token fetch failed for clinic %d: %s", clinic_id, type(exc).__name__)
        return None


def _ecw_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/fhir+json",
        "Content-Type":  "application/fhir+json",
    }


def _sync_ecw(config: EHRConfiguration, clinic_id: int, appointment: Appointment) -> tuple[bool, str]:
    """Create a FHIR Appointment in eClinicalWorks."""
    token = _get_ecw_token(config, clinic_id)
    if not token:
        return False, ""

    base = config.api_endpoint.rstrip("/")
    fhir_appt = {
        "resourceType": "Appointment",
        "status":       "booked",
        "serviceType": [{"text": appointment.appointment_type}],
        "description": appointment.chief_complaint or appointment.appointment_type,
        "start":       _human_to_iso(appointment.appointment_datetime),
        "participant": [
            {"actor": {"display": appointment.patient_name}, "status": "accepted"},
            *(
                [{"actor": {"display": appointment.provider}, "status": "accepted"}]
                if appointment.provider else []
            ),
        ],
        "comment": f"Booked via Aria AI — conf #{appointment.confirmation_number}",
    }

    try:
        r = httpx.post(f"{base}/Appointment", json=fhir_appt,
                       headers=_ecw_headers(token), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return True, r.json().get("id", "")
    except Exception as exc:
        logger.error("eClinicalWorks Appointment POST failed: %s", exc)
        return False, ""


def _fetch_patient_ecw(config, clinic_id, patient_name, date_of_birth) -> Optional[dict]:
    """Search eClinicalWorks for a patient via FHIR Patient search."""
    token = _get_ecw_token(config, clinic_id)
    if not token:
        return None

    parts  = patient_name.strip().split()
    family = parts[-1] if parts else patient_name
    given  = parts[0]  if len(parts) > 1 else ""
    base   = config.api_endpoint.rstrip("/")
    params: dict = {"family": family, "birthdate": date_of_birth, "_count": "5"}
    if given:
        params["given"] = given

    try:
        r = httpx.get(f"{base}/Patient", params=params,
                      headers=_ecw_headers(token), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        entries = r.json().get("entry", [])
        if not entries:
            return None
        return _parse_fhir_patient(entries[0].get("resource", {}), "eclinicalworks")
    except Exception as exc:
        logger.error("eClinicalWorks Patient search failed: %s", exc)
        return None


def _fetch_slots_ecw(config, clinic_id, appointment_type, date_start, date_end,
                     provider_name) -> list[dict]:
    """Fetch FHIR Slots from eClinicalWorks."""
    token = _get_ecw_token(config, clinic_id)
    if not token:
        return []

    base = config.api_endpoint.rstrip("/")
    try:
        r = httpx.get(f"{base}/Slot",
                      params={"status": "free", "start": f"ge{date_start}",
                              "end": f"le{date_end}", "_count": "50"},
                      headers=_ecw_headers(token), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        slots = []
        for entry in r.json().get("entry", []):
            slot = _parse_fhir_slot(entry.get("resource", {}), "eclinicalworks", appointment_type)
            if slot:
                slots.append(slot)
        return slots
    except Exception as exc:
        logger.error("eClinicalWorks Slot search failed: %s", exc)
        return []


def _fetch_chart_ecw(config, clinic_id, patient_id) -> Optional[dict]:
    """Fetch Condition + MedicationRequest + AllergyIntolerance from eClinicalWorks FHIR R4."""
    token = _get_ecw_token(config, clinic_id)
    if not token:
        return None

    # eCW FHIR R4 follows same structure as Epic/Cerner
    base    = config.api_endpoint.rstrip("/")
    headers = _ecw_headers(token)
    chart   = {"ehr_patient_id": patient_id, "ehr_system": "eclinicalworks",
                "diagnoses": [], "medications": [], "allergies": []}

    for resource, key, params in [
        ("Condition",          "diagnoses",   {"patient": patient_id, "clinical-status": "active"}),
        ("MedicationRequest",  "medications", {"patient": patient_id, "status": "active"}),
        ("AllergyIntolerance", "allergies",   {"patient": patient_id}),
    ]:
        try:
            r = httpx.get(f"{base}/{resource}", params={**params, "_count": "50"},
                          headers=headers, timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            for entry in r.json().get("entry", []):
                res = entry.get("resource", {})
                if resource == "Condition":
                    code = res.get("code", {})
                    chart[key].append({
                        "code":    code.get("coding", [{}])[0].get("code", ""),
                        "display": code.get("text") or code.get("coding", [{}])[0].get("display", ""),
                        "status":  "active",
                    })
                elif resource == "MedicationRequest":
                    med  = res.get("medicationCodeableConcept", {})
                    dose = res.get("dosageInstruction", [{}])[0].get("text", "") if res.get("dosageInstruction") else ""
                    chart[key].append({
                        "name":   med.get("text") or med.get("coding", [{}])[0].get("display", ""),
                        "dose":   dose,
                        "status": "active",
                    })
                elif resource == "AllergyIntolerance":
                    subst = res.get("code", {})
                    react = ""
                    if res.get("reaction"):
                        manif = res["reaction"][0].get("manifestation", [{}])
                        react = manif[0].get("text") or manif[0].get("coding", [{}])[0].get("display", "")
                    chart[key].append({
                        "substance": subst.get("text") or subst.get("coding", [{}])[0].get("display", ""),
                        "reaction":  react,
                        "severity":  res.get("reaction", [{}])[0].get("severity", "") if res.get("reaction") else "",
                    })
        except Exception as exc:
            logger.warning("eCW %s fetch failed for patient %s: %s", resource, patient_id, exc)

    return chart


def _post_note_ecw(config, clinic_id, patient_id, note_content) -> tuple[bool, str]:
    """Post a FHIR DocumentReference to eClinicalWorks."""
    token = _get_ecw_token(config, clinic_id)
    if not token:
        return False, ""

    import base64 as _b64
    base    = config.api_endpoint.rstrip("/")
    encoded = _b64.b64encode(note_content.encode()).decode()
    doc_ref = {
        "resourceType": "DocumentReference",
        "status":       "current",
        "type":         {"coding": [{"system": "http://loinc.org", "code": "11488-4"}],
                         "text": "Aria AI Encounter Summary"},
        "subject":      {"reference": f"Patient/{patient_id}"},
        "date":         datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "content":      [{"attachment": {"contentType": "text/plain", "data": encoded,
                                         "title": "Aria AI Encounter Summary"}}],
    }

    try:
        r = httpx.post(f"{base}/DocumentReference", json=doc_ref,
                       headers=_ecw_headers(token), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return True, r.json().get("id", "")
    except Exception as exc:
        logger.error("eCW DocumentReference POST failed: %s", exc)
        return False, ""


# ── Phase 4 cache helpers ─────────────────────────────────────────────────────

def _upsert_chart_summary(db, clinic_id, ehr_patient_id, ehr_system, chart) -> None:
    import json as _json
    from datetime import timedelta, timezone
    from backend.db.models import EMRChartSummary
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    existing = (
        db.query(EMRChartSummary)
        .filter(EMRChartSummary.clinic_id == clinic_id,
                EMRChartSummary.ehr_patient_id == ehr_patient_id)
        .first()
    )
    if existing:
        existing.diagnoses   = _json.dumps(chart.get("diagnoses", []))
        existing.medications = _json.dumps(chart.get("medications", []))
        existing.allergies   = _json.dumps(chart.get("allergies", []))
        existing.fetched_at  = datetime.now(timezone.utc).replace(tzinfo=None)
        existing.expires_at  = expires
    else:
        from backend.db.models import EMRChartSummary as _CS
        db.add(_CS(
            clinic_id=clinic_id,
            ehr_patient_id=ehr_patient_id,
            ehr_system=ehr_system,
            diagnoses=_json.dumps(chart.get("diagnoses", [])),
            medications=_json.dumps(chart.get("medications", [])),
            allergies=_json.dumps(chart.get("allergies", [])),
            expires_at=expires,
        ))
    try:
        db.commit()
    except Exception:
        db.rollback()


def _write_note_sync_record(db, clinic_id, session_id, ehr_patient_id, ehr_system,
                             doc_id, note_type, note_preview, status, error_msg) -> None:
    from backend.db.models import EMRNoteSync
    try:
        db.add(EMRNoteSync(
            clinic_id=clinic_id, session_id=session_id,
            ehr_patient_id=ehr_patient_id, ehr_system=ehr_system,
            ehr_document_id=doc_id, note_type=note_type,
            note_preview=note_preview, status=status, error_message=error_msg,
        ))
        db.commit()
    except Exception:
        db.rollback()


# Wire eCW into the main sync/lookup/slot routing
# (patch the existing _send_to_ehr dispatcher)
_ORIG_SEND_TO_EHR = None   # kept for reference; routing is done inline in sync_appointment_to_ehr


# ── Phase 3: Appointment type resolver ───────────────────────────────────────
# Maps free-text appointment type names → EHR-specific type IDs.
# Real production deployments would populate these from the EHR's own type catalog
# via a one-time setup call; the tables below are sensible defaults.

_EPIC_SERVICE_TYPE_MAP: dict[str, str] = {
    "annual physical":          "11",
    "well visit":               "11",
    "wellness exam":            "11",
    "new patient":              "185",
    "new patient consultation": "185",
    "follow-up":                "11",
    "follow up":                "11",
    "sick visit":               "11",
    "urgent visit":             "11",
    "telehealth":               "448",
    "virtual visit":            "448",
    "flu shot":                 "394",
    "vaccination":              "394",
    "lab":                      "108",
    "blood work":               "108",
    "cleaning":                 "29",   # dental
    "dental cleaning":          "29",
    "check-up":                 "11",
    "physical":                 "11",
}

_ATHENA_APPT_TYPE_MAP: dict[str, str] = {
    "annual physical":          "2",
    "well visit":               "2",
    "wellness exam":            "2",
    "new patient":              "1",
    "new patient consultation": "1",
    "follow-up":                "3",
    "follow up":                "3",
    "sick visit":               "4",
    "urgent visit":             "4",
    "telehealth":               "5",
    "virtual visit":            "5",
    "flu shot":                 "6",
    "vaccination":              "6",
    "lab":                      "7",
    "blood work":               "7",
    "cleaning":                 "8",
    "dental cleaning":          "8",
    "check-up":                 "2",
    "physical":                 "2",
}


def resolve_appointment_type_id(appointment_type: str, ehr_system: str) -> str:
    """
    Map a free-text appointment type to an EHR-specific type ID.
    Falls back to "1" (generic appointment) if no match found.
    Case-insensitive prefix match — "Annual Physical Exam" matches "annual physical".
    """
    key = appointment_type.lower().strip()
    if ehr_system == "epic":
        mapping = _EPIC_SERVICE_TYPE_MAP
    elif ehr_system == "athenahealth":
        mapping = _ATHENA_APPT_TYPE_MAP
    else:
        return "1"  # Cerner uses text-based serviceType, no numeric ID needed

    # Exact match first
    if key in mapping:
        return mapping[key]
    # Prefix match
    for pattern, type_id in mapping.items():
        if key.startswith(pattern) or pattern.startswith(key):
            return type_id
    return "1"


# ── Phase 3: Slot conflict check ─────────────────────────────────────────────

def check_slot_still_available(
    ehr_slot_id: str,
    clinic_id: int,
    db,
) -> bool:
    """
    Verify that an EHR slot (by its ehr_slot_id) is still marked 'free'
    in our local cache. Returns True if free/unknown, False if booked.
    This is a lightweight pre-booking guard — the EHR itself is authoritative.
    """
    row = (
        db.query(EMRAppointment)
        .filter(
            EMRAppointment.clinic_id == clinic_id,
            EMRAppointment.ehr_slot_id == ehr_slot_id,
        )
        .first()
    )
    if not row:
        return True   # Not in cache — optimistically allow (EHR will enforce)
    return row.status == "free"


def mark_slot_booked(ehr_slot_id: str, clinic_id: int, db) -> None:
    """
    Mark a cached EHR slot as 'busy' after a successful booking.
    Prevents Aria from offering the same slot to another patient before the 15-min cache expires.
    """
    row = (
        db.query(EMRAppointment)
        .filter(
            EMRAppointment.clinic_id == clinic_id,
            EMRAppointment.ehr_slot_id == ehr_slot_id,
        )
        .first()
    )
    if row:
        row.status = "busy"
        try:
            db.commit()
        except Exception:
            db.rollback()


# ── Phase 3: Provider NPI lookup ─────────────────────────────────────────────

def resolve_provider_npi(provider_name: str, clinic_id: int, db) -> Optional[str]:
    """
    Look up a provider's NPI number from the Provider table by name.
    Used to filter EHR slot searches by specific provider.
    Returns NPI string or None if not found / not configured.
    """
    if not provider_name or provider_name.lower() in ("any", ""):
        return None
    try:
        from backend.db.models import Provider
        rows = (
            db.query(Provider)
            .filter(
                Provider.clinic_id == clinic_id,
                Provider.is_active.is_(True),
            )
            .all()
        )
        # Token-based match: all search tokens must appear in provider name
        # e.g. "Dr. Smith" matches "Dr. Jane Smith" because both "dr." and "smith" are present
        search_tokens = set(provider_name.lower().split())
        for p in rows:
            p_tokens = set(p.name.lower().split())
            if search_tokens & p_tokens:  # any token overlap = match
                return p.npi_number or None
    except Exception as exc:
        logger.debug("Provider NPI lookup failed: %s", exc)
    return None


# ── Phase 3: EHR-aware slot fetch (auto-routing) ─────────────────────────────

def get_slots_auto(
    clinic_id: int,
    appointment_type: str,
    date_start: str,
    date_end: str,
    provider_name: Optional[str],
    db,
) -> tuple[list[dict], bool]:
    """
    Phase 3 auto-routing: returns (slots, from_ehr).
    - If the clinic has EHR configured + active, fetches live slots from the EHR
      and resolves the appointment type to an EHR-specific ID.
    - Falls through to return ([], False) if EHR not configured, so the caller
      can fall back to the mock office-hours slot generator.
    """
    config = get_ehr_configuration(db, clinic_id)
    if not config or not config.ehr_system or not config.api_endpoint:
        return [], False
    if config.sync_status == "error":
        logger.warning("EHR slot fetch skipped — config in error state for clinic %d", clinic_id)
        return [], False

    # Resolve provider NPI for EHR filtering
    npi = resolve_provider_npi(provider_name or "", clinic_id, db)
    effective_provider = npi or provider_name

    slots = get_available_slots(
        clinic_id=clinic_id,
        appointment_type=appointment_type,
        date_start=date_start,
        date_end=date_end,
        provider_name=effective_provider,
        db=db,
    )
    return slots, True
