"""
Customer portal auth for trial/subscribed clinics.
Endpoints: login, verify token, logout.
Password hashing: PBKDF2-HMAC-SHA256 (stdlib only, no extra deps).
"""
import base64
import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db import crud
from backend.limiter import limiter

router = APIRouter(prefix="/api/clinic-auth")
logger = logging.getLogger(__name__)

_ITERATIONS = 260_000


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = base64.b64encode(os.urandom(16)).decode()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"{salt}${base64.b64encode(h).decode()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, hashed = stored.split("$", 1)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return base64.b64encode(h).decode() == hashed


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = ""     # login by contact email
    slug: str = ""      # login by clinic slug (alternative)
    password: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login")
@limiter.limit("5/hour")   # 5 attempts per hour per IP — down from 5/minute
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    if not body.email and not body.slug:
        return JSONResponse(status_code=400, content={"error": "Provide email or clinic ID to log in."})

    clinic = (
        crud.get_clinic_by_email(db, body.email) if body.email
        else crud.get_clinic(db, body.slug)
    )
    if not clinic:
        identifier = body.email or body.slug
        logger.warning("Login failed — clinic not found: %s", identifier)
        # Same message for not-found and wrong-password to prevent enumeration
        return JSONResponse(status_code=401, content={"error": "Invalid credentials."})

    # Account lockout check
    if clinic.locked_until and datetime.now(timezone.utc).replace(tzinfo=None) < clinic.locked_until:
        remaining = int((clinic.locked_until - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() // 60) + 1
        return JSONResponse(status_code=429, content={
            "error": f"Account temporarily locked. Try again in {remaining} minute(s)."
        })

    if not clinic.customer_password_hash:
        return JSONResponse(status_code=401, content={
            "error": "No password set for this account. Contact admin@tabor.taborsynergy.com"
        })

    if not verify_password(body.password, clinic.customer_password_hash):
        attempts = crud.record_failed_login(db, clinic)
        remaining_before_lock = max(0, 10 - attempts)
        logger.warning("Login failed — wrong password: clinic=%s attempts=%d", clinic.slug, attempts)
        if clinic.locked_until:
            return JSONResponse(status_code=429, content={
                "error": "Too many failed attempts. Account locked for 30 minutes."
            })
        return JSONResponse(status_code=401, content={
            "error": f"Invalid credentials. {remaining_before_lock} attempt(s) remaining before lockout."
            if remaining_before_lock > 0 else "Invalid credentials."
        })

    # Successful login — reset lockout counter
    crud.reset_failed_logins(db, clinic)
    token = uuid.uuid4().hex
    crud.set_session_token(db, clinic.id, token)
    logger.info("Clinic login: slug=%s", clinic.slug)
    return {
        "token": token,
        "slug":  clinic.slug,
        "name":  clinic.name,
    }


@router.get("/verify")
def verify(x_clinic_token: str = Header(None), db: Session = Depends(get_db)):
    clinic = crud.get_clinic_by_token(db, x_clinic_token)
    if not clinic:
        return JSONResponse(status_code=401, content={"error": "Invalid or expired session."})
    return {
        "slug":       clinic.slug,
        "name":       clinic.name,
        "specialty":  clinic.specialty,
        "agent_name": clinic.agent_name,
        "status":     clinic.subscription_status,
    }


@router.post("/signup")
@limiter.limit("10/hour")
def signup(request: Request, body: dict, db: Session = Depends(get_db)):
    """Create a new clinic trial (14-day free trial on Starter plan)."""
    email = (body.get("email") or "").lower().strip()
    slug = (body.get("slug") or "").lower().strip()
    name = (body.get("name") or "").strip()
    specialty = (body.get("specialty") or "").strip()
    password = body.get("password") or ""

    # Validation
    if not email or "@" not in email:
        return JSONResponse(status_code=400, content={"error": "Valid email required"})
    if not slug or len(slug) < 3:
        return JSONResponse(status_code=400, content={"error": "Clinic ID must be at least 3 characters"})
    if not name or len(name) < 2:
        return JSONResponse(status_code=400, content={"error": "Clinic name required"})
    if not specialty:
        return JSONResponse(status_code=400, content={"error": "Specialty required"})
    if len(password) < 8:
        return JSONResponse(status_code=400, content={"error": "Password must be at least 8 characters"})

    # Check if email or slug already exists
    if crud.get_clinic_by_email(db, email):
        return JSONResponse(status_code=400, content={"error": "Email already registered"})
    if crud.get_clinic(db, slug):
        return JSONResponse(status_code=400, content={"error": "Clinic ID already taken"})

    # Hash password and create trial clinic
    password_hash = hash_password(password)
    clinic = crud.create_trial_clinic(db, email, slug, name, specialty, password_hash)

    if not clinic:
        return JSONResponse(status_code=400, content={"error": "Failed to create clinic"})

    # Login and return token
    token = uuid.uuid4().hex
    crud.set_session_token(db, clinic.id, token)
    logger.info("Trial signup: slug=%s, email=%s", clinic.slug, email)

    # Send Day 0 welcome email (async, non-blocking)
    try:
        from backend.services.email_svc import send_onboarding_day0
        send_onboarding_day0({
            "clinic_name": clinic.name,
            "clinic_email": clinic.email,
            "first_name": clinic.name.split()[0] if clinic.name else "there",
            "slug": clinic.slug,
            "plan": "starter",
            "trial_ends_at": clinic.trial_ends_at.strftime("%B %d, %Y") if clinic.trial_ends_at else "soon",
            "portal_url": f"https://aifrontdesk.taborsynergy.com/c/{clinic.slug}",
        })
        clinic.onboarding_emails_sent = 0  # Mark Day 0 as sent by APScheduler
    except Exception as e:
        logger.error(f"Failed to send Day 0 onboarding email to {clinic.email}: {e}")

    return {
        "token": token,
        "slug": clinic.slug,
        "name": clinic.name,
        "trial_ends_at": clinic.trial_ends_at.isoformat() if clinic.trial_ends_at else None,
        "subscription_status": "trial",
    }


@router.post("/logout")
def logout(x_clinic_token: str = Header(None), db: Session = Depends(get_db)):
    clinic = crud.get_clinic_by_token(db, x_clinic_token)
    if clinic:
        crud.set_session_token(db, clinic.id, "")
    return {"ok": True}
