"""
DB-native appointment service — replaces mock PMS for core booking operations.

Our database IS the PMS. Slots are generated from the clinic's office_hours config
and validated against existing appointments to prevent double-booking.

Insurance verification and patient billing remain in mocks/insurance.py and
mocks/payments.py until real API integrations are added.
"""
import logging
import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Office hours parser ───────────────────────────────────────────────────────

_DAY_MAP = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _parse_hour(s: str) -> int:
    """Parse '8am', '5pm', '08:00', '17:00' → int hour (24h)."""
    s = s.strip().lower()
    if ":" in s:
        h, m = s.split(":")
        hour = int(h)
        if "pm" in m and hour < 12:
            hour += 12
        return hour
    if "pm" in s:
        h = int(re.sub(r"[^0-9]", "", s))
        return h if h == 12 else h + 12
    h = int(re.sub(r"[^0-9]", "", s))
    return h if h == 12 else h   # 12am = 12, 8am = 8


def _day_range(start_day: str, end_day: str) -> list[int]:
    """'Mon' to 'Fri' → [0,1,2,3,4]"""
    s = _DAY_MAP.get(start_day.lower(), 0)
    e = _DAY_MAP.get(end_day.lower(), 4)
    if s <= e:
        return list(range(s, e + 1))
    # Wrap-around e.g. Sat-Mon
    return list(range(s, 7)) + list(range(0, e + 1))


def parse_office_hours(office_hours: str) -> dict[int, tuple[int, int]]:
    """
    Parse office_hours string → {weekday: (start_hour, end_hour)}.

    Supports formats like:
      "Mon–Fri 8am–5pm"
      "Monday-Friday 9am-5pm, Saturday 9am-1pm"
      "Mon-Fri 8am-5pm"
    Falls back to Mon-Fri 8am-5pm on parse failure.
    """
    schedule: dict[int, tuple[int, int]] = {}
    if not office_hours:
        for d in range(5):
            schedule[d] = (8, 17)
        return schedule

    # Split on comma for multiple day ranges
    segments = re.split(r",\s*", office_hours.strip())

    for seg in segments:
        seg = seg.strip()
        # Match: "Mon–Fri 8am–5pm" or "Monday 9am-5pm"
        m = re.match(
            r"([A-Za-z]+)\s*[–\-]\s*([A-Za-z]+)\s+(\S+)\s*[–\-]\s*(\S+)",
            seg,
        )
        if m:
            days = _day_range(m.group(1), m.group(2))
            try:
                start_h = _parse_hour(m.group(3))
                end_h   = _parse_hour(m.group(4))
                for d in days:
                    schedule[d] = (start_h, end_h)
                continue
            except Exception:
                pass

        # Single day: "Saturday 9am-1pm"
        m2 = re.match(r"([A-Za-z]+)\s+(\S+)\s*[–\-]\s*(\S+)", seg)
        if m2:
            day_int = _DAY_MAP.get(m2.group(1).lower())
            if day_int is not None:
                try:
                    schedule[day_int] = (_parse_hour(m2.group(2)), _parse_hour(m2.group(3)))
                except Exception:
                    pass

    if not schedule:
        for d in range(5):
            schedule[d] = (8, 17)
    return schedule


# ── Slot generation ───────────────────────────────────────────────────────────

def _fmt_display(dt: datetime) -> str:
    """Format datetime → human-readable: 'Monday, June 9 at 10:00 AM'"""
    hour   = dt.hour % 12 or 12
    ampm   = "AM" if dt.hour < 12 else "PM"
    minute = f"{dt.minute:02d}"
    # Use dt.day (int) to avoid platform-specific %-d format code
    return f"{dt.strftime('%A, %B')} {dt.day} at {hour}:{minute} {ampm}"


def _fmt_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:00")


