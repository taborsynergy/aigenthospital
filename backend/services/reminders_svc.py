"""
Appointment reminder service (EMAIL).

Sends two reminder emails before an appointment:
  1. 72-hour reminder — 3 days before
  2. 24-hour reminder — 1 day before

(The immediate booking confirmation email is sent from appointment_svc.book_appointment
 via email_svc.send_booking_confirmation_email.)

Entry point:
  send_due_reminders(db) — call from the hourly cron endpoint (/reminders/trigger)

Only clinics whose plan includes reminders (Growth/Enterprise) are processed.
Email is sent over the SendGrid HTTP transport; failures are logged, never raised.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# cron fires hourly; a 90-min window guarantees no gaps and minimal doubles
_WINDOW_MINUTES = 90


def _reminder_body(clinic, appt, hours: int) -> str:
    when = "in 3 days" if hours == 72 else "tomorrow"
    lines = [
        f"Hi {appt.patient_name or 'there'},",
        "",
        f"This is a reminder of your upcoming appointment at {clinic.name} ({when}):",
        "",
        f"Service:  {appt.appointment_type}",
        f"When:     {appt.appointment_datetime}",
    ]
    if appt.provider:
        lines.append(f"Provider: {appt.provider}")
    if getattr(clinic, "address", ""):
        lines.append(f"Where:    {clinic.address}")
    lines += ["", "What to bring: your insurance card, a photo ID, and a list of any current medications."]
    if getattr(clinic, "cancellation_policy", ""):
        lines += ["", clinic.cancellation_policy]
    if getattr(clinic, "phone", ""):
        lines += ["", f"Need to reschedule? Call us at {clinic.phone}."]
    lines += ["", "See you soon!", f"— {clinic.name}"]
    return "\n".join(lines)


def send_due_reminders(db: Session) -> dict:
    """
    Hourly cron entry point. Finds appointments due for 72h or 24h reminders and
    emails the patient. Returns {sent_72h, sent_24h, skipped, errors}.
    """
    from backend.db.crud import list_clinics
    from backend.plans import can_use_reminders

    stats = {"sent_72h": 0, "sent_24h": 0, "skipped": 0, "errors": 0}
    for clinic in list_clinics(db):
        if not can_use_reminders(clinic):
            continue  # plan gate — reminders are Growth/Enterprise only
        for appt in _find_due(db, clinic.id, 72, "reminder_72h_sent"):
            stats["sent_72h" if _send(clinic, appt, db, 72, "reminder_72h_sent") else "errors"] += 1
        for appt in _find_due(db, clinic.id, 24, "reminder_24h_sent"):
            stats["sent_24h" if _send(clinic, appt, db, 24, "reminder_24h_sent") else "errors"] += 1

    logger.info("Email reminders run complete: %s", stats)
    return stats


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_due(db: Session, clinic_id: int, hours_before: int, sent_flag: str):
    """Appointments within the reminder window, with an email, not yet reminded."""
    from backend.db.models import Appointment

    target = datetime.utcnow() + timedelta(hours=hours_before)
    window = timedelta(minutes=_WINDOW_MINUTES)

    q = db.query(Appointment).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.appointment_ts.isnot(None),
        Appointment.appointment_ts.between(target - window, target + window),
        Appointment.status.in_(["scheduled", "confirmed"]),
        Appointment.patient_email != "",
        Appointment.patient_email.isnot(None),
    )
    if sent_flag == "reminder_72h_sent":
        q = q.filter(Appointment.reminder_72h_sent.is_(False))
    else:
        q = q.filter(Appointment.reminder_24h_sent.is_(False))
    return q.all()


def _send(clinic, appt, db: Session, hours: int, sent_flag: str) -> bool:
    from backend.services.email_svc import send_email
    from backend.db.crud import update_appointment

    subject = f"Reminder: your appointment {'in 3 days' if hours == 72 else 'tomorrow'} — {clinic.name}"
    ok = send_email(to=appt.patient_email, subject=subject, body=_reminder_body(clinic, appt, hours),
                    from_name=clinic.name, reply_to=(getattr(clinic, "email", "") or "").strip())
    if ok:
        update_appointment(db, appt.confirmation_number, {sent_flag: True})
        logger.info("%dh email reminder sent: conf=%s to=%s", hours, appt.confirmation_number, appt.patient_email)
    else:
        logger.warning("%dh email reminder failed: conf=%s", hours, appt.confirmation_number)
    return ok
