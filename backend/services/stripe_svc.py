"""
Stripe billing service.
Falls back to mock mode if STRIPE_SECRET_KEY is not configured.
"""
import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)
_stripe = None

def _client():
    global _stripe
    if _stripe is None and settings.stripe_secret_key:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        _stripe = stripe
    return _stripe


def create_checkout_session(clinic_slug: str, clinic_name: str,
                             customer_email: str = "") -> dict:
    stripe = _client()
    if not stripe or not settings.stripe_price_id:
        mock_url = f"{settings.base_url}/admin?checkout=mock&clinic={clinic_slug}"
        logger.warning("Stripe not configured — returning mock checkout URL")
        return {"url": mock_url, "mock": True}

    try:
        params = {
            "mode": "subscription",
            "line_items": [{"price": settings.stripe_price_id, "quantity": 1}],
            "success_url": f"{settings.base_url}/admin?checkout=success&clinic={clinic_slug}",
            "cancel_url":  f"{settings.base_url}/admin?checkout=cancelled&clinic={clinic_slug}",
            "metadata":    {"clinic_slug": clinic_slug},
            "subscription_data": {"metadata": {"clinic_slug": clinic_slug}},
        }
        if customer_email:
            params["customer_email"] = customer_email

        session = stripe.checkout.Session.create(**params)
        return {"url": session.url, "mock": False}
    except Exception as exc:
        logger.exception("Stripe checkout error")
        return {"error": str(exc)}


def handle_webhook(payload: bytes, sig_header: str) -> Optional[dict]:
    stripe = _client()
    if not stripe or not settings.stripe_webhook_secret:
        return None

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
        return event
    except Exception as exc:
        logger.error("Stripe webhook error: %s", exc)
        return None


def cancel_subscription(subscription_id: str) -> bool:
    stripe = _client()
    if not stripe or not subscription_id:
        return False
    try:
        stripe.Subscription.cancel(subscription_id)
        return True
    except Exception:
        logger.exception("Stripe cancel error")
        return False
