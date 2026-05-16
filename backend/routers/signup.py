"""
Public self-service endpoints: trial signup and White Label quote requests.
No admin password required for either.
"""
import logging
import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db import crud
from backend.services.email_svc import send_quote_email
from backend.routers.clinic_auth import hash_password

router = APIRouter()
logger = logging.getLogger(__name__)

PLAN_RATES = {
    "starter":      199.0,
    "professional": 299.0,
    "enterprise":   499.0,
}


class SignupRequest(BaseModel):
    practice_name: str
    contact_email: str
    password: str
    specialty: str
    phone: str = ""
    plan: str = "professional"


def _make_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")[:30]
    suffix = uuid.uuid4().hex[:5]
    return f"{base}-{suffix}"


@router.post("/api/signup")
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    plan = body.plan.lower() if body.plan.lower() in PLAN_RATES else "professional"
    rate = PLAN_RATES[plan]

    slug = _make_slug(body.practice_name)
    # Ensure uniqueness (extremely unlikely collision, but be safe)
    while crud.get_clinic(db, slug):
        slug = _make_slug(body.practice_name)

    trial_ends_at = datetime.utcnow() + timedelta(days=14)

    if len(body.password) < 6:
        return JSONResponse(status_code=422, content={"detail": "Password must be at least 6 characters."})

    clinic = crud.create_clinic(db, {
        "slug":                   slug,
        "name":                   body.practice_name,
        "specialty":              body.specialty,
        "agent_name":             "Aria",
        "email":                  body.contact_email,
        "phone":                  body.phone,
        "subscription_status":    "trial",
        "monthly_rate":           rate,
        "trial_ends_at":          trial_ends_at,
        "customer_password_hash": hash_password(body.password),
    })

    chat_url = f"{settings.base_url}/c/{slug}"
    logger.info("Trial signup: slug=%s plan=%s email=%s", slug, plan, body.contact_email)

    return {
        "slug":          slug,
        "chat_url":      chat_url,
        "plan":          plan,
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
def request_quote(body: QuoteRequest):
    data = body.model_dump()
    emailed = send_quote_email(data)
    logger.info("Quote request from %s <%s> emailed=%s", body.company, body.email, emailed)
    return {
        "ok": True,
        "emailed": emailed,
        "message": (
            "Thank you! We've received your request and will contact you within one business day."
        ),
    }
