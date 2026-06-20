"""Appointment Types CRUD — clinic self-service visit type configuration."""
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.db.database import get_db
from backend.db.crud import get_clinic_by_token
from backend.db.models import AppointmentType

router = APIRouter()

_MAX_TYPES = 30  # sanity cap per clinic


class _ApptTypeBody(BaseModel):
    name: str
    duration_minutes: Optional[int] = 30
    description: Optional[str] = ""
    is_active: Optional[bool] = True


def _serialize(at: AppointmentType) -> dict:
    return {
        "id":               at.id,
        "name":             at.name,
        "duration_minutes": at.duration_minutes,
        "description":      at.description or "",
        "is_active":        at.is_active,
        "created_at":       at.created_at.isoformat() if at.created_at else None,
    }


@router.get("/api/{clinic_slug}/appointment-types")
async def list_appt_types(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    rows = (
        db.query(AppointmentType)
        .filter(AppointmentType.clinic_id == clinic.id)
        .order_by(AppointmentType.created_at)
        .all()
    )
    return {"appointment_types": [_serialize(r) for r in rows]}


@router.post("/api/{clinic_slug}/appointment-types")
async def create_appt_type(
    clinic_slug: str,
    body: _ApptTypeBody,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    name = (body.name or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "name is required"})
    if len(name) > 100:
        return JSONResponse(status_code=400, content={"error": "name too long (max 100)"})

    count = db.query(AppointmentType).filter(AppointmentType.clinic_id == clinic.id).count()
    if count >= _MAX_TYPES:
        return JSONResponse(status_code=400, content={
            "error": f"Maximum {_MAX_TYPES} appointment types per clinic."
        })

    duration = body.duration_minutes if body.duration_minutes in (15, 30, 45, 60, 90, 120) else 30

    row = AppointmentType(
        clinic_id=clinic.id,
        name=name,
        duration_minutes=duration,
        description=(body.description or "").strip()[:500],
        is_active=True if body.is_active is None else bool(body.is_active),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.patch("/api/{clinic_slug}/appointment-types/{appt_type_id}")
async def update_appt_type(
    clinic_slug: str,
    appt_type_id: int,
    body: _ApptTypeBody,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    row = db.query(AppointmentType).filter(
        AppointmentType.id == appt_type_id,
        AppointmentType.clinic_id == clinic.id,
    ).first()
    if not row:
        return JSONResponse(status_code=404, content={"error": "Appointment type not found"})

    if body.name is not None:
        n = body.name.strip()
        if not n:
            return JSONResponse(status_code=400, content={"error": "name cannot be empty"})
        row.name = n[:100]
    if body.duration_minutes is not None and body.duration_minutes in (15, 30, 45, 60, 90, 120):
        row.duration_minutes = body.duration_minutes
    if body.description is not None:
        row.description = body.description.strip()[:500]
    if body.is_active is not None:
        row.is_active = bool(body.is_active)

    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/api/{clinic_slug}/appointment-types/{appt_type_id}")
async def delete_appt_type(
    clinic_slug: str,
    appt_type_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    row = db.query(AppointmentType).filter(
        AppointmentType.id == appt_type_id,
        AppointmentType.clinic_id == clinic.id,
    ).first()
    if not row:
        return JSONResponse(status_code=404, content={"error": "Appointment type not found"})

    db.delete(row)
    db.commit()
    return {"ok": True, "deleted_id": appt_type_id}
