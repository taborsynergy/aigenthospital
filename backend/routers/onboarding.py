"""Dedicated onboarding router — Pro+ feature for clinic setup assistance."""
import uuid
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.crud import (
    get_clinic_by_token,
    get_onboarding_session,
    get_clinic_onboarding_session,
    create_onboarding_session,
    update_onboarding_session,
    mark_onboarding_completed,
    cancel_onboarding_session,
)
from backend.plans import can_use_dedicated_onboarding

router = APIRouter(prefix="/api", tags=["onboarding"])


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/{clinic_slug}/onboarding/current")
def get_current_onboarding(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get current onboarding session for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_dedicated_onboarding(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Dedicated onboarding not available on your plan. Upgrade to Enterprise."
        })

    session = get_clinic_onboarding_session(db, clinic.id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "No onboarding session found"})

    return {
        "id": session.id,
        "status": session.status,
        "contact_name": session.contact_name,
        "contact_email": session.contact_email,
        "contact_phone": session.contact_phone,
        "meeting_link": session.meeting_link,
        "meeting_platform": session.meeting_platform,
        "duration_minutes": session.duration_minutes,
        "notes": session.notes,
        "topics_covered": session.topics_covered,
        "scheduled_at": session.scheduled_at.isoformat() if session.scheduled_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "requested_at": session.requested_at.isoformat() if session.requested_at else None,
    }


@router.post("/{clinic_slug}/onboarding/request")
def request_onboarding(
    clinic_slug: str,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Request a dedicated onboarding session."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_dedicated_onboarding(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Dedicated onboarding not available on your plan. Upgrade to Enterprise."
        })

    # Validate required fields
    if not data.get("contact_name") or not data.get("contact_name").strip():
        return JSONResponse(status_code=400, content={"error": "contact_name required"})
    if not data.get("contact_email") or "@" not in data.get("contact_email", ""):
        return JSONResponse(status_code=400, content={"error": "valid contact_email required"})

    # Create onboarding session
    session = create_onboarding_session(db, clinic.id, data)
    if not session:
        return JSONResponse(status_code=400, content={"error": "Failed to create onboarding session"})

    return {
        "id": session.id,
        "status": session.status,
        "contact_name": session.contact_name,
        "contact_email": session.contact_email,
        "requested_at": session.requested_at.isoformat() if session.requested_at else None,
    }


@router.patch("/{clinic_slug}/onboarding/{session_id}")
def update_onboarding(
    clinic_slug: str,
    session_id: int,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update onboarding session (admin only)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_dedicated_onboarding(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Dedicated onboarding not available on your plan."
        })

    session = get_onboarding_session(db, session_id, clinic.id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "Onboarding session not found"})

    updated = update_onboarding_session(db, session_id, clinic.id, data)
    if not updated:
        return JSONResponse(status_code=404, content={"error": "Onboarding session not found"})

    return {
        "id": updated.id,
        "status": updated.status,
        "scheduled_at": updated.scheduled_at.isoformat() if updated.scheduled_at else None,
        "meeting_link": updated.meeting_link,
        "meeting_platform": updated.meeting_platform,
        "notes": updated.notes,
        "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
    }


@router.post("/{clinic_slug}/onboarding/{session_id}/complete")
def complete_onboarding(
    clinic_slug: str,
    session_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Mark onboarding session as completed."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_dedicated_onboarding(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Dedicated onboarding not available on your plan."
        })

    session = mark_onboarding_completed(db, session_id, clinic.id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "Onboarding session not found"})

    return {
        "status": session.status,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


@router.post("/{clinic_slug}/onboarding/{session_id}/cancel")
def cancel_onboarding(
    clinic_slug: str,
    session_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Cancel an onboarding session."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_dedicated_onboarding(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Dedicated onboarding not available on your plan."
        })

    session = cancel_onboarding_session(db, session_id, clinic.id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "Onboarding session not found"})

    return {
        "status": session.status,
    }


@router.post("/{clinic_slug}/onboarding/{session_id}/schedule")
def schedule_onboarding(
    clinic_slug: str,
    session_id: int,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Schedule an onboarding session (set date/time and meeting link)."""
    from datetime import datetime as dt

    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_dedicated_onboarding(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Dedicated onboarding not available on your plan."
        })

    session = get_onboarding_session(db, session_id, clinic.id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "Onboarding session not found"})

    # Validate scheduling data
    if not data.get("scheduled_at"):
        return JSONResponse(status_code=400, content={"error": "scheduled_at required"})

    # Parse ISO format date string
    try:
        scheduled_str = data.get("scheduled_at", "")
        # Remove Z suffix if present and parse
        if scheduled_str.endswith('Z'):
            scheduled_str = scheduled_str[:-1] + "+00:00"
        scheduled_dt = dt.fromisoformat(scheduled_str.replace('Z', '+00:00'))
        data["scheduled_at"] = scheduled_dt
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid scheduled_at format"})

    # Generate Zoom meeting link if not provided
    if not data.get("meeting_link"):
        meeting_id = str(uuid.uuid4())[:8].upper()
        data["meeting_link"] = f"https://zoom.us/j/{meeting_id}"

    # Update session with scheduling info
    data["status"] = "scheduled"
    updated = update_onboarding_session(db, session_id, clinic.id, data)

    return {
        "id": updated.id,
        "status": updated.status,
        "scheduled_at": updated.scheduled_at.isoformat() if updated.scheduled_at else None,
        "meeting_link": updated.meeting_link,
        "meeting_platform": updated.meeting_platform,
    }
