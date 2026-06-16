"""
Clinic user management endpoints.
Handles admin/staff user creation, authentication, and password reset.
"""
from datetime import datetime, timedelta
from typing import Optional
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import ClinicUser, Clinic
from backend.config import settings
from backend.auth import create_access_token, verify_access_token
from backend.routers.clinic_auth import hash_password, verify_password
from backend.routers.admin import require_admin
from backend.services.email_svc import send_email
from backend.db.crud import write_audit_log
from backend.limiter import limiter

router = APIRouter(prefix="/api/clinic/users", tags=["clinic-users"])

# Roles a clinic user may hold. Anything else is rejected at creation time.
ALLOWED_ROLES = {"admin", "manager", "staff", "billing"}
# Minimum password length for clinic users (matches a sane production baseline).
MIN_PASSWORD_LEN = 8


# ─── Pydantic Models ──────────────────────────────────────────────────────
class CreateClinicUserRequest(BaseModel):
    clinic_slug: str
    email: EmailStr
    full_name: str
    password: str
    role: str = "staff"  # admin, manager, staff, billing


class ClinicUserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    clinic_slug: str
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: ClinicUserResponse
    clinic_name: str
    clinic_slug: str


class ForgotPasswordRequest(BaseModel):
    clinic_slug: str
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# hash_password / verify_password are imported from clinic_auth (stdlib PBKDF2)


