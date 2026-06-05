"""
Multi-location management endpoints.

Clinics can have multiple physical locations, each with separate:
- Address, phone, office hours
- Providers
- Timezone
- (Pro+) Intelligent routing rules
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
    create_location, update_location, delete_location, set_primary_location,
)
from backend.plans import can_use_location_routing
from backend.services.routing_svc import route_to_location, get_routing_info

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


# ── Multi-location routing (Pro+) ────────────────────────────────────────────

class LocationRoutingUpdate(BaseModel):
    zip_code_coverage: Optional[str] = None
    service_categories: Optional[str] = None


@router.patch("/{clinic_slug}/locations/{location_id}/routing")
def update_location_routing(
    clinic_slug: str,
    location_id: int,
    body: LocationRoutingUpdate,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update intelligent routing rules for a location (Pro+)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_location_routing(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Multi-location routing not available on your plan. Upgrade to Pro or above."
        })

    location = get_location(db, location_id, clinic.id)
    if not location:
        raise HTTPException(404, "Location not found.")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return JSONResponse(status_code=400, content={"error": "No fields to update."})

    location = update_location(db, location_id, clinic.id, updates)
    logger.info("Location routing updated: clinic=%s location=%d", clinic_slug, location_id)
    return {
        "location_id": location.id,
        "name": location.name,
        "zip_code_coverage": location.zip_code_coverage or "",
        "service_categories": location.service_categories or "",
    }


@router.post("/{clinic_slug}/locations/{location_id}/set-primary")
def set_location_as_primary(
    clinic_slug: str,
    location_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Set a location as the primary/default for the clinic (Pro+)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_location_routing(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Multi-location routing not available on your plan. Upgrade to Pro or above."
        })

    location = set_primary_location(db, clinic.id, location_id)
    if not location:
        raise HTTPException(404, "Location not found.")

    logger.info("Primary location set: clinic=%s location=%d", clinic_slug, location_id)
    return {"ok": True, "primary_location": location.name}


@router.post("/{clinic_slug}/routing/test")
def test_location_routing(
    clinic_slug: str,
    patient_zip: Optional[str] = None,
    appointment_type: Optional[str] = None,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Test routing logic - returns which location a patient would be routed to (Pro+)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_location_routing(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Multi-location routing not available on your plan. Upgrade to Pro or above."
        })

    location = route_to_location(clinic.id, db, patient_zip, appointment_type)
    if not location:
        return JSONResponse(status_code=404, content={"error": "No suitable location found."})

    logger.info("Routing test: clinic=%s zip=%s type=%s → location=%s",
                clinic_slug, patient_zip, appointment_type, location.name)
    return get_routing_info(location)
