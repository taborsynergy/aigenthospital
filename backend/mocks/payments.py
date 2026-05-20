"""
Mock payment processing (Stripe/Square stand-in).
"""
import uuid
from typing import Optional

from backend.config import settings


def send_payment_link(
    patient_name: str,
    amount: float,
    channel: str,
    contact: str,
) -> dict:
    link_id = uuid.uuid4().hex[:12]
    base = settings.base_url.rstrip("/")
    payment_url = f"{base}/pay/{link_id}"

    return {
        "success": True,
        "payment_url": payment_url,
        "amount": amount,
        "patient_name": patient_name,
        "channel": channel,
        "sent_to": contact,
        "message": f"Payment link for ${amount:.2f} sent to {contact} via {channel.upper()}. Link expires in 72 hours.",
        "link_expires": "72 hours",
    }


def send_intake_form(
    patient_name: str,
    channel: str,
    patient_email: Optional[str] = None,
    patient_phone: Optional[str] = None,
) -> dict:
    form_id = uuid.uuid4().hex[:10]
    base = settings.base_url.rstrip("/")
    form_url = f"{base}/intake/{form_id}"
    contact = patient_email or patient_phone or "on file"

    return {
        "success": True,
        "form_url": form_url,
        "patient_name": patient_name,
        "sent_to": contact,
        "channel": channel,
        "message": f"Intake forms sent to {contact}. Please complete them at least 24 hours before your appointment.",
        "includes": ["Medical History", "HIPAA Consent", "Financial Policy", "Dental Anxiety Survey"],
    }
