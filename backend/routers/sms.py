"""
Twilio inbound SMS webhook.
POST /sms/inbound — called by Twilio when a patient texts the clinic's number.
"""
import logging

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.crud import get_clinic_by_twilio_number, get_or_create_sms_session
from backend.agent import aria
from backend.plans import can_use_sms
from backend.services.twilio_svc import twiml_response

router = APIRouter(prefix="/sms")
logger = logging.getLogger(__name__)


@router.post("/inbound")
async def inbound_sms(
    request: Request,
    From: str = Form(...),
    To: str = Form(...),
    Body: str = Form(...),
    db: Session = Depends(get_db),
):
    # Validate Twilio signature when credentials are configured
    if settings.twilio_auth_token:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(settings.twilio_auth_token)
        form_params = dict(await request.form())
        twilio_sig = request.headers.get("X-Twilio-Signature", "")
        # Reconstruct the URL Twilio signed — use base_url in proxy environments
        url = settings.base_url.rstrip("/") + "/sms/inbound" if settings.base_url else str(request.url)
        if not validator.validate(url, form_params, twilio_sig):
            logger.warning("Invalid Twilio signature — possible spoofed SMS from %s", request.client.host)
            return Response(content="", media_type="application/xml", status_code=403)
    logger.info("Inbound SMS: from=%s to=%s body=%s", From, To, Body[:60])

    clinic = get_clinic_by_twilio_number(db, To)
    if not clinic:
        logger.warning("No clinic found for Twilio number: %s", To)
        return Response(
            content=twiml_response("Sorry, this number is not currently active."),
            media_type="application/xml",
        )

    if not can_use_sms(clinic):
        logger.info("SMS blocked — plan does not include SMS: clinic=%s", clinic.slug)
        return Response(
            content=twiml_response(
                "SMS is not available on your clinic's current plan. "
                f"Please contact us at {clinic.phone} or visit our website."
            ),
            media_type="application/xml",
        )

    session_id = get_or_create_sms_session(db, clinic.id, From)

    try:
        reply, is_escalated = await aria.chat(
            clinic, session_id, Body, channel="sms", db=db
        )
    except Exception:
        logger.exception("SMS agent error: clinic=%s from=%s", clinic.slug, From)
        reply = f"Sorry, I ran into a technical issue. Please call us at {clinic.phone}."

    if is_escalated:
        reply += f"\n\nA team member will reach out to you at {From} shortly."

    return Response(content=twiml_response(reply), media_type="application/xml")
