"""Widget customization endpoints."""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import WidgetConfig
from backend.db.crud import get_clinic_by_token

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


class WidgetConfigUpdate(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    button_color: Optional[str] = None
    font_family: Optional[str] = None
    widget_title: Optional[str] = None
    widget_subtitle: Optional[str] = None
    cta_button_text: Optional[str] = None
    show_logo: Optional[bool] = None
    show_ratings: Optional[bool] = None
    enable_chat: Optional[bool] = None


def _serialize(cfg: WidgetConfig) -> dict:
    return {
        "logo_url": cfg.logo_url or "",
        "primary_color": cfg.primary_color,
        "button_color": cfg.button_color,
        "font_family": cfg.font_family,
        "widget_title": cfg.widget_title,
        "widget_subtitle": cfg.widget_subtitle,
        "cta_button_text": cfg.cta_button_text,
        "show_logo": cfg.show_logo,
        "show_ratings": cfg.show_ratings,
        "enable_chat": cfg.enable_chat,
    }


@router.get("/{clinic_slug}/widget/config")
def get_widget_config(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get widget customization settings."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    cfg = db.query(WidgetConfig).filter(WidgetConfig.clinic_id == clinic.id).first()
    if not cfg:
        # Return defaults
        return {
            "logo_url": "",
            "primary_color": "#007ACC",
            "button_color": "#007ACC",
            "font_family": "'Segoe UI', sans-serif",
            "widget_title": "Book an Appointment",
            "widget_subtitle": "Quick and easy scheduling",
            "cta_button_text": "Schedule Now",
            "show_logo": True,
            "show_ratings": True,
            "enable_chat": True,
        }
    return _serialize(cfg)


@router.patch("/{clinic_slug}/widget/config")
def update_widget_config(
    clinic_slug: str,
    body: WidgetConfigUpdate,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update widget customization."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return JSONResponse(status_code=400, content={"error": "No fields to update."})

    cfg = db.query(WidgetConfig).filter(WidgetConfig.clinic_id == clinic.id).first()
    if not cfg:
        cfg = WidgetConfig(clinic_id=clinic.id)
        db.add(cfg)

    for k, v in updates.items():
        setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    logger.info("Widget config updated: clinic=%s", clinic_slug)
    return _serialize(cfg)
