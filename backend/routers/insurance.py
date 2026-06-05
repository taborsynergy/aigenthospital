"""Custom insurance knowledge management endpoints."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.crud import get_clinic_by_token, get_or_create_insurance_knowledge, update_insurance_knowledge
from backend.plans import can_use_custom_insurance

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


class InsuranceKnowledgeUpdate(BaseModel):
    accepted_plans: Optional[str] = None
    copay_info: Optional[str] = None
    deductible_info: Optional[str] = None
    prior_auth_notes: Optional[str] = None
    custom_knowledge: Optional[str] = None


def _serialize(knowledge) -> dict:
    """Serialize insurance knowledge to dict."""
    return {
        "accepted_plans": knowledge.accepted_plans or "",
        "copay_info": knowledge.copay_info or "",
        "deductible_info": knowledge.deductible_info or "",
        "prior_auth_notes": knowledge.prior_auth_notes or "",
        "custom_knowledge": knowledge.custom_knowledge or "",
    }


@router.get("/{clinic_slug}/insurance-knowledge")
def get_insurance_knowledge(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get custom insurance knowledge for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_insurance(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Custom insurance knowledge not available on your plan. Upgrade to Professional or above."
        })

    knowledge = get_or_create_insurance_knowledge(db, clinic.id)
    return _serialize(knowledge)


@router.patch("/{clinic_slug}/insurance-knowledge")
def update_clinic_insurance_knowledge(
    clinic_slug: str,
    body: InsuranceKnowledgeUpdate,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update custom insurance knowledge."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_insurance(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Custom insurance knowledge not available on your plan. Upgrade to Professional or above."
        })

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return JSONResponse(status_code=400, content={"error": "No fields to update."})

    knowledge = get_or_create_insurance_knowledge(db, clinic.id)
    knowledge = update_insurance_knowledge(db, clinic.id, updates)

    logger.info("Insurance knowledge updated: clinic=%s", clinic_slug)
    return _serialize(knowledge)
