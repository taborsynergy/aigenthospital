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
    success, message = test_ehr_connection(config, clinic_id=clinic.id)

    if success:
        logger.info("EHR test passed: clinic=%s system=%s", clinic_slug, config.ehr_system)
        return {"success": True, "message": message}
    else:
        logger.warning("EHR test failed: clinic=%s — %s", clinic_slug, message)
        return {"success": False, "message": message}


@router.get("/{clinic_slug}/emr/sync-log")
def get_emr_sync_log(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Return last 20 EMR sync log entries for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})
    if not can_use_ehr_integration(clinic):
        return JSONResponse(status_code=403, content={"error": "EHR integration not available on your plan."})
    from backend.db.models import EMRSyncLog
    rows = (
        db.query(EMRSyncLog)
        .filter(EMRSyncLog.clinic_id == clinic.id)
        .order_by(EMRSyncLog.created_at.desc())
        .limit(20)
        .all()
    )
    entries = [
        {
            "id": r.id,
            "operation": r.operation,
            "direction": r.direction,
            "status": r.status,
            "ehr_system": r.ehr_system,
            "ehr_resource_id": r.ehr_resource_id,
            "error_message": r.error_message,
            "http_status": r.http_status,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"entries": entries}


@router.get("/{clinic_slug}/emr/patient-lookup")
def emr_patient_lookup(
    clinic_slug: str,
    patient_name: str,
    date_of_birth: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Look up a patient in the EHR by name + DOB."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})
    if not can_use_ehr_integration(clinic):
        return JSONResponse(status_code=403, content={"error": "EHR integration not available on your plan."})
    from backend.services.ehr_svc import lookup_patient
    patient = lookup_patient(clinic.id, patient_name, date_of_birth, db)
    if patient:
        return {"found": True, "patient": patient}
    return {"found": False}


@router.get("/{clinic_slug}/emr/slots")
def emr_get_slots(
    clinic_slug: str,
    appointment_type: str,
    date_start: str = "",
    date_end: str = "",
    provider_name: str = "",
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get available slots from EHR."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})
    if not can_use_ehr_integration(clinic):
        return JSONResponse(status_code=403, content={"error": "EHR integration not available on your plan."})
    from datetime import date, timedelta
    from backend.services.ehr_svc import get_available_slots
    if not date_start:
        date_start = (date.today() + timedelta(days=1)).isoformat()
    if not date_end:
        date_end = (date.fromisoformat(date_start) + timedelta(days=7)).isoformat()
    slots = get_available_slots(clinic.id, appointment_type, date_start, date_end,
                                provider_name or None, db)
    return {"slots": slots, "count": len(slots)}


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
