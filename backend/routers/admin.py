"""
Admin API — protected by X-Admin-Password header.
Provides CRUD for clinics, usage stats, and billing actions.
"""
import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db import crud
from backend.agent.aria import invalidate_prompt
from backend.auth import verify_admin_password

router = APIRouter(prefix="/admin/api")
logger = logging.getLogger(__name__)


# ── Auth ─────────────────────────────────────────────────────────────────────

def require_admin(x_admin_password: Optional[str] = Header(None)):
    # Constant-time comparison (see auth.verify_admin_password) to avoid leaking
    # the password length/prefix via response timing.
    if not verify_admin_password(x_admin_password):
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


# ── Clinic CRUD ───────────────────────────────────────────────────────────────

@router.get("/clinics", dependencies=[Depends(require_admin)])
def list_clinics(db: Session = Depends(get_db), limit: int = 100, offset: int = 0, status: str = ""):
    """List clinics (paginated). Params: limit (1-500), offset (>=0), status filter.
    Total count in X-Total-Count header. Default returns first 100 (unchanged shape)."""
    from fastapi.responses import JSONResponse
    limit = max(1, min(int(limit) if str(limit).lstrip("-").isdigit() else 100, 500))
    offset = max(0, int(offset) if str(offset).lstrip("-").isdigit() else 0)
    clinics, total = crud.list_clinics_paged(db, limit=limit, offset=offset,
                                             status=(status.strip() or None))
    return JSONResponse(content=[_serialize(c) for c in clinics],
                        headers={"X-Total-Count": str(total)})


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
def deactivate_clinic(slug: str, hard: bool = False, db: Session = Depends(get_db)):
    """
    Default (hard=false): reversible soft-delete (deactivate).
    hard=true: permanent purge of the clinic + all its data (cascades). Irreversible —
    use for right-to-be-forgotten / removing test data.
    """
    if hard:
        ok = crud.purge_clinic(db, slug)
        if not ok:
            raise HTTPException(404, "Clinic not found.")
        return {"purged": slug}
    ok = crud.deactivate_clinic(db, slug)
    if not ok:
        raise HTTPException(404, "Clinic not found.")
    return {"deleted": slug}


@router.post("/clinics/{slug}/activate", dependencies=[Depends(require_admin)])
def activate_subscription(slug: str, payment_reference: str = "", db: Session = Depends(get_db)):
    """Manually activate a 30-day subscription after payment is confirmed.

    Pass payment_reference (PayPal txn id / receipt) to reconcile the activation
    with a specific payment — re-submitting the same reference is a safe no-op
    (no double-credit), giving a 1:1 payment->activation mapping.
    """
    clinic = crud.activate_subscription(db, slug, payment_reference=payment_reference)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    return _serialize(clinic)


@router.post("/clinics/{slug}/plan", dependencies=[Depends(require_admin)])
def change_clinic_plan(slug: str, plan: str, request: Request, db: Session = Depends(get_db)):
    """
    Switch a clinic's plan tier (upgrade or downgrade), e.g. starter -> professional
    -> enterprise and back. Syncs monthly_rate; feature gating follows automatically.
    Returns any downgrade warnings (existing providers/locations over the new limit).
    """
    from backend.plans import PLANS, PLAN_RATES
    from backend.db.models import Provider, Location

    key = (plan or "").lower().strip()
    if key not in PLANS:
        raise HTTPException(400, f"Invalid plan '{plan}'. Valid: {', '.join(PLANS)}.")

    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")

    old_plan = clinic.plan
    new = PLANS[key]

    # Downgrade guardrail: warn (don't block) if current usage exceeds the new plan
    warnings = []
    prov_count = db.query(Provider).filter_by(clinic_id=clinic.id, is_active=True).count()
    loc_count = db.query(Location).filter_by(clinic_id=clinic.id, is_active=True).count()
    if new.get("max_providers") is not None and prov_count > new["max_providers"]:
        warnings.append(
            f"{prov_count} providers exceed the {new['max_providers']} allowed on {new['name']} "
            f"(existing kept; you can't add more until under the limit)."
        )
    if new.get("max_locations") is not None and loc_count > new["max_locations"]:
        warnings.append(
            f"{loc_count} locations exceed the {new['max_locations']} allowed on {new['name']} "
            f"(existing kept; you can't add more until under the limit)."
        )

    crud.change_plan(db, slug, key)
    invalidate_prompt(slug)
    crud.write_audit_log(
        db, actor="admin", action="clinic.plan_changed", target=slug,
        detail=json.dumps({"from": old_plan, "to": key, "monthly_rate": PLAN_RATES[key]}),
        ip=(request.client.host if request.client else ""),
    )
    return {
        "slug": slug,
        "previous_plan": old_plan,
        "plan": key,
        "monthly_rate": PLAN_RATES[key],
        "warnings": warnings,
    }


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
    """View subscription billing status for a clinic (PayPal-managed)."""
    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")

    return {
        "slug":                 clinic.slug,
        "plan":                 clinic.plan,
        "subscription_status":  clinic.subscription_status,
        "monthly_rate":         clinic.monthly_rate,
        "subscription_ends_at": clinic.subscription_ends_at.isoformat() if clinic.subscription_ends_at else None,
        "payment_processor":    "paypal",
    }


@router.post("/clinics/{slug}/cancel-subscription", dependencies=[Depends(require_admin)])
def cancel_clinic_subscription(slug: str, db: Session = Depends(get_db)):
    """Cancel a clinic's subscription (manual PayPal flow)."""
    clinic = crud.get_clinic(db, slug)
    if not clinic:
        raise HTTPException(404, "Clinic not found.")
    if clinic.subscription_status == "cancelled":
        raise HTTPException(400, "Subscription is already cancelled.")

    crud.update_clinic(db, slug, {"subscription_status": "cancelled"})
    return {"ok": True, "message": "Subscription marked as cancelled."}


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
