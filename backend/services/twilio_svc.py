"""
Twilio SMS service.
Falls back to mock/log mode when TWILIO_* credentials are not configured.
"""
import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)
_client_cache = None


def _client():
    global _client_cache
    if _client_cache is None and settings.twilio_account_sid and settings.twilio_auth_token:
        from twilio.rest import Client
        _client_cache = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    return _client_cache


def twilio_enabled() -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token)


def send_sms(to: str, body: str, from_: Optional[str] = None) -> bool:
    """Send an SMS. Falls back to structured log when Twilio not configured."""
    if not to or not to.strip():
        return False

    sender = from_ or settings.twilio_default_number
    client = _client()

    if not client:
        logger.info("[SMS-MOCK] To=%s From=%s | %s", to, sender, body[:120])
        return True   # treat as success in dev/PayPal mode

    try:
        msg = client.messages.create(body=body, from_=sender, to=to)
        logger.info("SMS sent: sid=%s to=%s", msg.sid, to)
        return True
    except Exception as exc:
        logger.error("Twilio send error to=%s: %s", to, exc)
        return False


def twiml_response(body: str) -> str:
    """Return a TwiML XML response string."""
    safe = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'


# ── Appointment SMS templates ─────────────────────────────────────────────────

def send_booking_confirmation(
    to: str,
    patient_name: str,
    clinic_name: str,
    appointment_type: str,
    appointment_datetime: str,
    provider: str,
    confirmation_number: str,
    clinic_phone: str = "",
    from_: Optional[str] = None,
) -> bool:
    """
    Sent immediately after booking.
    Example: "Confirmed: Annual Physical with Dr. Smith at Sunshine Clinic
              on Monday, June 9 at 10:00 AM. Confirmation #SUN-0609-A1B2.
              Questions? Call 555-1234."
    """
    parts = [
        f"Confirmed: {appointment_type} with {provider} at {clinic_name}",
        f"on {appointment_datetime}.",
        f"Confirmation #{confirmation_number}.",
    ]
    if clinic_phone:
        parts.append(f"Questions? Call {clinic_phone}.")
    return send_sms(to, " ".join(parts), from_)


def send_reminder_72h(
    to: str,
    patient_name: str,
    clinic_name: str,
    appointment_type: str,
    appointment_datetime: str,
    provider: str,
    clinic_phone: str = "",
    from_: Optional[str] = None,
) -> bool:
    """
    Sent ~72 hours before appointment.
    Patient can reply YES to confirm or NO to cancel.
    """
    body = (
        f"Hi {patient_name}! Reminder: {appointment_type} with {provider} "
        f"at {clinic_name} on {appointment_datetime}. "
        f"Reply YES to confirm or NO to cancel."
    )
    if clinic_phone:
        body += f" Questions? Call {clinic_phone}."
    return send_sms(to, body, from_)


def send_reminder_24h(
    to: str,
    patient_name: str,
    clinic_name: str,
    appointment_type: str,
    appointment_datetime: str,
    provider: str,
    clinic_phone: str = "",
    from_: Optional[str] = None,
) -> bool:
    """
    Sent ~24 hours before appointment.
    """
    body = (
        f"Hi {patient_name}! Your {appointment_type} at {clinic_name} "
        f"is tomorrow: {appointment_datetime} with {provider}. "
        f"Reply NO to cancel."
    )
    if clinic_phone:
        body += f" Questions? Call {clinic_phone}."
    return send_sms(to, body, from_)


def send_cancellation_confirmation(
    to: str,
    patient_name: str,
    clinic_name: str,
    appointment_datetime: str,
    clinic_phone: str = "",
    from_: Optional[str] = None,
) -> bool:
    """Sent when a patient cancels via SMS reply."""
    body = (
        f"Hi {patient_name}, your appointment at {clinic_name} on "
        f"{appointment_datetime} has been cancelled. "
        f"To rebook, text us or call {clinic_phone or clinic_name}."
    )
    return send_sms(to, body, from_)


def send_appointment_reminder(
    to: str,
    patient_name: str,
    provider: str,
    appt_datetime: str,
    clinic_name: str,
    from_: Optional[str] = None,
) -> bool:
    """Legacy wrapper — kept for backwards compatibility."""
    return send_reminder_72h(
        to=to,
        patient_name=patient_name,
        clinic_name=clinic_name,
        appointment_type="appointment",
        appointment_datetime=appt_datetime,
        provider=provider,
        from_=from_,
    )


def send_recall(
    to: str,
    patient_name: str,
    visit_type: str,
    clinic_name: str,
    from_: Optional[str] = None,
) -> bool:
    body = (
        f"Hi {patient_name}, it's been a while since your last visit at {clinic_name}. "
        f"You may be due for your {visit_type}. "
        f"Reply BOOK to schedule or STOP to unsubscribe."
    )
    return send_sms(to, body, from_)


# WhatsApp messaging was removed — SMS is the supported text channel.
# (WhatsApp requires per-clinic Meta Business sender approval, handled out of band.)
