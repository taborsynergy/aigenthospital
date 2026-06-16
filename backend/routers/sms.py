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

router = APIRouter()
logger = logging.getLogger(__name__)


async def _validate_twilio_signature(request: Request, path_suffix: str) -> bool:
    """Validate Twilio webhook signature. Returns True if valid or no credentials configured."""
    if not settings.twilio_auth_token:
        return True
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(settings.twilio_auth_token)
    form_params = dict(await request.form())
    twilio_sig = request.headers.get("X-Twilio-Signature", "")
    url = settings.base_url.rstrip("/") + path_suffix if settings.base_url else str(request.url)
    return validator.validate(url, form_params, twilio_sig)


async def _handle_inbound(
    request: Request,
    From: str,
    To: str,
    Body: str,
    db: Session,
    channel: str,
    path_suffix: str,
):
    """Handler for inbound SMS messages."""
    if not await _validate_twilio_signature(request, path_suffix):
        logger.warning("Invalid Twilio signature — possible spoofed %s from %s",
                       channel.upper(), request.client.host if request.client else "unknown")
        return Response(content="", media_type="application/xml", status_code=403)

    lookup_to = To
    lookup_from = From

    logger.info("Inbound %s: from=%s to=%s body=%s", channel.upper(), lookup_from, lookup_to, Body[:60])

    clinic = get_clinic_by_twilio_number(db, lookup_to)
    if not clinic:
        logger.warning("No clinic found for Twilio number: %s", lookup_to)
        return Response(
            content=twiml_response("Sorry, this number is not currently active."),
            media_type="application/xml",
        )

    # Plan gate check
    plan_ok = can_use_sms(clinic)
    if not plan_ok:
        return Response(
            content=twiml_response(
                f"This channel is not available on your clinic's current plan. "
                f"Please contact us at {clinic.phone} or visit our website."
            ),
            media_type="application/xml",
        )

    # ── Recall opt-out ────────────────────────────────────────────────
    _upper = Body.strip().upper()
    if _upper in ("OPTOUT", "UNSUBSCRIBE", "STOP RECALLS"):
        from backend.services.recall_svc import handle_optout
        optout_reply = handle_optout(db, clinic.id, lookup_from)
        return Response(content=twiml_response(optout_reply), media_type="application/xml")

    # ── Recall BOOK reply ─────────────────────────────────────────────
    if _upper == "BOOK":
        from backend.services.recall_svc import handle_book_reply
        book_reply = handle_book_reply(db, clinic, lookup_from)
        if book_reply:
            return Response(content=twiml_response(book_reply), media_type="application/xml")

    # ── YES/NO reminder replies ───────────────────────────────────────
    from backend.services.reminders_svc import handle_sms_reply
    quick_reply = handle_sms_reply(db, clinic, lookup_from, Body)
    if quick_reply:
        return Response(content=twiml_response(quick_reply), media_type="application/xml")

    # ── Full Aria conversation ────────────────────────────────────────
    session_id = get_or_create_sms_session(db, clinic.id, lookup_from)
    try:
        reply, is_escalated = await aria.chat(
            clinic, session_id, Body, channel=channel, db=db
        )
    except Exception:
        logger.exception("%s agent error: clinic=%s from=%s", channel.upper(), clinic.slug, lookup_from)
        reply = f"Sorry, I ran into a technical issue. Please call us at {clinic.phone}."

    if is_escalated:
        reply += f"\n\nA team member will reach out to you at {lookup_from} shortly."

    return Response(content=twiml_response(reply), media_type="application/xml")


@router.post("/sms/inbound")
async def inbound_sms(
    request: Request,
    From: str = Form(...),
    To: str = Form(...),
    Body: str = Form(...),
    db: Session = Depends(get_db),
):
    return await _handle_inbound(request, From, To, Body, db,
                                 channel="sms", path_suffix="/sms/inbound")
