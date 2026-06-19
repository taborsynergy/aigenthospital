"""
Recall campaign endpoints.

Clinic-authenticated:
  GET    /api/{slug}/recall-campaigns          — list campaigns
  POST   /api/{slug}/recall-campaigns          — create campaign
  GET    /api/{slug}/recall-campaigns/{id}     — get one campaign + stats
  PATCH  /api/{slug}/recall-campaigns/{id}     — update campaign
  DELETE /api/{slug}/recall-campaigns/{id}     — delete campaign
  GET    /api/{slug}/recall-campaigns/{id}/preview — patients due (dry run)
  POST   /api/{slug}/recall-campaigns/{id}/run     — send now (manual trigger)

Admin:
  POST   /api/recall/trigger  — run ALL active campaigns across all clinics (cron)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.crud import (
    get_clinic_by_token, get_recall_campaign,
    list_recall_campaigns, create_recall_campaign,
    update_recall_campaign, delete_recall_campaign,
    get_recall_stats, mark_recall_opted_out,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _unsub_page(title: str, msg: str, status: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Unsubscribe</title></head>"
        "<body style='font-family:-apple-system,Segoe UI,sans-serif;background:#f6f8fa;margin:0'>"
        "<div style='max-width:480px;margin:64px auto;background:#fff;border:1px solid #e2e8f0;"
        "border-radius:12px;padding:36px;text-align:center'>"
        f"<h2 style='color:#0f1f35;margin:0 0 10px'>{title}</h2>"
        f"<p style='color:#475569;font-size:15px;line-height:1.5'>{msg}</p>"
        "</div></body></html>"
    )
    return HTMLResponse(content=html, status_code=status)


@router.get("/api/unsubscribe", include_in_schema=False)
def unsubscribe(token: str = "", db: Session = Depends(get_db)):
    """Public, no-auth endpoint patients click from a recall email to opt out."""
    from backend.unsub import verify_unsub_token
    data = verify_unsub_token(token)
    if not data:
        return _unsub_page("Invalid link",
                           "This unsubscribe link is invalid or has expired.", status=400)
    clinic_id, email = data
    mark_recall_opted_out(db, clinic_id, email)
    logger.info("Recall unsubscribe: clinic=%s email=%s", clinic_id, email)
    return _unsub_page("You're unsubscribed",
                       "You will no longer receive appointment recall emails from this clinic.")


# ── Schemas ───────────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name:             str
    visit_type:       str
    interval_months:  int = 12
    message_template: str = ""
    is_active:        bool = True


class CampaignPatch(BaseModel):
    name:             Optional[str]  = None
    visit_type:       Optional[str]  = None
    interval_months:  Optional[int]  = None
    message_template: Optional[str]  = None
    is_active:        Optional[bool] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_admin(x_admin_password: str = Header(None)):
    from backend.auth import verify_admin_password
    if not verify_admin_password(x_admin_password):
        raise HTTPException(401, "Unauthorized")


def _clinic_auth(clinic_slug: str, x_clinic_token: str, db: Session):
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        raise HTTPException(403, "Unauthorized")
    return clinic


def _serialize(campaign, stats: dict = None) -> dict:
    return {
        "id":               campaign.id,
        "name":             campaign.name,
        "visit_type":       campaign.visit_type,
        "interval_months":  campaign.interval_months,
        "message_template": campaign.message_template,
        "is_active":        campaign.is_active,
        "created_at":       campaign.created_at.isoformat() if campaign.created_at else None,
        **({"stats": stats} if stats else {}),
    }


# ── Clinic-authenticated endpoints ────────────────────────────────────────────

@router.get("/api/{clinic_slug}/recall-campaigns")
def list_campaigns(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = _clinic_auth(clinic_slug, x_clinic_token, db)
    campaigns = list_recall_campaigns(db, clinic.id)
    return [_serialize(c, get_recall_stats(db, c.id)) for c in campaigns]


@router.post("/api/{clinic_slug}/recall-campaigns")
def create_campaign(
    clinic_slug: str,
    body: CampaignCreate,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = _clinic_auth(clinic_slug, x_clinic_token, db)

    if body.interval_months < 1 or body.interval_months > 36:
        return JSONResponse(status_code=400, content={
            "error": "interval_months must be between 1 and 36."
        })

    campaign = create_recall_campaign(db, {
        "clinic_id":        clinic.id,
        "name":             body.name.strip(),
        "visit_type":       body.visit_type.strip(),
        "interval_months":  body.interval_months,
        "message_template": body.message_template.strip(),
        "is_active":        body.is_active,
    })
    logger.info("Recall campaign created: clinic=%s name=%s", clinic.slug, campaign.name)
    return _serialize(campaign)


@router.get("/api/{clinic_slug}/recall-campaigns/{campaign_id}")
def get_campaign(
    clinic_slug: str,
    campaign_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = _clinic_auth(clinic_slug, x_clinic_token, db)
    campaign = get_recall_campaign(db, campaign_id, clinic.id)
    if not campaign:
        raise HTTPException(404, "Campaign not found.")
    return _serialize(campaign, get_recall_stats(db, campaign.id))


@router.patch("/api/{clinic_slug}/recall-campaigns/{campaign_id}")
def update_campaign(
    clinic_slug: str,
    campaign_id: int,
    body: CampaignPatch,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = _clinic_auth(clinic_slug, x_clinic_token, db)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return JSONResponse(status_code=400, content={"error": "No fields to update."})

    campaign = update_recall_campaign(db, campaign_id, clinic.id, updates)
    if not campaign:
        raise HTTPException(404, "Campaign not found.")
    return _serialize(campaign)


@router.delete("/api/{clinic_slug}/recall-campaigns/{campaign_id}")
def remove_campaign(
    clinic_slug: str,
    campaign_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = _clinic_auth(clinic_slug, x_clinic_token, db)
    deleted = delete_recall_campaign(db, campaign_id, clinic.id)
    if not deleted:
        raise HTTPException(404, "Campaign not found.")
    return {"ok": True}


@router.get("/api/{clinic_slug}/recall-campaigns/{campaign_id}/preview")
def preview_campaign_patients(
    clinic_slug: str,
    campaign_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Dry-run: show which patients would receive this campaign, without sending SMS."""
    from backend.services.recall_svc import preview_campaign

    clinic   = _clinic_auth(clinic_slug, x_clinic_token, db)
    campaign = get_recall_campaign(db, campaign_id, clinic.id)
    if not campaign:
        raise HTTPException(404, "Campaign not found.")

    patients = preview_campaign(db, clinic.id, campaign)
    return {
        "campaign":      _serialize(campaign),
        "patient_count": len(patients),
        "patients": [
            {
                "patient_name":  p["patient_name"],
                "patient_phone": p["patient_phone"][:4] + "****" + p["patient_phone"][-2:],  # masked
                "last_visit":    p["last_visit_ts"].strftime("%B %Y") if p["last_visit_ts"] else "Unknown",
            }
            for p in patients
        ],
    }


