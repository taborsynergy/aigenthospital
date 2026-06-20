"""Clinic Holidays CRUD — blocked dates where Aria never offers slots."""
import re
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.db.database import get_db
from backend.db.crud import get_clinic_by_token
from backend.db.models import ClinicHoliday

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_HOLIDAYS = 100  # sanity cap per clinic


class _HolidayBody(BaseModel):
    date: str             # ISO "2026-07-04"
    reason: Optional[str] = ""


def _serialize(h: ClinicHoliday) -> dict:
    return {
        "id":     h.id,
        "date":   h.date,
        "reason": h.reason or "",
    }


@router.get("/api/{clinic_slug}/holidays")
async def list_holidays(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    rows = (
        db.query(ClinicHoliday)
        .filter(ClinicHoliday.clinic_id == clinic.id)
        .order_by(ClinicHoliday.date)
        .all()
    )
    return {"holidays": [_serialize(r) for r in rows]}


@router.post("/api/{clinic_slug}/holidays")
async def add_holiday(
    clinic_slug: str,
    body: _HolidayBody,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    date = (body.date or "").strip()
    if not _DATE_RE.match(date):
        return JSONResponse(status_code=400, content={
            "error": "date must be ISO format: YYYY-MM-DD"
        })

    # Duplicate check
    existing = db.query(ClinicHoliday).filter(
        ClinicHoliday.clinic_id == clinic.id,
        ClinicHoliday.date == date,
    ).first()
    if existing:
        return JSONResponse(status_code=409, content={
            "error": f"{date} is already a blocked date."
        })

    count = db.query(ClinicHoliday).filter(ClinicHoliday.clinic_id == clinic.id).count()
    if count >= _MAX_HOLIDAYS:
        return JSONResponse(status_code=400, content={
            "error": f"Maximum {_MAX_HOLIDAYS} blocked dates per clinic."
        })

    row = ClinicHoliday(
        clinic_id=clinic.id,
        date=date,
        reason=(body.reason or "").strip()[:200],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/api/{clinic_slug}/holidays/{holiday_id}")
async def delete_holiday(
    clinic_slug: str,
    holiday_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    row = db.query(ClinicHoliday).filter(
        ClinicHoliday.id == holiday_id,
        ClinicHoliday.clinic_id == clinic.id,
    ).first()
    if not row:
        return JSONResponse(status_code=404, content={"error": "Holiday not found"})

    db.delete(row)
    db.commit()
    return {"ok": True, "deleted_id": holiday_id}
