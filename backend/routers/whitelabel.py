"""White label configuration router — Enterprise feature for custom branding, domains, and reselling."""
from datetime import datetime
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.crud import (
    get_clinic_by_token,
    get_whitelabel_config,
    create_whitelabel_config,
    update_whitelabel_config,
)
from backend.plans import (
    can_use_custom_branding,
    can_use_custom_domain,
    can_enable_reselling,
    can_access_source_code,
)

router = APIRouter(prefix="/api", tags=["whitelabel"])


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/{clinic_slug}/whitelabel")
def get_whitelabel_config_endpoint(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get white label configuration for clinic (Enterprise only)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_branding(clinic):
        return JSONResponse(status_code=403, content={
            "error": "White label feature not available on your plan. Upgrade to Enterprise."
        })

    config = get_whitelabel_config(db, clinic.id)
    if not config:
        config = create_whitelabel_config(db, clinic.id, {})

    return {
        "id": config.id,
        "logo_url": config.logo_url,
        "primary_color": config.primary_color,
        "secondary_color": config.secondary_color,
        "accent_color": config.accent_color,
        "font_family": config.font_family,
        "company_name": config.company_name,
        "remove_tabor_branding": config.remove_tabor_branding,
        "remove_powered_by": config.remove_powered_by,
        "custom_footer_text": config.custom_footer_text,
        "custom_domain": config.custom_domain,
        "domain_verified": config.domain_verified,
        "is_reseller": config.is_reseller,
        "can_access_source": config.can_access_source,
        "self_host_enabled": config.self_host_enabled,
    }


@router.patch("/{clinic_slug}/whitelabel")
def update_whitelabel_branding(
    clinic_slug: str,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update white label branding (colors, logo, company name)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_branding(clinic):
        return JSONResponse(status_code=403, content={
            "error": "White label feature not available on your plan."
        })

    config = get_whitelabel_config(db, clinic.id)
    if not config:
        config = create_whitelabel_config(db, clinic.id, {})

    # Validate and sanitize branding data
    allowed_fields = {
        "logo_url", "primary_color", "secondary_color", "accent_color",
        "font_family", "company_name", "remove_tabor_branding",
        "remove_powered_by", "custom_footer_text"
    }

    update_data = {k: v for k, v in data.items() if k in allowed_fields}

    # Validate colors are hex format
    for color_field in ["primary_color", "secondary_color", "accent_color"]:
        if color_field in update_data:
            color = update_data[color_field]
            if not (isinstance(color, str) and color.startswith("#") and len(color) in [7, 4]):
                return JSONResponse(status_code=400, content={
                    "error": f"{color_field} must be hex color (e.g., #007ACC)"
                })

    config = update_whitelabel_config(db, clinic.id, update_data)
    if not config:
        return JSONResponse(status_code=400, content={"error": "Failed to update branding"})

    return {
        "logo_url": config.logo_url,
        "primary_color": config.primary_color,
        "secondary_color": config.secondary_color,
        "accent_color": config.accent_color,
        "font_family": config.font_family,
        "company_name": config.company_name,
        "remove_tabor_branding": config.remove_tabor_branding,
        "remove_powered_by": config.remove_powered_by,
    }


@router.post("/{clinic_slug}/whitelabel/domain")
def set_custom_domain(
    clinic_slug: str,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Set custom domain (requires DNS verification)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_domain(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Custom domain feature not available on your plan."
        })

    domain = data.get("custom_domain", "").strip().lower()
    if not domain or "." not in domain:
        return JSONResponse(status_code=400, content={
            "error": "Valid custom domain required (e.g., clinic.yourdomain.com)"
        })

    config = get_whitelabel_config(db, clinic.id)
    if not config:
        config = create_whitelabel_config(db, clinic.id, {})

    config.custom_domain = domain
    config.domain_verified = False  # Requires DNS verification (manual for now)
    db.commit()
    db.refresh(config)

    return {
        "custom_domain": config.custom_domain,
        "domain_verified": config.domain_verified,
        "verification_instructions": (
            f"Add CNAME record: clinic-{clinic.id}.yourdomain.com -> "
            f"app.aigenthospital.com (DNS propagation can take up to 24 hours)"
        ),
    }


@router.get("/{clinic_slug}/whitelabel/reseller")
def get_reseller_config(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get reseller configuration (sub-tenant management)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_enable_reselling(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Reseller feature not available on your plan."
        })

    config = get_whitelabel_config(db, clinic.id)
    if not config:
        config = create_whitelabel_config(db, clinic.id, {})

    return {
        "is_reseller": config.is_reseller,
        "reseller_commission": config.reseller_commission,
        "max_sub_clinics": config.max_sub_clinics if config.max_sub_clinics > 0 else "unlimited",
        "message": "Reseller mode allows you to create and manage sub-clinics"
    }


@router.post("/{clinic_slug}/whitelabel/reseller/enable")
def enable_reseller_mode(
    clinic_slug: str,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Enable reseller mode (create sub-clinics)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_enable_reselling(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Reseller feature not available on your plan."
        })

    config = get_whitelabel_config(db, clinic.id)
    if not config:
        config = create_whitelabel_config(db, clinic.id, {})

    # Validate commission rate (0-30%)
    commission = float(data.get("reseller_commission", 20.0))
    if not (0 <= commission <= 30):
        return JSONResponse(status_code=400, content={
            "error": "Commission rate must be between 0% and 30%"
        })

    max_subs = int(data.get("max_sub_clinics", 0))  # 0 = unlimited
    if max_subs < 0:
        return JSONResponse(status_code=400, content={
            "error": "max_sub_clinics must be >= 0 (0 = unlimited)"
        })

    config.is_reseller = True
    config.reseller_commission = commission
    config.max_sub_clinics = max_subs
    db.commit()
    db.refresh(config)

    return {
        "is_reseller": True,
        "reseller_commission": config.reseller_commission,
        "max_sub_clinics": config.max_sub_clinics if config.max_sub_clinics > 0 else "unlimited",
        "message": "Reseller mode enabled. Use POST /api/{clinic_slug}/clinics/create-sub to create sub-clinics.",
    }


@router.post("/{clinic_slug}/whitelabel/source-code")
def grant_source_code_access(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Grant source code access (for self-hosting)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_access_source_code(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Source code access not available on your plan."
        })

    config = get_whitelabel_config(db, clinic.id)
    if not config:
        config = create_whitelabel_config(db, clinic.id, {})

    if config.can_access_source:
        return JSONResponse(status_code=200, content={
            "can_access_source": True,
            "message": "Source code access already granted",
            "access_granted_at": config.source_access_granted_at.isoformat() if config.source_access_granted_at else None,
        })

    config.can_access_source = True
    config.source_access_granted_at = datetime.utcnow()
    config.self_host_enabled = True
    db.commit()
    db.refresh(config)

    return {
        "can_access_source": True,
        "self_host_enabled": True,
        "access_granted_at": config.source_access_granted_at.isoformat(),
        "setup_instructions": (
            "1. Clone the private GitHub repo: git clone https://github.com/taborsynergy/aigenthospital-private.git\n"
            "2. Follow the self-hosting guide: docs/SELF_HOSTING.md\n"
            "3. Configure environment variables in .env.local\n"
            "4. Run docker-compose up to start your instance\n"
            "5. Update custom domain DNS to point to your infrastructure"
        ),
    }
