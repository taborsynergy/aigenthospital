"""
Multi-location management endpoints.

Clinics can have multiple physical locations, each with separate:
- Address, phone, office hours
- Providers
- Timezone
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Location
from backend.db.crud import (
    get_clinic_by_token, list_locations, get_location,
    create_location, update_location, delete_location,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class LocationCreate(BaseModel):
    name: str
    address: Optional[str] = None
    city_state: Optional[str] = None
    phone: Optional[str] = None
    office_hours: Optional[str] = None
    providers: Optional[str] = None
    timezone: Optional[str] = "US/Eastern"


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city_state: Optional[str] = None
    phone: Optional[str] = None
    office_hours: Optional[str] = None
    providers: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None


def _serialize(loc: Location) -> dict:
    """Serialize location to dict."""
    return {
        "id":            loc.id,
        "name":          loc.name,
        "address":       loc.address or "",
        "city_state":    loc.city_state or "",
        "phone":         loc.phone or "",
        "office_hours":  loc.office_hours or "",
        "providers":     loc.providers or "",
        "timezone":      loc.timezone or "US/Eastern",
        "is_active":     loc.is_active,
        "created_at":    loc.created_at.isoformat() if loc.created_at else None,
    }


# ── Clinic-authenticated endpoints ────────────────────────────────────────────

@router.get("/{clinic_slug}/locations")
def list_clinic_locations(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """List all locations for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    locations = list_locations(db, clinic.id)
    return [_serialize(loc) for loc in locations]


@router.post("/{clinic_slug}/locations")
def create_clinic_location(
    clinic_slug: str,
    body: LocationCreate,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Create a new location for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not body.name or len(body.name.strip()) < 2:
        return JSONResponse(status_code=400, content={"error": "Location name required (min 2 chars)."})

    # Check for duplicates
    existing = [loc for loc in list_locations(db, clinic.id) if loc.name == body.name]
    if existing:
        return JSONResponse(status_code=400, content={"error": "Location name already exists."})

    location = create_location(db, {
        "clinic_id":    clinic.id,
        "name":         body.name.strip(),
        "address":      (body.address or "").strip(),
        "city_state":   (body.city_state or "").strip(),
        "phone":        (body.phone or "").strip(),
        "office_hours": (body.office_hours or "").strip(),
        "providers":    (body.providers or "").strip(),
        "timezone":     body.timezone or "US/Eastern",
    })
    logger.info("Location created: clinic=%s location=%s", clinic_slug, location.name)
    return _serialize(location)


@router.get("/{clinic_slug}/locations/{location_id}")
def get_clinic_location(
    clinic_slug: str,
    location_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get a specific location."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    location = get_location(db, location_id, clinic.id)
    if not location:
        raise HTTPException(404, "Location not found.")
    return _serialize(location)


@router.patch("/{clinic_slug}/locations/{location_id}")
def update_clinic_location(
    clinic_slug: str,
    location_id: int,
    body: LocationUpdate,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update a location."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return JSONResponse(status_code=400, content={"error": "No fields to update."})

    location = update_location(db, location_id, clinic.id, updates)
    if not location:
        raise HTTPException(404, "Location not found.")

    logger.info("Location updated: clinic=%s location=%d", clinic_slug, location_id)
    return _serialize(location)


@router.delete("/{clinic_slug}/locations/{location_id}")
def remove_clinic_location(
    clinic_slug: str,
    location_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Delete a location (soft-delete: sets is_active=False)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    deleted = delete_location(db, location_id, clinic.id)
    if not deleted:
        raise HTTPException(404, "Location not found.")

    logger.info("Location deleted: clinic=%s location=%d", clinic_slug, location_id)
    return {"ok": True}
