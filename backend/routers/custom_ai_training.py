"""Custom AI training router — manage clinic-specific agent training data."""
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.crud import (
    get_clinic_by_token,
    list_custom_ai_training,
    get_custom_ai_training,
    create_custom_ai_training,
    update_custom_ai_training,
    delete_custom_ai_training,
)
from backend.plans import can_use_custom_ai_training
from backend.services.custom_ai_training_svc import get_training_summary

router = APIRouter(prefix="/api", tags=["custom_ai_training"])


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/{clinic_slug}/custom-ai-training")
def list_training(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """List all custom AI training items for this clinic."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_ai_training(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Custom AI training not available on your plan. Upgrade to Enterprise."
        })

    items = list_custom_ai_training(db, clinic.id)
    return {
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "type": item.training_type,
                "content": item.content,
                "is_active": item.is_active,
                "priority": item.priority,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in items
        ],
        "summary": get_training_summary(db, clinic.id),
    }


@router.post("/{clinic_slug}/custom-ai-training")
def create_training(
    clinic_slug: str,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Create a new custom AI training item (max 50 per clinic, max 5000 chars)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_ai_training(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Custom AI training not available on your plan. Upgrade to Enterprise."
        })

    if not data.get("title") or not data.get("content"):
        return JSONResponse(status_code=400, content={"error": "title and content required"})

    content = data.get("content", "").strip()
    if len(content) > 5000:
        return JSONResponse(status_code=400, content={"error": "content must be ≤ 5000 characters"})

    items = list_custom_ai_training(db, clinic.id)
    if len(items) >= 50:
        return JSONResponse(status_code=400, content={"error": "Maximum 50 training items per clinic"})

    item = create_custom_ai_training(
        db,
        clinic.id,
        {
            "training_type": data.get("training_type", "custom"),
            "title": data.get("title", "").strip()[:255],
            "content": content,
            "is_active": data.get("is_active", True),
            "priority": min(10, max(0, data.get("priority", 0))),
        },
    )

    return {
        "id": item.id,
        "title": item.title,
        "type": item.training_type,
        "content": item.content,
        "is_active": item.is_active,
        "priority": item.priority,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.patch("/{clinic_slug}/custom-ai-training/{training_id}")
def update_training(
    clinic_slug: str,
    training_id: int,
    data: dict,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Update a custom AI training item."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_ai_training(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Custom AI training not available on your plan. Upgrade to Enterprise."
        })

    item = get_custom_ai_training(db, training_id, clinic.id)
    if not item:
        return JSONResponse(status_code=404, content={"error": "Training item not found"})

    if "content" in data:
        content = data.get("content", "").strip()
        if len(content) > 5000:
            return JSONResponse(status_code=400, content={"error": "content must be ≤ 5000 characters"})

    update_data = {}
    if "training_type" in data:
        update_data["training_type"] = data["training_type"]
    if "title" in data:
        update_data["title"] = data["title"][:255]
    if "content" in data:
        update_data["content"] = data["content"].strip()
    if "is_active" in data:
        update_data["is_active"] = bool(data["is_active"])
    if "priority" in data:
        update_data["priority"] = min(10, max(0, int(data["priority"])))

    item = update_custom_ai_training(db, training_id, clinic.id, update_data)
    if not item:
        return JSONResponse(status_code=404, content={"error": "Training item not found"})

    return {
        "id": item.id,
        "title": item.title,
        "type": item.training_type,
        "content": item.content,
        "is_active": item.is_active,
        "priority": item.priority,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.delete("/{clinic_slug}/custom-ai-training/{training_id}")
def delete_training(
    clinic_slug: str,
    training_id: int,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Delete a custom AI training item."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_ai_training(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Custom AI training not available on your plan. Upgrade to Enterprise."
        })

    success = delete_custom_ai_training(db, training_id, clinic.id)
    if not success:
        return JSONResponse(status_code=404, content={"error": "Training item not found"})

    return {"deleted": True}


@router.get("/{clinic_slug}/custom-ai-training/summary")
def training_summary(
    clinic_slug: str,
    db: Session = Depends(get_db),
    x_clinic_token: str = Header(None),
):
    """Get summary of custom AI training (count and metadata, no content)."""
    clinic = get_clinic_by_token(db, x_clinic_token)
    if not clinic or clinic.slug != clinic_slug:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})

    if not can_use_custom_ai_training(clinic):
        return JSONResponse(status_code=403, content={
            "error": "Custom AI training not available on your plan. Upgrade to Enterprise."
        })

    return get_training_summary(db, clinic.id)
