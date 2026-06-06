"""Provider/Doctor management router — multi-doctor practice support (Growth+ plan)."""
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.crud import (
    get_clinic_by_token,
    list_providers,
    get_provider,
    create_provider,
    update_provider,
    deactivate_provider,
    count_active_providers,
)
from backend.plans import can_add_provider, max_providers

router = APIRouter(prefix="/api", tags=["providers"])


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/{clinic_slug}/providers")
def list_clinic_providers(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """List all providers for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    providers = list_providers(db, clinic.id)
    return {
        "providers": [
            {
                "id": p.id,
                "name": p.name,
                "email": p.email,
                "phone": p.phone,
                "specialty": p.specialty,
                "license_number": p.license_number,
                "npi_number": p.npi_number,
                "bio": p.bio,
                "photo_url": p.photo_url,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in providers
        ],
        "count": len(providers),
        "max_allowed": max_providers(clinic),
    }


@router.post("/{clinic_slug}/providers")
def create_clinic_provider(
    clinic_slug: str,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Create a new provider for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    # Check provider limit
    current_count = count_active_providers(db, clinic.id)
    if not can_add_provider(clinic, current_count):
        max_allowed = max_providers(clinic)
        return JSONResponse(status_code=400, content={
            "error": f"Provider limit reached ({max_allowed}) on your {clinic.plan} plan"
        })

    # Validate required fields
    if not data.get("name") or not data.get("name").strip():
        return JSONResponse(status_code=400, content={"error": "name required"})

    # Create provider
    provider = create_provider(db, clinic.id, data)
    if not provider:
        return JSONResponse(status_code=400, content={"error": "Failed to create provider"})

    return {
        "id": provider.id,
        "name": provider.name,
        "email": provider.email,
        "phone": provider.phone,
        "specialty": provider.specialty,
        "license_number": provider.license_number,
        "npi_number": provider.npi_number,
        "bio": provider.bio,
        "photo_url": provider.photo_url,
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
    }


@router.get("/{clinic_slug}/providers/{provider_id}")
def get_clinic_provider(
    clinic_slug: str,
    provider_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get a specific provider."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    provider = get_provider(db, provider_id, clinic.id)
    if not provider:
        return JSONResponse(status_code=404, content={"error": "Provider not found"})

    return {
        "id": provider.id,
        "name": provider.name,
        "email": provider.email,
        "phone": provider.phone,
        "specialty": provider.specialty,
        "license_number": provider.license_number,
        "npi_number": provider.npi_number,
        "bio": provider.bio,
        "photo_url": provider.photo_url,
        "is_active": provider.is_active,
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


@router.patch("/{clinic_slug}/providers/{provider_id}")
def update_clinic_provider(
    clinic_slug: str,
    provider_id: int,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update a provider."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    provider = get_provider(db, provider_id, clinic.id)
    if not provider:
        return JSONResponse(status_code=404, content={"error": "Provider not found"})

    # Update provider
    updated = update_provider(db, provider_id, clinic.id, data)
    if not updated:
        return JSONResponse(status_code=404, content={"error": "Provider not found"})

    return {
        "id": updated.id,
        "name": updated.name,
        "email": updated.email,
        "phone": updated.phone,
        "specialty": updated.specialty,
        "license_number": updated.license_number,
        "npi_number": updated.npi_number,
        "bio": updated.bio,
        "photo_url": updated.photo_url,
        "is_active": updated.is_active,
        "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
    }


@router.delete("/{clinic_slug}/providers/{provider_id}")
def delete_clinic_provider(
    clinic_slug: str,
    provider_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Deactivate a provider (soft delete)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    success = deactivate_provider(db, provider_id, clinic.id)
    if not success:
        return JSONResponse(status_code=404, content={"error": "Provider not found"})

    return {"deleted": True}
