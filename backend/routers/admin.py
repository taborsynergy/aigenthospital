"""
Admin API — protected by X-Admin-Password header.
Provides CRUD for clinics, usage stats, and billing actions.
"""
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db import crud
from backend.agent.aria import invalidate_prompt

router = APIRouter(prefix="/admin/api")
logger = logging.getLogger(__name__)


# ── Auth ─────────────────────────────────────────────────────────────────────

def require_admin(x_admin_password: Optional[str] = Header(None)):
    if x_admin_password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid admin password")



# ── Schemas ───────────────────────────────────────────────────────────────────

class ClinicIn(BaseModel):
    slug: str
    name: str
    specialty: str
    agent_name: str = "Aria"
    city_state: str = ""
    timezone: str = "Central Time (CT)"
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    office_hours: str = "Mon–Fri 8am–5pm"
    after_hours_protocol: str = "For emergencies call 911."
    providers: str = ""
    services_offered: str = ""
    insurance_accepted: str = ""
    pms_system: str = "Athenahealth"
    cancellation_policy: str = "24-hour notice required to avoid a $50 fee."
    escalation_contact: str = ""
    hipaa_verify_method: str = "Full name + date of birth + last 4 digits of SSN"
    twilio_phone: str = ""
    monthly_rate: float = 299.0
    initial_password: Optional[str] = None   # optional portal login password set at creation time


class ClinicPatch(BaseModel):
    name: Optional[str] = None
    specialty: Optional[str] = None
    agent_name: Optional[str] = None
    city_state: Optional[str] = None
    timezone: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    office_hours: Optional[str] = None
    after_hours_protocol: Optional[str] = None
    providers: Optional[str] = None
    services_offered: Optional[str] = None
    insurance_accepted: Optional[str] = None
    pms_system: Optional[str] = None
    cancellation_policy: Optional[str] = None
    escalation_contact: Optional[str] = None
    hipaa_verify_method: Optional[str] = None
    twilio_phone: Optional[str] = None
    monthly_rate: Optional[float] = None
    subscription_status: Optional[Literal["trial", "active", "past_due", "cancelled"]] = None


class SmsRequest(BaseModel):
    to: str
    message: str


# ── Clinic CRUD ───────────────────────────────────────────────────────────────

@router.get("/clinics", dependencies=[Depends(require_admin)])
def list_clinics(db: Session = Depends(get_db)):
    clinics = crud.list_clinics(db)
    return [_serialize(c) for c in clinics]


@router.post("/clinics", dependencies=[Depends(require_admin)])
def create_clinic(body: ClinicIn, db: Session = Depends(get_db)):
    if crud.get_clinic(db, body.slug):
        raise HTTPException(400, f"Slug '{body.slug}' already exists.")
    data = body.model_dump(exclude={"initial_password"})
    if body.initial_password:
        from backend.routers.clinic_auth import hash_password
        if len(body.initial_password) < 6:
            raise HTTPException(400, "initial_password must be at least 6 characters.")
        data["customer_password_hash"] = hash_password(body.initial_password)
    clinic = crud.create_clinic(db, data)
    return _serialize(clinic)


@router.get("/clinics/{slug}", dependencies=[Depends(require_admin)])
def get_clinic(slug: str, db: Session = Depends(get_db)):
    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    return _serialize(clinic)


@router.patch("/clinics/{slug}", dependencies=[Depends(require_admin)])
def update_clinic(slug: str, body: ClinicPatch, db: Session = Depends(get_db)):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    clinic = crud.update_clinic(db, slug, data)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    invalidate_prompt(clinic.id)
    return _serialize(clinic)


@router.delete("/clinics/{slug}", dependencies=[Depends(require_admin)])
def deactivate_clinic(slug: str, db: Session = Depends(get_db)):
    ok = crud.deactivate_clinic(db, slug)
    if not ok:
        raise HTTPException(404, "Clinic not found.")
    return {"deleted": slug}


