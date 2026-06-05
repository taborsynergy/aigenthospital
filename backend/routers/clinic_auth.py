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

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.limiter import limiter

from backend.db.database import get_db
from backend.db import crud

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
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    if not body.email and not body.slug:
        return JSONResponse(status_code=400, content={"error": "Provide email or slug to log in."})

    clinic = crud.get_clinic_by_email(db, body.email) if body.email else crud.get_clinic(db, body.slug)
    if not clinic:
        identifier = body.email or body.slug
        logger.warning("Login failed — no clinic found for: %s", identifier)
        return JSONResponse(status_code=401, content={"error": "No account found. Check your email or clinic ID."})
    if not clinic.customer_password_hash:
        logger.warning("Login failed — clinic %s has no password set", clinic.slug)
        return JSONResponse(status_code=401, content={"error": "No password set for this account. Contact admin@tabor.taborsynergy.com"})
    if not verify_password(body.password, clinic.customer_password_hash):
        logger.warning("Login failed — wrong password for clinic: %s", clinic.slug)
        return JSONResponse(status_code=401, content={"error": "Incorrect password. Please try again."})

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


@router.post("/logout")
def logout(x_clinic_token: str = Header(None), db: Session = Depends(get_db)):
    clinic = crud.get_clinic_by_token(db, x_clinic_token)
    if clinic:
        crud.set_session_token(db, clinic.id, "")
    return {"ok": True}
