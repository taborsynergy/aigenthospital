"""
Stripe billing service — full subscription lifecycle management.

Setup (one-time in Stripe Dashboard):
  1. Create 3 Products: Starter, Professional, Enterprise
  2. Add a monthly recurring Price to each
  3. Copy the price_id (price_XXXX) into Render env vars:
       STRIPE_STARTER_PRICE_ID, STRIPE_PROFESSIONAL_PRICE_ID, STRIPE_ENTERPRISE_PRICE_ID
  4. Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET
  5. Register webhook endpoint: https://taborsynergy-agent.onrender.com/billing/webhook
     Events to enable: checkout.session.completed, customer.subscription.updated,
     customer.subscription.deleted, invoice.payment_succeeded, invoice.payment_failed

When STRIPE_SECRET_KEY is not set, all functions return mock/None — PayPal mode.
"""
import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)
_stripe = None


def _client():
    global _stripe
    if _stripe is None and settings.stripe_secret_key:
        import stripe as _s
        _s.api_key = settings.stripe_secret_key
        _stripe = _s
    return _stripe


def stripe_enabled() -> bool:
    return bool(settings.stripe_secret_key)


def get_price_id(plan: str) -> str:
    """Return the Stripe Price ID for the given plan key."""
    mapping = {
        "starter":      settings.stripe_starter_price_id,
        "professional": settings.stripe_professional_price_id,
        "enterprise":   settings.stripe_enterprise_price_id,
    }
    return mapping.get(plan.lower(), "")


# ── Checkout ──────────────────────────────────────────────────────────────────

def create_checkout_session(
    clinic_slug: str,
    clinic_name: str,
    plan: str,
    customer_email: str = "",
    existing_customer_id: str = "",
) -> dict:
    """
    Create a Stripe Checkout Session for a subscription upgrade.

    Returns:
        {"url": "https://checkout.stripe.com/...", "mock": False}  — Stripe configured
        {"url": "<paypal_fallback>", "mock": True}                 — Stripe not configured
        {"error": "..."}                                           — Stripe error
    """
    stripe = _client()
    price_id = get_price_id(plan)

    if not stripe or not price_id:
        logger.warning("Stripe not configured for plan %s — returning mock URL", plan)
        return {"url": "", "mock": True}

    try:
        params: dict = {
            "mode":       "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": (
                f"{settings.base_url}/c/{clinic_slug}"
                "?stripe=success&session_id={CHECKOUT_SESSION_ID}"
            ),
            "cancel_url": f"{settings.base_url}/c/{clinic_slug}?stripe=cancelled",
            "metadata": {
                "clinic_slug": clinic_slug,
                "plan":        plan,
            },
            "subscription_data": {
                "metadata": {"clinic_slug": clinic_slug, "plan": plan},
            },
            "allow_promotion_codes": True,
        }
        if existing_customer_id:
            params["customer"] = existing_customer_id
        elif customer_email:
            params["customer_email"] = customer_email

        session = stripe.checkout.Session.create(**params)
        logger.info("Stripe checkout session created: clinic=%s plan=%s", clinic_slug, plan)
        return {"url": session.url, "session_id": session.id, "mock": False}

    except Exception as exc:
        logger.exception("Stripe checkout error: clinic=%s plan=%s", clinic_slug, plan)
        return {"error": str(exc)}


# ── Customer Portal ───────────────────────────────────────────────────────────

def create_customer_portal_session(stripe_customer_id: str, return_url: str = "") -> dict:
    """
    Create a Stripe Billing Portal session so the clinic can:
    - Update their payment method
    - Download invoices
    - Cancel subscription

    Returns: {"url": "https://billing.stripe.com/..."} or {"error": "..."}
    """
    stripe = _client()
    if not stripe:
        return {"error": "Stripe not configured"}

    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url or settings.base_url,
        )
        return {"url": session.url}
    except Exception as exc:
        logger.exception("Stripe portal error: customer=%s", stripe_customer_id)
        return {"error": str(exc)}


# ── Subscription management ───────────────────────────────────────────────────

def get_subscription(subscription_id: str) -> Optional[dict]:
    """Fetch current subscription details from Stripe."""
    stripe = _client()
    if not stripe or not subscription_id:
        return None
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        return {
            "id":         sub.id,
            "status":     sub.status,
            "plan":       sub.metadata.get("plan", ""),
            "current_period_end": sub.current_period_end,
            "cancel_at_period_end": sub.cancel_at_period_end,
        }
    except Exception:
        logger.exception("Failed to retrieve subscription %s", subscription_id)
        return None


def cancel_subscription(subscription_id: str, immediately: bool = False) -> bool:
    """
    Cancel a Stripe subscription.
    immediately=False (default) → cancel at current period end (preferred).
    immediately=True → cancel right now and issue proration.
    """
    stripe = _client()
    if not stripe or not subscription_id:
        return False
    try:
        if immediately:
            stripe.Subscription.cancel(subscription_id)
        else:
            stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        logger.info("Subscription %s cancelled (immediately=%s)", subscription_id, immediately)
        return True
    except Exception:
        logger.exception("Failed to cancel subscription %s", subscription_id)
        return False


def reactivate_subscription(subscription_id: str) -> bool:
    """Re-enable a subscription that was set to cancel_at_period_end."""
    stripe = _client()
    if not stripe or not subscription_id:
        return False
    try:
        stripe.Subscription.modify(subscription_id, cancel_at_period_end=False)
        logger.info("Subscription %s reactivated", subscription_id)
        return True
    except Exception:
        logger.exception("Failed to reactivate subscription %s", subscription_id)
        return False


def update_subscription_plan(subscription_id: str, new_plan: str) -> bool:
    """Upgrade or downgrade a subscription to a different price (with proration)."""
    stripe = _client()
    new_price_id = get_price_id(new_plan)
    if not stripe or not subscription_id or not new_price_id:
        return False
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        item_id = sub["items"]["data"][0]["id"]
        stripe.Subscription.modify(
            subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
            metadata={"plan": new_plan},
            proration_behavior="create_prorations",
        )
        logger.info("Subscription %s updated to plan %s", subscription_id, new_plan)
        return True
    except Exception:
        logger.exception("Failed to update subscription %s to %s", subscription_id, new_plan)
        return False


# ── Webhook ───────────────────────────────────────────────────────────────────

def handle_webhook(payload: bytes, sig_header: str) -> Optional[dict]:
    """Validate and parse a Stripe webhook payload."""
    stripe = _client()
    if not stripe or not settings.stripe_webhook_secret:
        return None
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
        return event
    except Exception as exc:
        logger.error("Stripe webhook validation error: %s", exc)
        return None