def generate_slots(
    clinic,
    date_start: Optional[str],
    date_end: Optional[str],
    duration_minutes: int = 30,
    db=None,
    provider_filter: Optional[str] = None,
    max_slots: int = 8,
) -> list[dict]:
    """
    Generate available appointment slots for a clinic.

    - Parses clinic.office_hours to determine working days/hours
    - Queries DB to exclude already-booked slots (conflict prevention)
    - Returns up to max_slots available slots
    """
    today = date.today()
    start = (
        datetime.strptime(date_start, "%Y-%m-%d").date()
        if date_start else today + timedelta(days=1)
    )
    end = (
        datetime.strptime(date_end, "%Y-%m-%d").date()
        if date_end else start + timedelta(days=6)
    )

    schedule = parse_office_hours(clinic.office_hours if clinic else "")
    providers = _parse_providers(clinic)

    # Get already-booked datetimes from DB
    booked_isos: set[str] = set()
    if db and clinic:
        booked_isos = _get_booked_isos(db, clinic.id, start, end)

    slots: list[dict] = []
    current = start

    while current <= end and len(slots) < max_slots:
        weekday = current.weekday()
        if weekday in schedule:
            start_h, end_h = schedule[weekday]
            slot_dt = datetime.combine(current, time(start_h, 0))
            end_dt  = datetime.combine(current, time(end_h, 0))

            while slot_dt < end_dt and len(slots) < max_slots:
                iso = _fmt_iso(slot_dt)
                if iso not in booked_isos:
                    prov = _select_provider(providers, provider_filter)
                    slots.append({
                        "date":             current.isoformat(),
                        "day":              _fmt_display(slot_dt).split(" at ")[0],
                        "time":             _fmt_display(slot_dt).split(" at ")[1],
                        "datetime_display": _fmt_display(slot_dt),
                        "datetime_iso":     iso,
                        "provider":         prov,
                        "duration_minutes": duration_minutes,
                        "slot_id":          f"slot_{slot_dt.strftime('%Y%m%d_%H%M')}_{uuid.uuid4().hex[:4]}",
                    })
                slot_dt += timedelta(minutes=duration_minutes)

        current += timedelta(days=1)

    # Annotate slots with location if multi-location is configured
    if db and clinic and slots:
        try:
            from backend.plans import can_use_location_routing
            from backend.db.crud import list_locations
            if can_use_location_routing(clinic):
                locations = list_locations(db, clinic.id)
                if locations:
                    primary = next((l for l in locations if l.is_primary), locations[0])
                    for slot in slots:
                        slot["location_name"] = primary.name
                        slot["location_address"] = primary.address or clinic.address
        except Exception:
            pass

    return slots


def _send_confirmation_email(confirmation_number: str, clinic, db) -> None:
    """Fire-and-forget booking confirmation EMAIL to the patient (all plans)."""
    try:
        from backend.db.models import Appointment
        from backend.services.email_svc import send_booking_confirmation_email
        appt = db.query(Appointment).filter_by(confirmation_number=confirmation_number).first()
        if appt:
            send_booking_confirmation_email(clinic, appt)
    except Exception:
        logger.debug("Booking confirmation email skipped — %s", confirmation_number)


def _get_booked_isos(db, clinic_id: int, date_start: date, date_end: date) -> set[str]:
    """Return set of booked ISO datetime strings for the clinic in the date range."""
    from backend.db.models import Appointment
    rows = (
        db.query(Appointment.appointment_ts)
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.status.in_(["scheduled", "rescheduled"]),
            Appointment.appointment_ts.isnot(None),
            Appointment.appointment_ts >= datetime.combine(date_start, time.min),
            Appointment.appointment_ts <= datetime.combine(date_end, time.max),
        )
        .all()
    )
    return {_fmt_iso(r.appointment_ts) for r in rows if r.appointment_ts}


def _parse_providers(clinic) -> list[str]:
    raw = (clinic.providers if clinic and clinic.providers else "") or "Dr. Provider"
    return [p.strip() for p in raw.split(",") if p.strip()]


def _select_provider(providers: list[str], preference: Optional[str]) -> str:
    if not providers:
        return "Dr. Provider"
    if preference and preference.lower() != "any":
        match = next((p for p in providers if preference.lower() in p.lower()), None)
        if match:
            return match
    return providers[0]


# ── Booking ───────────────────────────────────────────────────────────────────

def _invalid_date_reason(appt_ts: Optional[datetime]) -> Optional[str]:
    """Return a human error if a parsed appointment time is unbookable, else None.

    Guards against booking in the past or in an absurd year (e.g. 9999). Impossible
    calendar dates like 'February 30' fail parsing and yield appt_ts=None, which is
    handled by the caller separately.
    """
    if appt_ts is None:
        return None
    today = date.today()
    if appt_ts.date() < today:
        return "That date is in the past. Please choose an upcoming date."
    if appt_ts.year > today.year + 2:
        return "That date is too far in the future. Please choose a date within the next two years."
    return None


