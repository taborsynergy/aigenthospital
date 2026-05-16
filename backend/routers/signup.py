"""
Public self-service signup endpoint.
Anyone can create a trial clinic — no admin password required.
"""
import logging
import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db import crud

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

    clinic = crud.create_clinic(db, {
        "slug":                slug,
        "name":                body.practice_name,
        "specialty":           body.specialty,
        "agent_name":          "Aria",
        "email":               body.contact_email,
        "phone":               body.phone,
        "subscription_status": "trial",
        "monthly_rate":        rate,
        "trial_ends_at":       trial_ends_at,
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
