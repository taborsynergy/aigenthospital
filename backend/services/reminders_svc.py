"""
Appointment reminder service.

Sends three types of SMS messages:
  1. Booking confirmation — immediately after a patient books
  2. 72-hour reminder    — 3 days before the appointment
  3. 24-hour reminder    — 1 day before the appointment

Entry points:
  send_booking_confirmation_sms(clinic, appointment) — call from appointment_svc.book_appointment()
  send_due_reminders(db)                             — call from the hourly cron endpoint

Only clinics on Professional or Enterprise plans receive SMS (plan gate enforced here).
Falls back gracefully when Twilio is not configured (logs a mock send).
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# How wide a window around the target time we consider "due"
# (cron fires every hour, so 90-min window guarantees no gaps and minimal doubles)
_WINDOW_MINUTES = 90


def send_booking_confirmation_sms(clinic, appointment, db: Session) -> bool:
    """
    Send an immediate booking confirmation SMS to the patient.
    Called right after a successful book_appointment() call.
    Silently skips if: no patient_phone, plan doesn't include SMS, Twilio not configured.
    """
    from backend.plans import can_use_sms
    from backend.services.twilio_svc import send_booking_confirmation
    from backend.db.crud import update_appointment

    if not appointment.patient_phone:
        return False
    if not can_use_sms(clinic):
        return False

    from_number = clinic.twilio_phone or None
    ok = send_booking_confirmation(
        to=appointment.patient_phone,
        patient_name=appointment.patient_name,
        clinic_name=clinic.name,
        appointment_type=appointment.appointment_type,
        appointment_datetime=appointment.appointment_datetime,
        provider=appointment.provider or "",
        confirmation_number=appointment.confirmation_number,
        clinic_phone=clinic.phone or "",
        from_=from_number,
    )
    if ok:
        update_appointment(db, appointment.confirmation_number, {"confirmation_sent": True})
        logger.info("Booking confirmation SMS sent: conf=%s to=%s",
                    appointment.confirmation_number, appointment.patient_phone)
    return ok


def send_due_reminders(db: Session) -> dict:
    """
    Main entry point for the hourly cron job.
    Finds all appointments due for 72h or 24h reminders and sends them.

    Returns a summary dict: {sent_72h, sent_24h, skipped, errors}
    """
    from backend.db.crud import list_clinics
    from backend.plans import can_use_sms

    stats = {"sent_72h": 0, "sent_24h": 0, "skipped": 0, "errors": 0}
    clinics = list_clinics(db)

    for clinic in clinics:
        if not can_use_sms(clinic):
            continue  # plan gate — SMS is Pro/Enterprise only

        # 72-hour reminders
        due_72h = _find_due(db, clinic.id, hours_before=72, sent_flag="reminder_72h_sent")
        for appt in due_72h:
            sent = _send_72h(clinic, appt, db)
            stats["sent_72h" if sent else "errors"] += 1

        # 24-hour reminders
        due_24h = _find_due(db, clinic.id, hours_before=24, sent_flag="reminder_24h_sent")
        for appt in due_24h:
            sent = _send_24h(clinic, appt, db)
            stats["sent_24h" if sent else "errors"] += 1

    logger.info("Reminders run complete: %s", stats)
    return stats


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_due(db: Session, clinic_id: int, hours_before: int, sent_flag: str):
    """
    Find appointments whose appointment_ts is within the reminder window
    and whose reminder flag hasn't been set yet.
    """
    from backend.db.models import Appointment

    now     = datetime.utcnow()
    target  = now + timedelta(hours=hours_before)
    window  = timedelta(minutes=_WINDOW_MINUTES)
    from_dt = target - window
    to_dt   = target + window

    q = (
        db.query(Appointment)
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.appointment_ts.isnot(None),
            Appointment.appointment_ts.between(from_dt, to_dt),
            Appointment.status.in_(["scheduled", "confirmed"]),
            Appointment.patient_phone != "",
            Appointment.patient_phone.isnot(None),
        )
    )
    # Filter by unsent flag
    if sent_flag == "reminder_72h_sent":
        q = q.filter(Appointment.reminder_72h_sent.is_(False))
    else:
        q = q.filter(Appointment.reminder_24h_sent.is_(False))

    return q.all()


def _send_72h(clinic, appointment, db: Session) -> bool:
    from backend.services.twilio_svc import send_reminder_72h
    from backend.db.crud import update_appointment

    ok = send_reminder_72h(
        to=appointment.patient_phone,
        patient_name=appointment.patient_name,
        clinic_name=clinic.name,
        appointment_type=appointment.appointment_type,
        appointment_datetime=appointment.appointment_datetime,
        provider=appointment.provider or "",
        clinic_phone=clinic.phone or "",
        from_=clinic.twilio_phone or None,
    )
    if ok:
        update_appointment(db, appointment.confirmation_number, {"reminder_72h_sent": True})
        logger.info("72h reminder sent: conf=%s to=%s",
                    appointment.confirmation_number, appointment.patient_phone)
    else:
        logger.warning("72h reminder failed: conf=%s", appointment.confirmation_number)
    return ok


def _send_24h(clinic, appointment, db: Session) -> bool:
    from backend.services.twilio_svc import send_reminder_24h
    from backend.db.crud import update_appointment

    ok = send_reminder_24h(
        to=appointment.patient_phone,
        patient_name=appointment.patient_name,
        clinic_name=clinic.name,
        appointment_type=appointment.appointment_type,
        appointment_datetime=appointment.appointment_datetime,
        provider=appointment.provider or "",
        clinic_phone=clinic.phone or "",
        from_=clinic.twilio_phone or None,
    )
    if ok:
        update_appointment(db, appointment.confirmation_number, {"reminder_24h_sent": True})
        logger.info("24h reminder sent: conf=%s to=%s",
                    appointment.confirmation_number, appointment.patient_phone)
    else:
        logger.warning("24h reminder failed: conf=%s", appointment.confirmation_number)
    return ok


def handle_sms_reply(
    db: Session,
    clinic,
    patient_phone: str,
    reply_text: str,
) -> Optional[str]:
    """
    Handle YES/NO replies to appointment reminders.

    YES  → mark appointment as confirmed, reply with confirmation
    NO   → cancel appointment, reply with cancellation
    Other → return None so caller falls through to Aria

    Returns: TwiML response text, or None if not a reminder reply
    """
    from backend.db.models import Appointment
    from backend.db.crud import update_appointment
    from backend.services.twilio_svc import send_cancellation_confirmation

    text = reply_text.strip().upper()

    # Only handle clean YES or NO — everything else goes to Aria
    if text not in ("YES", "NO", "Y", "N", "CONFIRM", "CANCEL"):
        return None

    # Find the most recent scheduled/confirmed appointment for this phone + clinic
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.clinic_id == clinic.id,
            Appointment.patient_phone == patient_phone,
            Appointment.status.in_(["scheduled", "confirmed"]),
        )
        .order_by(Appointment.appointment_ts.asc())
        .first()
    )

    if not appt:
        return None  # no pending appointment — let Aria handle

    if text in ("YES", "Y", "CONFIRM"):
        update_appointment(db, appt.confirmation_number, {"status": "confirmed"})
        logger.info("Appointment confirmed via SMS reply: conf=%s", appt.confirmation_number)
        return (
            f"Confirmed! We'll see you for your {appt.appointment_type} "
            f"on {appt.appointment_datetime}. "
            f"See you then, {appt.patient_name.split()[0]}!"
        )

    if text in ("NO", "N", "CANCEL"):
        update_appointment(db, appt.confirmation_number, {"status": "cancelled"})
        logger.info("Appointment cancelled via SMS reply: conf=%s", appt.confirmation_number)
        # Send cancellation confirmation (non-blocking, best-effort)
        send_cancellation_confirmation(
            to=patient_phone,
            patient_name=appt.patient_name,
            clinic_name=clinic.name,
            appointment_datetime=appt.appointment_datetime,
            clinic_phone=clinic.phone or "",
            from_=clinic.twilio_phone or None,
        )
        return (
            f"Your appointment on {appt.appointment_datetime} has been cancelled. "
            f"To rebook, just text us or call {clinic.phone or clinic.name}."
        )

    return None