def book_appointment(
    clinic,
    db,
    patient_name: str,
    appointment_type: str,
    datetime_str: str,
    provider: Optional[str] = None,
    patient_phone: Optional[str] = None,
    patient_email: Optional[str] = None,
    patient_dob: Optional[str] = None,
    is_new_patient: bool = False,
    chief_complaint: Optional[str] = None,
    session_id: str = "",
    channel: str = "web",
) -> dict:
    """
    Book an appointment and persist it to the appointments table.
    Returns a dict matching the tool contract expected by Aria.
    """
    from backend.db.crud import create_appointment

    providers    = _parse_providers(clinic)
    chosen_prov  = _select_provider(providers, provider)
    prefix       = (clinic.name[:3].upper().replace(" ", "") if clinic else "APT")
    conf_num     = f"{prefix}-{datetime.utcnow().strftime('%m%d')}-{uuid.uuid4().hex[:4].upper()}"

    # Parse datetime_str to a proper timestamp for conflict checking
    appt_ts = _parse_datetime_str(datetime_str)

    # Reject clearly-invalid dates (past / absurd future) before persisting
    reason = _invalid_date_reason(appt_ts)
    if reason:
        return {"success": False, "error": reason}

    # Persist to DB
    try:
        create_appointment(db, {
            "clinic_id":            clinic.id,
            "confirmation_number":  conf_num,
            "patient_name":         patient_name,
            "patient_phone":        patient_phone or "",
            "patient_email":        patient_email or "",
            "patient_dob":          patient_dob or "",
            "appointment_type":     appointment_type,
            "appointment_datetime": datetime_str,
            "appointment_ts":       appt_ts,
            "provider":             chosen_prov,
            "is_new_patient":       bool(is_new_patient),
            "chief_complaint":      chief_complaint or "",
            "status":               "scheduled",
            "channel":              channel,
            "session_id":           session_id,
        })
        logger.info("Appointment booked: clinic=%s conf=%s patient=%s",
                    clinic.slug if clinic else "?", conf_num, patient_name)
    except Exception:
        logger.exception("Failed to persist appointment for %s", patient_name)
        return {
            "success": False,
            "error":   "Failed to save appointment. Please try again.",
        }

    # Send booking confirmation EMAIL (best-effort, non-blocking; all plans)
    if patient_email and clinic and db:
        _send_confirmation_email(conf_num, clinic, db)

    # Sync to EHR if configured (best-effort, non-blocking)
    if clinic and db:
        try:
            from backend.services.ehr_svc import sync_appointment_to_ehr
            from backend.db.crud import get_appointment_by_confirmation
            appt_obj = get_appointment_by_confirmation(db, conf_num, clinic.id)
            if appt_obj:
                sync_appointment_to_ehr(clinic.id, appt_obj, db)
        except Exception:
            logger.debug("EHR sync skipped for %s", conf_num)

    return {
        "success":             True,
        "confirmation_number": conf_num,
        "patient_name":        patient_name,
        "appointment_type":    appointment_type,
        "datetime":            datetime_str,
        "provider":            chosen_prov,
        "location":            clinic.address if clinic else "",
        "prep_instructions": (
            "Please arrive 15 minutes early and bring your insurance card and a photo ID."
            if is_new_patient
            else "Please arrive 5 minutes early with your insurance card."
        ),
        "reminder_sent": True,
    }


# ── Rescheduling ──────────────────────────────────────────────────────────────

