"""
Stripe webhook handler.
POST /billing/webhook — called by Stripe for subscription events.
"""
import logging

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.crud import get_clinic_by_stripe_customer, update_clinic, get_clinic
from backend.services.stripe_svc import handle_webhook

router = APIRouter(prefix="/billing")
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()
    event = handle_webhook(payload, stripe_signature or "")

    if event is None:
        # Stripe not configured or signature check failed — accept silently
        return {"received": True}

    etype = event["type"]
    logger.info("Stripe event: %s", etype)

    if etype == "checkout.session.completed":
        session = event["data"]["object"]
        slug = session.get("metadata", {}).get("clinic_slug")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        if slug:
            now = datetime.utcnow()
            existing = get_clinic(db, slug)
            update_data = {
                "stripe_customer_id":     customer_id or "",
                "stripe_subscription_id": subscription_id or "",
                "subscription_status":    "active",
                "subscription_ends_at":   now + timedelta(days=30),
            }
            if existing and not existing.activated_at:
                update_data["activated_at"] = now
            update_clinic(db, slug, update_data)
            logger.info("Clinic %s activated via Stripe checkout", slug)

    elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        sub = event["data"]["object"]
        customer_id = sub.get("customer")
        status = sub.get("status", "cancelled")
        clinic = get_clinic_by_stripe_customer(db, customer_id)
        if clinic:
            new_status = "active" if status == "active" else ("past_due" if status == "past_due" else "cancelled")
            update_clinic(db, clinic.slug, {"subscription_status": new_status})
            logger.info("Clinic %s subscription → %s", clinic.slug, new_status)

    return {"received": True}