@router.post("/api/{clinic_slug}/recall-campaigns/{campaign_id}/run")
def run_campaign_now(
    clinic_slug: str,
    campaign_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Manually trigger a campaign — emails all due patients immediately."""
    from backend.services.recall_svc import run_campaign
    from backend.plans import can_use_reminders

    clinic   = _clinic_auth(clinic_slug, x_clinic_token, db)
    campaign = get_recall_campaign(db, campaign_id, clinic.id)
    if not campaign:
        raise HTTPException(404, "Campaign not found.")
    if not can_use_reminders(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Recall campaigns are available on the Growth and Enterprise plans. Please upgrade."
        })

    stats = run_campaign(db, clinic, campaign)
    logger.info("Manual recall run: clinic=%s campaign=%d stats=%s",
                clinic.slug, campaign_id, stats)
    return {"ok": True, **stats}


# ── Admin / cron endpoint ─────────────────────────────────────────────────────

@router.post("/api/recall/trigger", dependencies=[Depends(_require_admin)])
def trigger_all_recalls(db: Session = Depends(get_db)):
    """
    Daily cron entry point — run all active recall campaigns across all clinics.
    Called by Render cron job every morning at 9 AM.
    """
    from backend.services.recall_svc import run_all_active_campaigns
    stats = run_all_active_campaigns(db)
    logger.info("Recall cron complete: %s", stats)
    return {"ok": True, **stats}