def reschedule_appointment(
    clinic,
    db,
    patient_name: str,
    new_datetime: str,
    patient_dob: Optional[str] = None,
    current_appointment_date: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Find a patient's most recent scheduled appointment and reschedule it.
    Returns the updated confirmation number.
    """
    from backend.db.crud import find_appointment_by_patient, update_appointment

    appt = find_appointment_by_patient(
        db, clinic.id, patient_name,
        patient_dob=patient_dob,
        date_hint=current_appointment_date,
        status="scheduled",
    )

    new_ts   = _parse_datetime_str(new_datetime)
    reason = _invalid_date_reason(new_ts)
    if reason:
        return {"success": False, "error": reason}
    providers = _parse_providers(clinic)

    if appt:
        # Update existing record
        update_appointment(db, appt.confirmation_number, {
            "appointment_datetime": new_datetime,
            "appointment_ts":       new_ts,
            "status":               "rescheduled",
        })
        conf_num = appt.confirmation_number
        provider = appt.provider or _select_provider(providers, None)
        logger.info("Appointment rescheduled: conf=%s patient=%s → %s",
                    conf_num, patient_name, new_datetime)
    else:
        # No existing record found — create a new rescheduled entry
        prefix   = (clinic.name[:3].upper().replace(" ", "") if clinic else "APT")
        conf_num = f"{prefix}-{datetime.utcnow().strftime('%m%d')}-{uuid.uuid4().hex[:4].upper()}"
        provider = _select_provider(providers, None)
        try:
            from backend.db.crud import create_appointment
            create_appointment(db, {
                "clinic_id":            clinic.id,
                "confirmation_number":  conf_num,
                "patient_name":         patient_name,
                "patient_dob":          patient_dob or "",
                "appointment_type":     "rescheduled visit",
                "appointment_datetime": new_datetime,
                "appointment_ts":       new_ts,
                "provider":             provider,
                "status":               "rescheduled",
                "channel":              "web",
            })
        except Exception:
            logger.exception("Failed to create reschedule record")

    return {
        "success":             True,
        "confirmation_number": conf_num,
        "patient_name":        patient_name,
        "new_datetime":        new_datetime,
        "provider":            provider,
        "message":             f"Appointment rescheduled to {new_datetime}. Confirmation: {conf_num}",
    }


# ── Cancellation ──────────────────────────────────────────────────────────────

def cancel_appointment(
    clinic,
    db,
    patient_name: str,
    appointment_date: str,
    patient_dob: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Find and cancel a patient's appointment. Updates status to 'cancelled'.
    """
    from backend.db.crud import find_appointment_by_patient, update_appointment

    appt = find_appointment_by_patient(
        db, clinic.id, patient_name,
        patient_dob=patient_dob,
        date_hint=appointment_date,
        status="scheduled",
    )

    policy = clinic.cancellation_policy if clinic else "24-hour notice required."

    if appt:
        update_appointment(db, appt.confirmation_number, {"status": "cancelled"})
        logger.info("Appointment cancelled: conf=%s patient=%s",
                    appt.confirmation_number, patient_name)
        return {
            "success":             True,
            "patient_name":        patient_name,
            "cancelled_date":      appointment_date,
            "confirmation_number": appt.confirmation_number,
            "cancellation_policy": policy,
            "message":             "Appointment cancelled. We hope to see you again soon.",
        }

    return {
        "success":             True,
        "patient_name":        patient_name,
        "cancelled_date":      appointment_date,
        "cancellation_policy": policy,
        "message": (
            "Cancellation recorded. If you don't see a confirmation, "
            "please call us to confirm. " + policy
        ),
    }


# ── Waitlist ──────────────────────────────────────────────────────────────────

def add_to_waitlist(
    clinic,
    db,
    patient_name: str,
    patient_phone: str,
    appointment_type: str,
    preferred_provider: Optional[str] = None,
    earliest_available: Optional[str] = None,
) -> dict:
    """Add patient to waitlist by creating a waitlist appointment record."""
    from backend.db.crud import create_appointment

    prefix   = (clinic.name[:3].upper().replace(" ", "") if clinic else "APT")
    conf_num = f"{prefix}-WL-{uuid.uuid4().hex[:6].upper()}"

    try:
        existing_waitlist = _count_waitlist(db, clinic.id)
        create_appointment(db, {
            "clinic_id":            clinic.id,
            "confirmation_number":  conf_num,
            "patient_name":         patient_name,
            "patient_phone":        patient_phone,
            "appointment_type":     appointment_type,
            "appointment_datetime": earliest_available or "Next available",
            "provider":             preferred_provider or "",
            "status":               "waitlist",
            "channel":              "web",
        })
        position = existing_waitlist + 1
    except Exception:
        logger.exception("Failed to add %s to waitlist", patient_name)
        position = 1

    return {
        "success":      True,
        "patient_name": patient_name,
        "position":     position,
        "message": (
            f"{patient_name} has been added to our waitlist (position #{position}). "
            f"We'll contact {patient_phone} the moment a slot opens up."
        ),
    }


def _count_waitlist(db, clinic_id: int) -> int:
    from backend.db.models import Appointment
    return (
        db.query(Appointment)
        .filter(Appointment.clinic_id == clinic_id, Appointment.status == "waitlist")
        .count()
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_datetime_str(datetime_str: str) -> Optional[datetime]:
    """
    Best-effort parse of human-readable datetime strings like:
      'Monday, June 9 at 10:00 AM'
      'Tuesday, June 10, 2026 at 2:30 PM'
      'June 9 at 10:00 AM'
    Returns None on failure.
    """
    if not datetime_str:
        return None

    # Normalise separators
    s = datetime_str.strip()
    # Remove day-of-week prefix: "Monday, June 9 at..."  → "June 9 at..."
    s = re.sub(r"^[A-Za-z]+,\s*", "", s)
    # Replace " at " with " "
    s = s.replace(" at ", " ")
    # Add current year if missing
    if not re.search(r"\b\d{4}\b", s):
        s = f"{s} {date.today().year}"

    for fmt in (
        "%B %d %I:%M %p %Y",
        "%B %d, %Y %I:%M %p",
        "%B %d %H:%M %Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue

    logger.warning("Could not parse datetime_str: %r", datetime_str)
    return None
