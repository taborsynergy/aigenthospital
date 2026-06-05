import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.agent import aria
from backend.db.database import get_db
from backend.schemas import ClinicProfileUpdate
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
                response_text = ""
                is_escalated = False
                async for event_type, data in aria.chat_stream(
                    clinic, session_id, user_message, channel="web", db=db
                ):
                    if event_type == "chunk":
                        response_text += data
                        await websocket.send_json({"type": "chunk", "text": data})
                    elif event_type == "done":
                        response_text, is_escalated = data
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

    if not body.message or not body.message.strip():
        return JSONResponse(status_code=400, content={"error": "Message cannot be empty."})

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


@router.get("/api/{clinic_slug}/analytics")
async def get_analytics(
    clinic_slug: str,
    report: str = "full",   # full | today | weekly | monthly | no_shows | providers | conversations | recall
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """
    Real-time analytics dashboard for the clinic portal.
    report=full returns all sections in one call (used by the Analytics tab).
    Individual report types can be requested for lighter payloads.
    """
    from backend.services import analytics_svc

    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    try:
        if report == "full":
            return analytics_svc.get_full_dashboard(db, clinic.id, clinic)
        elif report == "today":
            return analytics_svc.get_today_appointments(db, clinic.id)
        elif report == "weekly":
            return analytics_svc.get_weekly_summary(db, clinic.id)
        elif report == "monthly":
            return analytics_svc.get_monthly_summary(db, clinic.id)
        elif report == "no_shows":
            return analytics_svc.get_no_shows(db, clinic.id)
        elif report == "providers":
            return analytics_svc.get_provider_breakdown(db, clinic.id)
        elif report == "conversations":
            return analytics_svc.get_conversation_stats(db, clinic.id, clinic)
        elif report == "recall":
            return analytics_svc.get_recall_performance(db, clinic.id)
        else:
            return JSONResponse(status_code=400, content={"error": f"Unknown report type: {report}"})
    except Exception:
        logger.exception("Analytics error: clinic=%s report=%s", clinic_slug, report)
        return JSONResponse(status_code=500, content={"error": "Failed to compute analytics."})


# ── Clinic profile (self-edit by clinic staff) ────────────────────────────────

@router.get("/api/{clinic_slug}/profile")
async def get_profile(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Load current clinic profile for editing."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    return {
        "name":                clinic.name or "",
        "specialty":           clinic.specialty or "",
        "address":             clinic.address or "",
        "city_state":          clinic.city_state or "",
        "phone":               clinic.phone or "",
        "website":             clinic.website or "",
        "office_hours":        clinic.office_hours or "",
        "providers":           clinic.providers or "",
        "services_offered":    clinic.services_offered or "",
        "insurance_accepted":  clinic.insurance_accepted or "",
        "cancellation_policy": clinic.cancellation_policy or "",
        "after_hours_protocol": clinic.after_hours_protocol or "",
        "timezone":            clinic.timezone or "US/Eastern",
        "hipaa_verify_method": clinic.hipaa_verify_method or "",
        "escalation_contact":  clinic.escalation_contact or "",
        "pms_system":          clinic.pms_system or "",
    }


@router.patch("/api/{clinic_slug}/profile")
async def update_profile(
    clinic_slug: str,
    body: ClinicProfileUpdate,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Clinic staff can self-edit their profile."""
    from backend.db.crud import write_audit_log, update_clinic
    import json

    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    # Build updates from non-None fields
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return JSONResponse(status_code=400, content={"error": "No fields to update."})

    # Record before state for audit
    before = {k: getattr(clinic, k, None) for k in updates.keys()}

    # Apply updates
    updated = update_clinic(db, clinic_slug, updates)
    if not updated:
        return JSONResponse(status_code=404, content={"error": "Clinic not found."})

    # Audit log: what changed
    after = {k: getattr(updated, k, None) for k in updates.keys()}
    diff = {k: {"before": before.get(k), "after": after.get(k)} for k in updates.keys()}
    write_audit_log(
        db, f"clinic:{clinic_slug}", "clinic.profile_updated",
        target=clinic_slug, detail=json.dumps(diff),
    )
    logger.info("Clinic profile updated: slug=%s fields=%s", clinic_slug, list(updates.keys()))

    return {"ok": True, "updated_fields": list(updates.keys())}


class _StatusBody(BaseModel):
    status: str   # confirmed | no_show | completed | cancelled


_ALLOWED_STATUSES = {"confirmed", "no_show", "completed", "cancelled", "scheduled", "rescheduled"}


@router.patch("/api/{clinic_slug}/appointments/{confirmation_number}")
async def update_appointment_status(
    clinic_slug: str,
    confirmation_number: str,
    body: _StatusBody,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Clinic staff can update appointment status: confirmed / no_show / completed / cancelled."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    new_status = body.status.lower()
    if new_status not in _ALLOWED_STATUSES:
        return JSONResponse(status_code=400, content={
            "error": f"Invalid status. Allowed: {', '.join(sorted(_ALLOWED_STATUSES))}"
        })

    from backend.db.crud import update_appointment
    appt = update_appointment(db, confirmation_number, {"status": new_status})
    if not appt or appt.clinic_id != clinic.id:
        return JSONResponse(status_code=404, content={"error": "Appointment not found."})

    return {"ok": True, "confirmation_number": confirmation_number, "status": new_status}


class _UpgradeBody(BaseModel):
    plan: str


@router.post("/api/{clinic_slug}/upgrade-request")
async def upgrade_request(
    clinic_slug: str,
    body: _UpgradeBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """
    Clinic requests a plan upgrade — returns PayPal link and emails admin.
    When STRIPE_STARTER/PROFESSIONAL/ENTERPRISE_PRICE_ID env vars are set in future,
    a stripe checkout_url will also be returned automatically.
    """
    from backend.config import settings as cfg
    from backend.services.email_svc import send_upgrade_request_email

    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    _PRICES = {"starter": 297, "professional": 597, "enterprise": 997}
    new_plan    = (body.plan or "").lower()
    current_key = (getattr(clinic, "plan", None) or "professional").lower()

    if new_plan not in _PRICES:
        return JSONResponse(status_code=400, content={"error": "Invalid plan."})
    if _PRICES.get(new_plan, 0) <= _PRICES.get(current_key, 0):
        return JSONResponse(status_code=400, content={"error": "Select a higher plan to upgrade."})

    new_price  = _PRICES[new_plan]
    paypal_url = cfg.paypal_me_url.rstrip("/") + f"/{new_price}"

    background_tasks.add_task(send_upgrade_request_email, {
        "clinic_name":  clinic.name,
        "clinic_email": clinic.email,
        "clinic_slug":  clinic.slug,
        "current_plan": current_key,
        "new_plan":     new_plan,
        "new_price":    new_price,
        "paypal_url":   paypal_url,
    })

    return {"ok": True, "paypal_url": paypal_url, "new_plan": new_plan, "new_price": new_price}


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


@router.get("/api/{clinic_slug}/billing-portal")
async def billing_portal(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """
    Return a Stripe Customer Portal URL so the clinic can manage their own billing:
    update payment method, download invoices, cancel subscription.
    Requires an active Stripe customer ID.
    """
    from backend.config import settings as cfg
    from backend.services.stripe_svc import create_customer_portal_session, stripe_enabled

    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not stripe_enabled():
        return JSONResponse(status_code=400, content={"error": "Stripe billing not configured."})

    if not clinic.stripe_customer_id:
        return JSONResponse(status_code=400, content={
            "error": "No Stripe account linked. Complete a Stripe checkout first."
        })

    result = create_customer_portal_session(
        stripe_customer_id=clinic.stripe_customer_id,
        return_url=f"{cfg.base_url}/c/{clinic_slug}",
    )
    if result.get("error"):
        return JSONResponse(status_code=500, content={"error": result["error"]})

    return {"portal_url": result["url"]}


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