@router.post("/clinics/{slug}/activate", dependencies=[Depends(require_admin)])
def activate_subscription(slug: str, db: Session = Depends(get_db)):
    """Manually activate a 30-day subscription after payment is confirmed."""
    clinic = crud.activate_subscription(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    return _serialize(clinic)


class NotesRequest(BaseModel):
    notes: str


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.post("/clinics/{slug}/reset-password", dependencies=[Depends(require_admin)])
def reset_clinic_password(slug: str, body: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset a clinic's portal login password."""
    from backend.routers.clinic_auth import hash_password
    if len(body.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    clinic = crud.update_clinic(db, slug, {"customer_password_hash": hash_password(body.new_password)})
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    logger.info("Password reset by admin for clinic: %s", slug)
    return {"ok": True, "slug": slug}


@router.patch("/clinics/{slug}/notes", dependencies=[Depends(require_admin)])
def update_notes(slug: str, body: NotesRequest, db: Session = Depends(get_db)):
    """Save internal CRM notes for a clinic."""
    clinic = crud.update_notes(db, slug, body.notes)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    return _serialize(clinic)


# ── Usage ─────────────────────────────────────────────────────────────────────

@router.get("/clinics/{slug}/usage", dependencies=[Depends(require_admin)])
def clinic_usage(slug: str, db: Session = Depends(get_db)):
    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    return crud.get_usage_summary(db, clinic.id)


@router.get("/stats", dependencies=[Depends(require_admin)])
def overall_stats(db: Session = Depends(get_db)):
    clinics = crud.list_clinics(db)
    usage_by_id    = {r["clinic_id"]: r for r in crud.get_all_usage_summary(db)}
    sessions_by_id = crud.get_all_monthly_sessions(db)
    return {
        "total_clinics":  len(clinics),
        "active_clinics": sum(1 for c in clinics if c.subscription_status == "active"),
        "trial_clinics":  sum(1 for c in clinics if c.subscription_status == "trial"),
        "mrr": sum(c.monthly_rate for c in clinics if c.subscription_status == "active"),
        "clinics": [
            {
                **_serialize(c),
                "usage": usage_by_id.get(c.id, {"messages": 0, "tokens": 0}),
                "sessions_this_month": sessions_by_id.get(c.id, 0),
            }
            for c in clinics
        ],
    }


# ── Billing ───────────────────────────────────────────────────────────────────

@router.post("/clinics/{slug}/checkout", dependencies=[Depends(require_admin)])
def create_checkout(slug: str, db: Session = Depends(get_db)):
    """Build a PayPal.me payment link pre-filled with the clinic's monthly rate."""
    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    base   = settings.paypal_me_url.rstrip("/")
    amount = int(clinic.monthly_rate) if clinic.monthly_rate == int(clinic.monthly_rate) else clinic.monthly_rate
    url    = f"{base}/{amount}"
    return {"url": url, "method": "paypal"}


@router.get("/clinics/{slug}/billing", dependencies=[Depends(require_admin)])
def get_billing_status(slug: str, db: Session = Depends(get_db)):
    """View Stripe subscription status for a clinic."""
    from backend.services.stripe_svc import get_subscription, stripe_enabled

    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")

    stripe_sub = None
    if stripe_enabled() and clinic.stripe_subscription_id:
        stripe_sub = get_subscription(clinic.stripe_subscription_id)

    return {
        "slug":                  clinic.slug,
        "plan":                  clinic.plan,
        "subscription_status":   clinic.subscription_status,
        "monthly_rate":          clinic.monthly_rate,
        "subscription_ends_at":  clinic.subscription_ends_at.isoformat() if clinic.subscription_ends_at else None,
        "stripe_customer_id":    clinic.stripe_customer_id or None,
        "stripe_subscription_id": clinic.stripe_subscription_id or None,
        "stripe_live":           stripe_sub,
    }


@router.post("/clinics/{slug}/billing-portal", dependencies=[Depends(require_admin)])
def admin_billing_portal(slug: str, db: Session = Depends(get_db)):
    """Generate a Stripe Customer Portal link so the clinic can manage their own billing."""
    from backend.services.stripe_svc import create_customer_portal_session

    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    if not clinic.stripe_customer_id:
        raise HTTPException(400, "Clinic has no Stripe customer — they must complete checkout first.")

    result = create_customer_portal_session(
        stripe_customer_id=clinic.stripe_customer_id,
        return_url=f"{settings.base_url}/c/{clinic.slug}",
    )
    if result.get("error"):
        raise HTTPException(500, f"Stripe error: {result['error']}")
    return {"portal_url": result["url"]}


@router.post("/clinics/{slug}/cancel-subscription", dependencies=[Depends(require_admin)])
def cancel_clinic_subscription(slug: str, db: Session = Depends(get_db)):
    """Cancel a clinic's Stripe subscription at end of current billing period."""
    from backend.services.stripe_svc import cancel_subscription

    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    if not clinic.stripe_subscription_id:
        raise HTTPException(400, "No active Stripe subscription to cancel.")

    ok = cancel_subscription(clinic.stripe_subscription_id, immediately=False)
    if not ok:
        raise HTTPException(500, "Failed to cancel subscription. Check Stripe credentials.")

    return {"ok": True, "message": "Subscription will cancel at end of current billing period."}


# ── SMS ───────────────────────────────────────────────────────────────────────

@router.post("/clinics/{slug}/sms", dependencies=[Depends(require_admin)])
def send_sms(slug: str, body: SmsRequest, db: Session = Depends(get_db)):
    from backend.services.twilio_svc import send_sms as _send
    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    ok = _send(to=body.to, body=body.message, from_=clinic.twilio_phone or None)
    return {"sent": ok}


@router.get("/clinics/{slug}/sms", dependencies=[Depends(require_admin)])
def list_sms(slug: str, db: Session = Depends(get_db)):
    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    convs = crud.list_sms_conversations(db, clinic.id)
    return [
        {
            "patient_phone":   c.patient_phone,
            "session_id":      c.session_id,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        }
        for c in convs
    ]


# ── Helper ────────────────────────────────────────────────────────────────────

def _serialize(clinic) -> dict:
    return {
        "id":                  clinic.id,
        "slug":                clinic.slug,
        "name":                clinic.name,
        "specialty":           clinic.specialty,
        "agent_name":          clinic.agent_name,
        "city_state":          clinic.city_state,
        "timezone":            clinic.timezone,
        "address":             clinic.address,
        "phone":               clinic.phone,
        "email":               clinic.email,
        "website":             clinic.website,
        "office_hours":        clinic.office_hours,
        "after_hours_protocol":clinic.after_hours_protocol,
        "providers":           clinic.providers,
        "services_offered":    clinic.services_offered,
        "insurance_accepted":  clinic.insurance_accepted,
        "pms_system":          clinic.pms_system,
        "cancellation_policy": clinic.cancellation_policy,
        "escalation_contact":  clinic.escalation_contact,
        "hipaa_verify_method": clinic.hipaa_verify_method,
        "twilio_phone":        clinic.twilio_phone,
        "stripe_customer_id":  clinic.stripe_customer_id,
        "plan":                clinic.plan or "professional",
        "subscription_status": clinic.subscription_status,
        "monthly_rate":        clinic.monthly_rate,
        "trial_ends_at":          clinic.trial_ends_at.isoformat() if clinic.trial_ends_at else None,
        "subscription_ends_at":   clinic.subscription_ends_at.isoformat() if clinic.subscription_ends_at else None,
        "activated_at":           clinic.activated_at.isoformat() if clinic.activated_at else None,
        "admin_notes":            clinic.admin_notes or "",
        "is_active":           clinic.is_active,
        "created_at":          clinic.created_at.isoformat() if clinic.created_at else None,
    }
