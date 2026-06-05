"""Custom AI training service for clinic-specific agent customization."""
import logging
from sqlalchemy.orm import Session

from backend.db.crud import get_active_training_context

logger = logging.getLogger(__name__)


def build_training_prompt_injection(db: Session, clinic_id: int) -> str:
    """
    Build a system prompt injection from clinic's custom training data.
    Returns formatted string ready for inclusion in system prompt.
    """
    context = get_active_training_context(db, clinic_id)
    if not context:
        return ""

    injection = f"""
You have been provided with custom training data specific to this healthcare clinic:

{context}

This training data takes precedence over generic healthcare knowledge. Use it to:
- Provide accurate clinic-specific information about procedures, policies, and practices
- Answer questions about their specific intake forms, telehealth requirements, or cancellation policies
- Reference their staff, services, and office hours as provided in the training
- Explain their insurance acceptance policies and payment requirements
- Direct patients to appropriate resources mentioned in their training data

Always prioritize this clinic-specific information when available.
"""
    return injection.strip()


def get_training_summary(db: Session, clinic_id: int) -> dict:
    """Get a summary of clinic's training data (metadata without content)."""
    from backend.db.crud import list_custom_ai_training

    items = list_custom_ai_training(db, clinic_id)
    return {
        "total_items": len(items),
        "active_items": sum(1 for item in items if item.is_active),
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "type": item.training_type,
                "is_active": item.is_active,
                "priority": item.priority,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ],
    }
