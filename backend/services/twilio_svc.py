"""
Twilio SMS service.
Falls back to mock/log mode if TWILIO_* credentials are not configured.
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


def send_sms(to: str, body: str, from_: Optional[str] = None) -> bool:
    """Send an SMS. Returns True on success."""
    sender = from_ or settings.twilio_default_number
    client = _client()

    if not client:
        logger.info("[MOCK SMS] To=%s From=%s Body=%s", to, sender, body[:80])
        return True

    try:
        msg = client.messages.create(body=body, from_=sender, to=to)
        logger.info("SMS sent: sid=%s to=%s", msg.sid, to)
        return True
    except Exception as exc:
        logger.exception("Twilio send error: %s", exc)
        return False


def twiml_response(body: str) -> str:
    """Return a TwiML XML response string."""
    safe = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'


def send_appointment_reminder(to: str, patient_name: str, provider: str,
                               appt_datetime: str, clinic_name: str,
                               from_: Optional[str] = None) -> bool:
    body = (
        f"Hi {patient_name}! Confirming your appointment with {provider} "
        f"on {appt_datetime} at {clinic_name}. "
        f"Reply YES to confirm or NO to reschedule."
    )
    return send_sms(to, body, from_)


def send_recall(to: str, patient_name: str, visit_type: str,
                clinic_name: str, from_: Optional[str] = None) -> bool:
    body = (
        f"Hi {patient_name}, it's been a while since your last visit at {clinic_name}. "
        f"You may be due for your {visit_type}. Reply BOOK to schedule or STOP to unsubscribe."
    )
    return send_sms(to, body, from_)
