"""
Stripe webhook handler — full subscription lifecycle.

Events handled:
  checkout.session.completed     → activate subscription, set plan
  customer.subscription.updated  → sync plan + status changes
  customer.subscription.deleted  → mark cancelled
  invoice.payment_succeeded      → extend subscription_ends_at, log payment
  invoice.payment_failed         → mark past_due, send dunning email
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.crud import get_clinic_by_stripe_customer, update_clinic, get_clinic
from backend.services.stripe_svc import handle_webhook

router = APIRouter(prefix="/billing")
logger = logging.getLogger(__name__)

# Map Stripe subscription statuses → our internal statuses
_STATUS_MAP = {
    "active":    "active",
    "past_due":  "past_due",
    "canceled":  "cancelled",
    "cancelled": "cancelled",
    "unpaid":    "past_due",
    "paused":    "past_due",
}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()

    # If Stripe is not configured (PayPal mode), accept silently
    if not settings.stripe_webhook_secret:
        return {"received": True}

    event = handle_webhook(payload, stripe_signature or "")
    if event is None:
        logger.warning("Stripe webhook rejected — invalid signature from %s",
                       request.client.host if request.client else "unknown")
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    etype = event["type"]
    logger.info("Stripe event received: %s", etype)

    try:
        if etype == "checkout.session.completed":
            _handle_checkout_completed(db, event["data"]["object"])

        elif etype == "customer.subscription.updated":
            _handle_subscription_updated(db, event["data"]["object"])

        elif etype == "customer.subscription.deleted":
            _handle_subscription_deleted(db, event["data"]["object"])

        elif etype == "invoice.payment_succeeded":
            _handle_payment_succeeded(db, event["data"]["object"])

        elif etype == "invoice.payment_failed":
            _handle_payment_failed(db, event["data"]["object"])

        else:
            logger.debug("Stripe event ignored: %s", etype)

    except Exception:
        # Log but always return 200 — prevents Stripe from retrying indefinitely
        logger.exception("Error processing Stripe event %s", etype)

    return {"received": True}


# ── Event handlers ────────────────────────────────────────────────────────────

def _handle_checkout_completed(db: Session, session: dict) -> None:
    """New subscription checkout completed — activate the clinic."""
    slug          = session.get("metadata", {}).get("clinic_slug")
    plan          = session.get("metadata", {}).get("plan", "professional")
    customer_id   = session.get("customer", "")
    subscription_id = session.get("subscription", "")

    if not slug:
        logger.warning("checkout.session.completed missing clinic_slug in metadata")
        return

    clinic = get_clinic(db, slug)
    if not clinic:
        logger.warning("checkout.session.completed: clinic not found: %s", slug)
        return

    from backend.plans import PLAN_RATES
    rate = PLAN_RATES.get(plan, PLAN_RATES["professional"])
    now  = datetime.utcnow()

    update_data = {
        "stripe_customer_id":     customer_id,
        "stripe_subscription_id": subscription_id,
        "subscription_status":    "active",
        "plan":                   plan,
        "monthly_rate":           rate,
        "subscription_ends_at":   now + timedelta(days=30),
    }
    if not clinic.activated_at:
        update_data["activated_at"] = now

    update_clinic(db, slug, update_data)
    logger.info("Clinic %s activated via Stripe checkout — plan=%s", slug, plan)

    # Welcome email
    try:
        from backend.services.email_svc import send_subscription_activated_email
        send_subscription_activated_email({
            "clinic_name":  clinic.name,
            "clinic_email": clinic.email,
            "plan":         plan,
            "rate":         rate,
            "ends_at":      (now + timedelta(days=30)).strftime("%B %d, %Y"),
            "portal_url":   f"{settings.base_url}/c/{slug}",
        })
    except Exception:
        logger.exception("Failed to send activation email for %s", slug)


def _handle_subscription_updated(db: Session, sub: dict) -> None:
    """Subscription changed — sync status and plan."""
    customer_id = sub.get("customer", "")
    status      = sub.get("status", "")
    plan        = sub.get("metadata", {}).get("plan", "")

    clinic = get_clinic_by_stripe_customer(db, customer_id)
    if not clinic:
        return

    update_data: dict = {
        "subscription_status": _STATUS_MAP.get(status, "past_due"),
    }

    # Sync plan if metadata carries it
    if plan and plan in ("starter", "professional", "enterprise"):
        from backend.plans import PLAN_RATES
        update_data["plan"] = plan
        update_data["monthly_rate"] = PLAN_RATES[plan]

    # Sync cancel_at_period_end → reflect in subscription_ends_at
    cancel_at = sub.get("cancel_at")
    if cancel_at:
        update_data["subscription_ends_at"] = datetime.utcfromtimestamp(cancel_at)

    update_clinic(db, clinic.slug, update_data)
    logger.info("Clinic %s subscription updated — status=%s plan=%s",
                clinic.slug, status, plan or "unchanged")


def _handle_subscription_deleted(db: Session, sub: dict) -> None:
    """Subscription fully cancelled."""
    customer_id = sub.get("customer", "")
    clinic = get_clinic_by_stripe_customer(db, customer_id)
    if not clinic:
        return

    update_clinic(db, clinic.slug, {"subscription_status": "cancelled"})
    logger.info("Clinic %s subscription cancelled via Stripe", clinic.slug)

    try:
        from backend.services.email_svc import send_subscription_cancelled_email
        send_subscription_cancelled_email({
            "clinic_name":  clinic.name,
            "clinic_email": clinic.email,
        })
    except Exception:
        logger.exception("Failed to send cancellation email for %s", clinic.slug)


def _handle_payment_succeeded(db: Session, invoice: dict) -> None:
    """Invoice paid — extend subscription by billing period."""
    customer_id     = invoice.get("customer", "")
    subscription_id = invoice.get("subscription", "")
    amount_paid     = invoice.get("amount_paid", 0) / 100  # cents → dollars

    clinic = get_clinic_by_stripe_customer(db, customer_id)
    if not clinic:
        return

    # Use period_end from the invoice lines if available
    lines = invoice.get("lines", {}).get("data", [])
    period_end = None
    if lines:
        period_end = lines[0].get("period", {}).get("end")

    now = datetime.utcnow()
    ends_at = (
        datetime.utcfromtimestamp(period_end)
        if period_end
        else now + timedelta(days=30)
    )

    update_clinic(db, clinic.slug, {
        "subscription_status":    "active",
        "subscription_ends_at":   ends_at,
        "stripe_subscription_id": subscription_id or clinic.stripe_subscription_id,
    })
    logger.info("Clinic %s payment succeeded — $%.2f, active until %s",
                clinic.slug, amount_paid, ends_at.date())


def _handle_payment_failed(db: Session, invoice: dict) -> None:
    """Invoice payment failed — mark past_due and send dunning email."""
    customer_id = invoice.get("customer", "")
    attempt     = invoice.get("attempt_count", 1)
    amount_due  = invoice.get("amount_due", 0) / 100

    clinic = get_clinic_by_stripe_customer(db, customer_id)
    if not clinic:
        return

    update_clinic(db, clinic.slug, {"subscription_status": "past_due"})
    logger.warning("Clinic %s payment failed — attempt=%d amount=$%.2f",
                   clinic.slug, attempt, amount_due)

    try:
        from backend.services.email_svc import send_payment_failed_email
        send_payment_failed_email({
            "clinic_name":   clinic.name,
            "clinic_email":  clinic.email,
            "amount_due":    amount_due,
            "attempt_count": attempt,
            "portal_url":    f"{settings.base_url}/c/{clinic.slug}",
        })
    except Exception:
        logger.exception("Failed to send payment-failed email for %s", clinic.slug)
