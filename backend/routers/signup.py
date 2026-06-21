"""
Public self-service endpoints: trial signup and White Label quote requests.
No admin password required for either.
"""
import logging
import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db import crud
from backend.plans import PLAN_RATES, PLANS
from backend.services.email_svc import send_demo_request_email, send_quote_email, send_trial_signup_email
from backend.routers.clinic_auth import hash_password

router = APIRouter()
logger = logging.getLogger(__name__)


class SignupRequest(BaseModel):
    practice_name: str
    contact_email: EmailStr
    password: str = ""   # default "" so FastAPI never returns a 422 array; we validate below
    specialty: str
    phone: str = ""
    plan: str = "professional"


def _make_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")[:30]
    suffix = uuid.uuid4().hex[:5]
    return f"{base}-{suffix}"


@router.post("/api/signup")
def signup(body: SignupRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not body.practice_name.strip():
        return JSONResponse(status_code=400, content={"error": "Practice name is required."})
    if not body.specialty.strip():
        return JSONResponse(status_code=400, content={"error": "Specialty is required."})
    if len(body.password) < 6:
        return JSONResponse(status_code=400, content={"error": "Password must be at least 6 characters."})

    plan_key = body.plan.lower()
    if plan_key not in PLAN_RATES:
        return JSONResponse(status_code=400, content={"error": f"Invalid plan '{body.plan}'. Valid plans: {', '.join(PLAN_RATES)}."})
    rate = PLAN_RATES[plan_key]

    slug = _make_slug(body.practice_name)
    while crud.get_clinic(db, slug):
        slug = _make_slug(body.practice_name)

    trial_ends_at = datetime.utcnow() + timedelta(days=14)

    clinic = crud.create_clinic(db, {
        "slug":                   slug,
        "name":                   body.practice_name,
        "specialty":              body.specialty,
        "agent_name":             "Aria",
        "email":                  str(body.contact_email),
        "phone":                  body.phone,
        "subscription_status":    "trial",
        "plan":                   plan_key,
        "monthly_rate":           rate,
        "trial_ends_at":          trial_ends_at,
        "customer_password_hash": hash_password(body.password),
        "is_active":              True,
    })

    # Generate session token so the landing page can auto-login the user on redirect
    token = uuid.uuid4().hex
    crud.set_session_token(db, clinic.id, token)

    chat_url = f"{settings.base_url}/c/{slug}"
    portal_url = f"{chat_url}?token={token}"
    logger.info("Trial signup: slug=%s plan=%s email=%s", slug, plan_key, body.contact_email)

    background_tasks.add_task(send_trial_signup_email, {
        "practice_name": body.practice_name,
        "specialty":     body.specialty,
        "contact_email": body.contact_email,
        "phone":         body.phone,
        "plan":          plan_key,
        "monthly_rate":  rate,
        "trial_ends_at": trial_ends_at.strftime("%B %d, %Y"),
        "slug":          slug,
        "chat_url":      chat_url,
    })

    return {
        "slug":          slug,
        "chat_url":      chat_url,
        "portal_url":    portal_url,
        "token":         token,
        "plan":          plan_key,
        "monthly_rate":  rate,
        "trial_ends_at": trial_ends_at.strftime("%B %d, %Y"),
    }


# ── White Label quote request ─────────────────────────────────────────────────

class QuoteRequest(BaseModel):
    full_name: str
    email: str
    company: str
    phone: str = ""
    locations: str = ""
    pms: str = ""
    message: str = ""


@router.post("/api/quote")
def request_quote(body: QuoteRequest, background_tasks: BackgroundTasks):
    data = body.model_dump()
    background_tasks.add_task(send_quote_email, data)
    logger.info("Quote request from %s <%s>", body.company, body.email)
    return {
        "ok": True,
        "emailed": True,
        "message": (
            "Thank you! We've received your request and will contact you within one business day."
        ),
    }


# ── Demo request ─────────────────────────────────────────────────────────────

class DemoRequest(BaseModel):
    full_name: str
    email: EmailStr
    phone: str = ""
    practice_name: str
    specialty: str
    num_providers: str = ""
    preferred_slot: str
    message: str = ""


@router.post("/api/demo-request")
def request_demo(body: DemoRequest, background_tasks: BackgroundTasks):
    if not body.full_name.strip():
        return JSONResponse(status_code=400, content={"error": "Full name is required."})
    if not body.practice_name.strip():
        return JSONResponse(status_code=400, content={"error": "Practice name is required."})
    if not body.specialty.strip():
        return JSONResponse(status_code=400, content={"error": "Specialty is required."})
    if not body.preferred_slot.strip():
        return JSONResponse(status_code=400, content={"error": "Preferred demo time is required."})

    data = body.model_dump()
    background_tasks.add_task(send_demo_request_email, data)
    logger.info("Demo request from %s <%s> practice=%s", body.full_name, body.email, body.practice_name)
    return {
        "ok": True,
        "message": "Thank you! We'll confirm your demo slot within 24 hours.",
    }


@router.get("/api/plans")
def get_all_plans():
    """Get all available plans with features and coming_soon items."""
    return {
        "plans": {
            key: {
                "name": plan["name"],
                "price": plan["price"],
                "color": plan["color"],
                "max_locations": plan["max_locations"],
                "conversations_limit": plan["conversations_limit"],
                "features": {
                    "reminders": plan.get("reminders", False),
                    "widget_embed": plan["widget_embed"],
                    "custom_agent_name": plan["custom_agent_name"],
                    "white_label": plan["white_label"],
                },
                "support": plan["support"],
                "coming_soon": plan.get("coming_soon", []),
            }
            for key, plan in PLANS.items()
        }
    }
