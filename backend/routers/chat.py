import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.agent import aria
from backend.db.database import get_db
from backend.db.crud import get_clinic, get_clinic_by_token, list_appointments
from backend.models.schemas import ChatMessage, ChatResponse
from backend.plans import get_plan, monthly_conversation_limit

router = APIRouter()
logger = logging.getLogger(__name__)


def _greeting(clinic) -> str:
    return (
        f"Hi there! I'm {clinic.agent_name}, the virtual front desk for {clinic.name}. "
        "How can I help you today? I can schedule appointments, answer insurance questions, "
        "help with billing, or answer any questions about our office."
    )


_CONTACT = "admin@tabor.taborsynergy.com"


def _access_blocked(clinic, db=None) -> str | None:
    """Return a block message if the clinic cannot use the chat, else None."""
    now = datetime.utcnow()
    if clinic.subscription_status == "trial":
        if clinic.trial_ends_at and now > clinic.trial_ends_at:
            return (
                "I'm sorry, this clinic's 14-day free trial has ended. "
                f"Please contact us at {_CONTACT} to activate a subscription."
            )
    elif clinic.subscription_status == "active":
        if clinic.subscription_ends_at and now > clinic.subscription_ends_at:
            return (
                "I'm sorry, this clinic's subscription has expired. "
                f"Please contact us at {_CONTACT} to renew."
            )
    elif clinic.subscription_status in ("past_due", "cancelled"):
        return (
            f"This clinic's subscription is {clinic.subscription_status}. "
            f"Please contact us at {_CONTACT} to restore access."
        )

    # Monthly conversation limit
    if db:
        limit = monthly_conversation_limit(clinic)
        if limit is not None:
            from backend.db.crud import get_usage_this_month
            used = get_usage_this_month(db, clinic.id)
            if used >= limit:
                plan = get_plan(clinic)
                return (
                    f"Your clinic has reached its {limit}-conversation limit for this month "
                    f"on the {plan['name']} plan. "
                    f"Please contact us at {_CONTACT} to upgrade."
                )
    return None


