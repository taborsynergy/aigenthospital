"""
Clinic onboarding checklist endpoints.
Tracks setup progress (Day 1-5): clinic info, branding, email, SMS, EMR, training.
"""
import json
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import OnboardingChecklist, Clinic, ClinicUser
from backend.auth import verify_access_token
from backend.email_service import send_email

router = APIRouter(prefix="/api/clinic/onboarding", tags=["clinic-onboarding"])


# ─── Pydantic Models ──────────────────────────────────────────────────────
class OnboardingStepResponse(BaseModel):
    name: str
    label: str
    description: str
    completed: bool


class OnboardingStatusResponse(BaseModel):
    clinic_slug: str
    progress_percent: int
    steps: dict[str, OnboardingStepResponse]
    portal_url: str
    go_live_ready: bool
    completed_at: Optional[datetime] = None


class UpdateStepRequest(BaseModel):
    step: str
    data: dict


class ValidateSMTPRequest(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    from_email: str


class ValidateTwilioRequest(BaseModel):
    account_sid: str
    auth_token: str
    phone_number: str


# ─── Endpoints ───────────────────────────────────────────────────────────
def get_clinic_and_user(clinic_slug: str, user_id: int, db: Session):
    """Verify user belongs to clinic"""
    clinic = db.query(Clinic).filter(Clinic.slug == clinic_slug).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    user = db.query(ClinicUser).filter(ClinicUser.id == user_id).first()
    if not user or user.clinic_id != clinic.id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    return clinic, user


@router.get("/{clinic_slug}/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    clinic_slug: str,
    user_id: int = Depends(verify_access_token),
    db: Session = Depends(get_db)
) -> OnboardingStatusResponse:
    """
    Get onboarding checklist status for a clinic.
    Shows which steps are completed and overall progress.
    """
    clinic, user = get_clinic_and_user(clinic_slug, user_id, db)

    # Get or create onboarding record
    checklist = db.query(OnboardingChecklist).filter(
        OnboardingChecklist.clinic_id == clinic.id
    ).first()

    if not checklist:
        checklist = OnboardingChecklist(clinic_id=clinic.id)
        db.add(checklist)
        db.commit()
        db.refresh(checklist)

    # Define steps
    steps = {
        "clinic_info": OnboardingStepResponse(
            name="clinic_info",
            label="Clinic Info",
            description="Clinic name, address, phone, specialty",
            completed=checklist.clinic_info_completed
        ),
        "branding": OnboardingStepResponse(
            name="branding",
            label="Branding",
            description="Logo, colors, custom text",
            completed=checklist.branding_completed
        ),
        "email_config": OnboardingStepResponse(
            name="email_config",
            label="Email Setup",
            description="SMTP for appointment confirmations",
            completed=checklist.email_config_completed
        ),
        "sms_config": OnboardingStepResponse(
            name="sms_config",
            label="SMS Setup",
            description="Twilio for appointment reminders",
            completed=checklist.sms_config_completed
        ),
        "emr_integration": OnboardingStepResponse(
            name="emr_integration",
            label="EMR Integration",
            description="Connect to patient records system",
            completed=checklist.emr_integration_completed
        ),
        "staff_training": OnboardingStepResponse(
            name="staff_training",
            label="Staff Training",
            description="Train team on admin dashboard",
            completed=checklist.staff_training_completed
        ),
    }

    # Calculate progress
    completed = sum(1 for s in steps.values() if s.completed)
    progress_percent = int((completed / len(steps)) * 100)
    go_live_ready = completed == len(steps)

    return OnboardingStatusResponse(
        clinic_slug=clinic.slug,
        progress_percent=progress_percent,
        steps=steps,
        portal_url=f"https://{clinic.slug}.aifrontdesk.com",
        go_live_ready=go_live_ready,
        completed_at=checklist.completed_at
    )


@router.post("/{clinic_slug}/steps/{step}")
async def update_onboarding_step(
    clinic_slug: str,
    step: str,
    req: UpdateStepRequest,
    user_id: int = Depends(verify_access_token),
    db: Session = Depends(get_db)
) -> dict:
    """
    Update a specific onboarding step.
    Saves data and marks step as completed.
    """
    clinic, user = get_clinic_and_user(clinic_slug, user_id, db)

    checklist = db.query(OnboardingChecklist).filter(
        OnboardingChecklist.clinic_id == clinic.id
    ).first()

    if not checklist:
        checklist = OnboardingChecklist(clinic_id=clinic.id)
        db.add(checklist)
        db.commit()
        db.refresh(checklist)

    # Update the appropriate step
    if step == "clinic_info":
        checklist.clinic_info_completed = True
        checklist.clinic_info_data = json.dumps(req.data)
        # Update clinic with provided info
        clinic.specialty = req.data.get("specialty", clinic.specialty)
        clinic.address = req.data.get("address", clinic.address)
        clinic.phone = req.data.get("phone", clinic.phone)
        clinic.city_state = req.data.get("city_state", clinic.city_state)

    elif step == "branding":
        checklist.branding_completed = True
        checklist.branding_data = json.dumps(req.data)
        # These would be stored in WidgetConfig in production

    elif step == "email_config":
        checklist.email_config_completed = True
        checklist.email_config_data = json.dumps(req.data)
        # In production, validate and store SMTP credentials securely

    elif step == "sms_config":
        checklist.sms_config_completed = True
        checklist.sms_config_data = json.dumps(req.data)
        # In production, validate Twilio credentials

    elif step == "emr_integration":
        checklist.emr_integration_completed = True
        checklist.emr_integration_data = json.dumps(req.data)
        # In production, would initialize EHRConfiguration record

    elif step == "staff_training":
        checklist.staff_training_completed = True
        checklist.staff_training_date = datetime.utcnow()

    else:
        raise HTTPException(status_code=400, detail=f"Unknown step: {step}")

    db.commit()

    return {
        "detail": f"Step '{step}' completed",
        "completed": getattr(checklist, f"{step}_completed")
    }


@router.post("/{clinic_slug}/validate-smtp")
async def validate_smtp(
    clinic_slug: str,
    req: ValidateSMTPRequest,
    user_id: int = Depends(verify_access_token),
    db: Session = Depends(get_db)
) -> dict:
    """
    Test SMTP credentials by sending a test email.
    """
    clinic, user = get_clinic_and_user(clinic_slug, user_id, db)

    try:
        # Test send email
        send_email(
            to=user.email,
            subject="Aria AI — SMTP Configuration Test",
            body="This is a test email to verify your SMTP configuration.\n\nIf you received this, your settings are correct!",
            smtp_host=req.smtp_host,
            smtp_port=req.smtp_port,
            smtp_user=req.smtp_user,
            smtp_pass=req.smtp_pass,
            from_email=req.from_email
        )

        # Mark as tested
        checklist = db.query(OnboardingChecklist).filter(
            OnboardingChecklist.clinic_id == clinic.id
        ).first()
        if checklist:
            checklist.email_config_tested = True
            db.commit()

        return {
            "success": True,
            "detail": "SMTP configuration verified. Test email sent to " + user.email
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"SMTP validation failed: {str(e)}"
        )


@router.post("/{clinic_slug}/validate-twilio")
async def validate_twilio(
    clinic_slug: str,
    req: ValidateTwilioRequest,
    user_id: int = Depends(verify_access_token),
    db: Session = Depends(get_db)
) -> dict:
    """
    Test Twilio credentials by sending a test SMS.
    """
    clinic, user = get_clinic_and_user(clinic_slug, user_id, db)

    try:
        from twilio.rest import Client

        # Test Twilio connection
        client = Client(req.account_sid, req.auth_token)
        message = client.messages.create(
            body="Aria AI: SMS configuration test. If you received this, your Twilio setup is correct!",
            from_=req.phone_number,
            to=user.clinic.phone  # Send to clinic's primary phone
        )

        # Mark as tested
        checklist = db.query(OnboardingChecklist).filter(
            OnboardingChecklist.clinic_id == clinic.id
        ).first()
        if checklist:
            checklist.sms_config_tested = True
            db.commit()

        return {
            "success": True,
            "detail": f"Twilio configuration verified. Test SMS sent.",
            "message_sid": message.sid
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Twilio validation failed: {str(e)}"
        )


@router.post("/{clinic_slug}/go-live")
async def mark_go_live(
    clinic_slug: str,
    user_id: int = Depends(verify_access_token),
    db: Session = Depends(get_db)
) -> dict:
    """
    Mark clinic as ready for go-live.
    All checklist items must be completed.
    """
    clinic, user = get_clinic_and_user(clinic_slug, user_id, db)

    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can launch")

    checklist = db.query(OnboardingChecklist).filter(
        OnboardingChecklist.clinic_id == clinic.id
    ).first()

    if not checklist:
        raise HTTPException(status_code=400, detail="Onboarding not started")

    # Verify all steps completed
    if not all([
        checklist.clinic_info_completed,
        checklist.branding_completed,
        checklist.email_config_completed,
        checklist.sms_config_completed,
        checklist.emr_integration_completed,
        checklist.staff_training_completed,
    ]):
        raise HTTPException(
            status_code=400,
            detail="Not all onboarding steps completed"
        )

    # Mark as go-live
    now = datetime.utcnow()
    checklist.go_live_date = now
    checklist.completed_at = now
    clinic.is_active = True
    clinic.activated_at = now

    db.commit()

    # Send congratulations email
    send_email(
        to=user.email,
        subject=f"🎉 {clinic.name} is Live on Aria AI!",
        body=f"""
        Hi {user.full_name},

        Congratulations! {clinic.name} is now live on Aria AI!

        Portal: https://{clinic.slug}.aifrontdesk.com
        Admin Dashboard: https://{clinic.slug}.aifrontdesk.com/admin

        Your patients can now book appointments 24/7.

        Next steps:
        1. Share the portal link with patients
        2. Add QR codes to your waiting room
        3. Monitor dashboard for first appointments

        Need support? Email support@aifrontdesk.com

        Welcome to the Aria AI community! 🚀
        —Aria AI Team
        """
    )

    return {
        "detail": "Clinic is now live!",
        "go_live_date": checklist.go_live_date,
        "portal_url": f"https://{clinic.slug}.aifrontdesk.com",
        "admin_url": f"https://{clinic.slug}.aifrontdesk.com/admin"
    }
