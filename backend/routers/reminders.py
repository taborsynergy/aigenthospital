"""
Appointment reminder trigger endpoint.
POST /api/reminders/trigger — called by the hourly Render cron job.

Protected by admin password so only the cron (or admin) can invoke it.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db

router = APIRouter(prefix="/api/reminders")
logger = logging.getLogger(__name__)


def _require_admin(x_admin_password: str = Header(None)):
    if (x_admin_password or "").strip() != (settings.admin_password or "").strip():
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/trigger", dependencies=[Depends(_require_admin)])
def trigger_reminders(db: Session = Depends(get_db)):
    """
    Run the reminder check: find all appointments due for 72h or 24h reminders
    and send SMS via Twilio. Marks each appointment so reminders aren't re-sent.

    Called every hour by Render cron job.
    Also available manually from the admin panel for testing.
    """
    from backend.services.reminders_svc import send_due_reminders
    stats = send_due_reminders(db)
    logger.info("Reminder trigger: %s", stats)
    return {"ok": True, **stats}


@router.post("/send-confirmation/{confirmation_number}", dependencies=[Depends(_require_admin)])
def resend_confirmation(confirmation_number: str, db: Session = Depends(get_db)):
    """Manually resend a booking confirmation EMAIL for a specific appointment."""
    from backend.db.models import Appointment
    from backend.db.crud import get_clinic_by_id
    from backend.services.email_svc import send_booking_confirmation_email

    appt = db.query(Appointment).filter_by(confirmation_number=confirmation_number).first()
    if not appt:
        raise HTTPException(404, "Appointment not found.")

    clinic = get_clinic_by_id(db, appt.clinic_id)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")

    if not appt.patient_email:
        raise HTTPException(400, "No patient email on record.")

    ok = send_booking_confirmation_email(clinic, appt)
    return {"ok": ok, "to": appt.patient_email}