@router.websocket("/ws/{clinic_slug}/{session_id}")
async def websocket_chat(websocket: WebSocket, clinic_slug: str, session_id: str,
                         db: Session = Depends(get_db)):
    clinic = get_clinic(db, clinic_slug)
    if not clinic:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    logger.info("WS connected: clinic=%s session=%s", clinic_slug, session_id)

    block_msg = _access_blocked(clinic, db)
    if block_msg:
        await websocket.send_json({"type": "message", "content": block_msg, "session_id": session_id})
        await websocket.close(code=4003)
        return

    await websocket.send_json({
        "type": "message",
        "content": _greeting(clinic),
        "session_id": session_id,
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                user_message = payload.get("message", "").strip()
            except (json.JSONDecodeError, AttributeError):
                user_message = data.strip()

            if not user_message:
                continue

            await websocket.send_json({"type": "typing", "active": True})

            try:
                response_text, is_escalated = await aria.chat(
                    clinic, session_id, user_message, channel="web", db=db
                )
            except Exception as agent_err:
                err_type = type(agent_err).__name__
                logger.exception("Agent error [%s]: clinic=%s session=%s",
                                 err_type, clinic_slug, session_id)
                await websocket.send_json({"type": "typing", "active": False})
                await websocket.send_json({
                    "type": "error",
                    "content": (
                        f"I'm sorry, I ran into a technical issue. "
                        f"Please try again or call us at {clinic.phone}."
                    ),
                    "error_type": err_type,
                })
                continue

            await websocket.send_json({"type": "typing", "active": False})
            await websocket.send_json({
                "type": "message",
                "content": response_text,
                "session_id": session_id,
                "escalated": is_escalated,
            })

    except WebSocketDisconnect:
        logger.info("WS disconnected: clinic=%s session=%s", clinic_slug, session_id)
        aria.clear_session(clinic.id, session_id)


@router.post("/api/{clinic_slug}/chat", response_model=ChatResponse)
async def rest_chat(clinic_slug: str, body: ChatMessage, db: Session = Depends(get_db)):
    clinic = get_clinic(db, clinic_slug)
    if not clinic:
        return JSONResponse(status_code=404, content={"error": "Clinic not found."})

    block_msg = _access_blocked(clinic, db)
    if block_msg:
        return JSONResponse(status_code=403, content={"error": block_msg})

    session_id = body.session_id or str(uuid.uuid4())
    try:
        response_text, is_escalated = await aria.chat(
            clinic, session_id, body.message, channel="web", db=db
        )
        return ChatResponse(content=response_text, session_id=session_id, escalated=is_escalated)
    except Exception:
        logger.exception("REST chat error: clinic=%s", clinic_slug)
        return JSONResponse(status_code=500, content={"error": "Internal error. Please try again."})


@router.get("/api/{clinic_slug}/config")
async def clinic_config(clinic_slug: str, db: Session = Depends(get_db)):
    clinic = get_clinic(db, clinic_slug)
    if not clinic:
        return JSONResponse(status_code=404, content={"error": "Clinic not found."})
    plan = get_plan(clinic)
    return {
        "agent_name":   clinic.agent_name,
        "clinic_name":  clinic.name,
        "specialty":    clinic.specialty,
        "phone":        clinic.phone,
        "white_label":  plan["white_label"],
    }


@router.get("/api/{clinic_slug}/appointments")
async def get_appointments(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Return all appointments for a clinic. Requires clinic session token."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})
    appts = list_appointments(db, clinic.id)
    return [
        {
            "id":                   a.id,
            "confirmation_number":  a.confirmation_number,
            "patient_name":         a.patient_name,
            "patient_phone":        a.patient_phone,
            "patient_email":        a.patient_email,
            "patient_dob":          a.patient_dob,
            "appointment_type":     a.appointment_type,
            "appointment_datetime": a.appointment_datetime,
            "provider":             a.provider,
            "is_new_patient":       a.is_new_patient,
            "chief_complaint":      a.chief_complaint,
            "status":               a.status,
            "channel":              a.channel,
            "booked_at":            a.created_at.strftime("%Y-%m-%d %H:%M UTC"),
        }
        for a in appts
    ]


@router.get("/api/{clinic_slug}/plan")
async def clinic_plan(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Return plan details + usage for the clinic portal."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})
    from backend.db.crud import get_usage_this_month
    plan = get_plan(clinic)
    used = get_usage_this_month(db, clinic.id)
    limit = plan["conversations_limit"]
    return {
        "plan_key":              getattr(clinic, "plan", "professional") or "professional",
        "plan_name":             plan["name"],
        "price":                 plan["price"],
        "conversations_used":    used,
        "conversations_limit":   limit,
        "features": {
            "sms":               plan["sms"],
            "widget_embed":      plan["widget_embed"],
            "custom_agent_name": plan["custom_agent_name"],
            "white_label":       plan["white_label"],
            "max_locations":     plan["max_locations"],
            "support":           plan["support"],
        },
        "subscription_status":   clinic.subscription_status,
        "trial_ends_at":         clinic.trial_ends_at.strftime("%B %d, %Y") if clinic.trial_ends_at else None,
        "subscription_ends_at":  clinic.subscription_ends_at.strftime("%B %d, %Y") if clinic.subscription_ends_at else None,
    }


@router.get("/api/health")
async def health():
    return {"status": "ok", "service": "Tabor Synergy Agent"}


@router.get("/api/health/ai")
async def health_ai():
    """Test that the Anthropic API key is valid and the model responds."""
    try:
        from backend.agent.aria import _client
        from backend.config import settings
        resp = await _client.messages.create(
            model=settings.model,
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        return {"status": "ok", "model": resp.model, "reply": resp.content[0].text if resp.content else ""}
    except Exception as e:
        return {"status": "error", "error_type": type(e).__name__, "detail": str(e)[:300]}