# ─── Endpoints ────────────────────────────────────────────────────────────
@router.post("/create", response_model=dict, dependencies=[Depends(require_admin)])
async def create_clinic_user(
    req: CreateClinicUserRequest,
    request: Request,
    db: Session = Depends(get_db)
) -> dict:
    """
    Create a new clinic user (admin/staff).
    Called during Day 1 kickoff to create the admin account.

    SECURITY: protected by the platform admin password (X-Admin-Password header)
    via require_admin. Without this, anyone could mint a clinic-admin account for
    any clinic. Self-service staff invites can be layered on later behind a
    clinic-admin JWT, but account bootstrap stays platform-admin-only.
    """
    # Validate role against the allowlist (never trust client-supplied role)
    if req.role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(sorted(ALLOWED_ROLES))}",
        )

    # Enforce a minimum password strength
    if len(req.password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters",
        )

    # Verify clinic exists
    clinic = db.query(Clinic).filter(Clinic.slug == req.clinic_slug).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    # Check if user already exists
    existing = db.query(ClinicUser).filter(ClinicUser.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Hash password
    password_hash = hash_password(req.password)

    # Create user
    user = ClinicUser(
        clinic_id=clinic.id,
        email=req.email,
        password_hash=password_hash,
        full_name=req.full_name,
        role=req.role,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Audit: who got a clinic account, with what role
    write_audit_log(
        db,
        actor="admin",
        action="clinic_user.create",
        target=f"{clinic.slug}:{user.email}",
        detail=json.dumps({"role": user.role, "user_id": user.id}),
        ip=(request.client.host if request.client else ""),
    )

    # Send welcome email
    send_email(
        to=req.email,
        subject=f"Welcome to Aria AI — {clinic.name}",
        body=f"""
        Hi {req.full_name},

        Your admin account has been created for {clinic.name}.

        Portal: https://{clinic.slug}.aifrontdesk.com/admin
        Email: {req.email}

        Next steps:
        1. Log in with your password
        2. Complete the setup checklist
        3. Invite staff members
        4. Go live!

        Need help? Email support@aifrontdesk.com

        —Aria AI Team
        """
    )

    return {
        "success": True,
        "user_id": user.id,
        "email": user.email,
        "portal_url": f"https://{clinic.slug}.aifrontdesk.com/admin",
        "message": f"User {req.email} created successfully"
    }


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/hour")   # brute-force protection per IP (matches app-wide pattern)
async def login(
    request: Request,
    req: LoginRequest,
    db: Session = Depends(get_db)
) -> LoginResponse:
    """
    Authenticate clinic user and return JWT token.
    """
    # Get clinic
    clinic = db.query(Clinic).filter(Clinic.slug == req.clinic_slug).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    # Get user
    user = db.query(ClinicUser).filter(
        ClinicUser.clinic_id == clinic.id,
        ClinicUser.email == req.email
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Check if account is currently locked
    if user.locked_until and user.locked_until > datetime.utcnow():
        raise HTTPException(
            status_code=429,
            detail="Account locked due to too many failed attempts. Try again later."
        )

    # Lock window has elapsed — reset the counter so a stale count can't re-lock instantly
    if user.locked_until and user.locked_until <= datetime.utcnow():
        user.failed_login_attempts = 0
        user.locked_until = None

    # Verify password
    if not verify_password(req.password, user.password_hash):
        user.failed_login_attempts += 1

        # Lock account after 5 failed attempts
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=30)

        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Reset failed attempts on successful login
    user.failed_login_attempts = 0
    user.last_login_at = datetime.utcnow()
    user.locked_until = None
    db.commit()

    # Create JWT token
    token = create_access_token(
        data={
            "user_id": user.id,
            "clinic_id": clinic.id,
            "clinic_slug": clinic.slug,
            "role": user.role
        }
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=ClinicUserResponse.model_validate(user),
        clinic_name=clinic.name,
        clinic_slug=clinic.slug
    )


@router.post("/forgot-password")
@limiter.limit("5/hour")   # prevent reset-email flooding / enumeration probing
async def forgot_password(
    request: Request,
    req: ForgotPasswordRequest,
    db: Session = Depends(get_db)
) -> dict:
    """
    Request password reset link.
    Don't reveal if email exists (security).
    """
    clinic = db.query(Clinic).filter(Clinic.slug == req.clinic_slug).first()
    if not clinic:
        return {"detail": "If email exists, reset link sent"}

    user = db.query(ClinicUser).filter(
        ClinicUser.clinic_id == clinic.id,
        ClinicUser.email == req.email
    ).first()

    if user:
        # Generate reset token
        reset_token = secrets.token_urlsafe(32)
        user.reset_token = reset_token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        db.commit()

        # Send reset email
        reset_url = f"https://{clinic.slug}.aifrontdesk.com/reset-password?token={reset_token}"
        send_email(
            to=user.email,
            subject="Reset Your Aria AI Password",
            body=f"""
            Hi {user.full_name},

            Click the link below to reset your password (valid for 1 hour):
            {reset_url}

            If you didn't request this, ignore this email.

            —Aria AI Team
            """
        )

    return {"detail": "If email exists, reset link sent"}


@router.post("/reset-password")
@limiter.limit("5/hour")   # prevent brute-forcing reset tokens
async def reset_password(
    request: Request,
    req: ResetPasswordRequest,
    db: Session = Depends(get_db)
) -> dict:
    """
    Reset password using reset token.
    """
    # Enforce password strength on reset too
    if len(req.new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters",
        )

    # Reject empty/blank tokens outright (avoid matching users with empty reset_token="")
    if not req.token or not req.token.strip():
        raise HTTPException(status_code=400, detail="Invalid reset token")

    user = db.query(ClinicUser).filter(
        ClinicUser.reset_token == req.token
    ).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    # Check token expiration
    if user.reset_token_expires is None or user.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset token expired")

    # Hash and update password
    user.password_hash = hash_password(req.new_password)
    user.reset_token = ""
    user.reset_token_expires = None
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    return {"detail": "Password reset successfully"}


@router.get("/profile", response_model=ClinicUserResponse)
async def get_profile(
    user_id: int = Depends(verify_access_token),
    db: Session = Depends(get_db)
) -> ClinicUserResponse:
    """
    Get current user profile.
    """
    user = db.query(ClinicUser).filter(ClinicUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return ClinicUserResponse.model_validate(user)


@router.get("/clinic/{clinic_slug}", response_model=list[ClinicUserResponse])
async def list_clinic_users(
    clinic_slug: str,
    user_id: int = Depends(verify_access_token),
    db: Session = Depends(get_db)
) -> list[ClinicUserResponse]:
    """
    List all users for a clinic (admin only).
    """
    # Verify user is admin of this clinic
    user = db.query(ClinicUser).filter(ClinicUser.id == user_id).first()
    clinic = db.query(Clinic).filter(Clinic.slug == clinic_slug).first()

    if not clinic or not user or user.clinic_id != clinic.id or user.role != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized")

    users = db.query(ClinicUser).filter(ClinicUser.clinic_id == clinic.id).all()
    return [ClinicUserResponse.model_validate(u) for u in users]


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user_id: int = Depends(verify_access_token),
    db: Session = Depends(get_db)
) -> dict:
    """
    Delete a clinic user (admin only).
    """
    current_user = db.query(ClinicUser).filter(ClinicUser.id == current_user_id).first()
    user_to_delete = db.query(ClinicUser).filter(ClinicUser.id == user_id).first()

    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")

    # Only admins can delete users
    if current_user.role != "admin" or current_user.clinic_id != user_to_delete.clinic_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    db.delete(user_to_delete)
    db.commit()

    return {"detail": f"User {user_to_delete.email} deleted"}
