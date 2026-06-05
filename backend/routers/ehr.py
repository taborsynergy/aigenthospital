"""EHR system integration management endpoints."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.crud import get_clinic_by_token, get_or_create_ehr_configuration, update_ehr_configuration
from backend.plans import can_use_ehr_integration
from backend.services.ehr_svc import test_ehr_connection, get_supported_ehr_systems

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


class EHRConfigurationUpdate(BaseModel):
    ehr_system: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_key: Optional[str] = None
    client_id: Optional[str] = None
    auto_sync: Optional[bool] = None
    sync_patients: Optional[bool] = None


def _serialize(config) -> dict:
    """Serialize EHR configuration to dict (hide sensitive data)."""
    return {
        "ehr_system": config.ehr_system or "",
        "api_endpoint": config.api_endpoint or "",
        "auto_sync": config.auto_sync,
        "sync_patients": config.sync_patients,
        "last_sync_at": config.last_sync_at.isoformat() if config.last_sync_at else None,
        "sync_status": config.sync_status,
        "error_message": config.error_message or "",
    }


@router.get("/{clinic_slug}/ehr-config")
def get_ehr_configuration(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get EHR configuration for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_ehr_integration(clinic):
        return JSONResponse(status_code=403, content={
            "error": "EHR integration not available on your plan. Upgrade to Pro or above."
        })

    config = get_or_create_ehr_configuration(db, clinic.id)
    return _serialize(config)


@router.patch("/{clinic_slug}/ehr-config")
def update_ehr_config(
    clinic_slug: str,
    body: EHRConfigurationUpdate,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update EHR configuration."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_ehr_integration(clinic):
        return JSONResponse(status_code=403, content={
            "error": "EHR integration not available on your plan. Upgrade to Pro or above."
        })

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return JSONResponse(status_code=400, content={"error": "No fields to update."})

    config = get_or_create_ehr_configuration(db, clinic.id)
    config = update_ehr_configuration(db, clinic.id, updates)

    logger.info("EHR configuration updated: clinic=%s system=%s", clinic_slug, config.ehr_system)
    return _serialize(config)


@router.post("/{clinic_slug}/ehr-config/test")
def test_ehr_config(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Test EHR connection with current configuration."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_ehr_integration(clinic):
        return JSONResponse(status_code=403, content={
            "error": "EHR integration not available on your plan. Upgrade to Pro or above."
        })

    config = get_or_create_ehr_configuration(db, clinic.id)
    success, message = test_ehr_connection(config)

    if success:
        logger.info("EHR test passed: clinic=%s system=%s", clinic_slug, config.ehr_system)
        return {"success": True, "message": message}
    else:
        logger.warning("EHR test failed: clinic=%s — %s", clinic_slug, message)
        return {"success": False, "message": message}


@router.get("/{clinic_slug}/ehr-config/systems")
def get_supported_systems(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get list of supported EHR systems."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_ehr_integration(clinic):
        return JSONResponse(status_code=403, content={
            "error": "EHR integration not available on your plan. Upgrade to Pro or above."
        })

    return {
        "supported_systems": get_supported_ehr_systems(),
        "note": "Additional EHR systems can be integrated upon request"
    }
