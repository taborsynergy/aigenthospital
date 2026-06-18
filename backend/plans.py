"""
Plan definitions and feature-gate helpers.
Single source of truth — import from here everywhere.
"""
from datetime import datetime


PLANS = {
    "starter": {
        "name":                "Starter",
        "price":               297,
        "conversations_limit": 300,       # per month; None = unlimited
        "reminders":           False,     # email reminders + recall (Growth+)
        "widget_embed":        False,
        "custom_agent_name":   False,
        "white_label":         False,
        "max_locations":       1,
        "max_providers":       1,         # Solo practice only
        "support":             "Email support",
        "color":               "#6B7280",
        "coming_soon":         [],
    },
    "professional": {
        "name":                "Professional",
        "price":               597,
        "conversations_limit": 1000,
        "reminders":           True,      # email reminders + recall
        "widget_embed":        True,
        "custom_agent_name":   True,
        "white_label":         False,
        "max_locations":       3,
        "max_providers":       5,         # Growth: 2-5 doctors
        "monthly_reports":     True,
        "custom_insurance":    True,
        "support":             "Priority email support",
        "color":               "#1E40AF",
        "coming_soon":         [],
    },
    "enterprise": {
        "name":                "Enterprise",
        "price":               997,
        "conversations_limit": None,      # unlimited
        "reminders":           True,      # email reminders + recall
        "widget_embed":        True,
        "custom_agent_name":   True,
        "white_label":         True,
        "max_locations":       None,      # unlimited
        "max_providers":       None,      # unlimited
        "monthly_reports":     True,
        "custom_insurance":    True,
        "location_routing":    True,
        "ehr_integration":     True,
        "custom_ai_training":  True,
        "support":             "Dedicated account manager + 24/7 priority",
        "color":               "#7C3AED",
        "coming_soon":         [],
    },
}

PLAN_RATES = {k: float(v["price"]) for k, v in PLANS.items()}


def get_plan(clinic) -> dict:
    """Return the plan dict for a clinic, defaulting to professional."""
    key = (getattr(clinic, "plan", None) or "professional").lower()
    return PLANS.get(key, PLANS["professional"])


def can_use_reminders(clinic) -> bool:
    """Email appointment reminders + recall campaigns — Growth and Enterprise plans."""
    return get_plan(clinic).get("reminders", False)


def can_embed_widget(clinic) -> bool:
    return get_plan(clinic)["widget_embed"]


def can_customize_agent_name(clinic) -> bool:
    return get_plan(clinic)["custom_agent_name"]


def is_white_label(clinic) -> bool:
    return get_plan(clinic)["white_label"]


def monthly_conversation_limit(clinic) -> int | None:
    return get_plan(clinic)["conversations_limit"]


def get_coming_soon_features(clinic) -> list[str]:
    """Get list of features coming soon for this plan."""
    return get_plan(clinic).get("coming_soon", [])


def is_feature_coming_soon(clinic, feature: str) -> bool:
    """Check if a specific feature is coming soon for this plan."""
    return feature in get_coming_soon_features(clinic)


def can_use_monthly_reports(clinic) -> bool:
    """Check if clinic plan supports monthly performance reports."""
    return get_plan(clinic).get("monthly_reports", False)


def can_use_custom_insurance(clinic) -> bool:
    """Check if clinic plan supports custom insurance knowledge."""
    return get_plan(clinic).get("custom_insurance", False)


def can_use_location_routing(clinic) -> bool:
    """Check if clinic plan supports multi-location intelligent routing."""
    return get_plan(clinic).get("location_routing", False)


def can_use_ehr_integration(clinic) -> bool:
    """Check if clinic plan supports EHR system integration."""
    return get_plan(clinic).get("ehr_integration", False)


def can_use_custom_ai_training(clinic) -> bool:
    """Check if clinic plan supports custom AI training."""
    return get_plan(clinic).get("custom_ai_training", False)


def max_providers(clinic) -> int | None:
    """Get max number of providers allowed on clinic's plan. None = unlimited."""
    return get_plan(clinic).get("max_providers", 1)


def can_add_provider(clinic, current_provider_count: int) -> bool:
    """Check if clinic can add another provider based on plan limit."""
    limit = max_providers(clinic)
    if limit is None:
        return True  # Unlimited
    return current_provider_count < limit


def can_use_dedicated_onboarding(clinic) -> bool:
    """Check if clinic plan supports dedicated onboarding (Pro+ only)."""
    plan = get_plan(clinic)
    # Pro/Enterprise have dedicated onboarding, Starter/Growth do not
    return plan.get("name") in ["Enterprise"]  # For now, Enterprise only


def can_use_custom_branding(clinic) -> bool:
    """Check if clinic can customize branding (colors, logo, etc)."""
    return is_white_label(clinic)


def can_use_custom_domain(clinic) -> bool:
    """Check if clinic can map custom domain."""
    return is_white_label(clinic)


def can_access_source_code(clinic) -> bool:
    """Check if clinic can access source code for self-hosting."""
    return is_white_label(clinic)


def can_enable_reselling(clinic) -> bool:
    """Check if clinic can create and manage sub-clinics (reseller)."""
    return is_white_label(clinic)


def can_self_host(clinic) -> bool:
    """Check if clinic can self-host on own infrastructure."""
    return is_white_label(clinic)


def is_clinic_active(clinic) -> bool:
    """
    Check if a clinic can access the platform.
    Active if: (trial active) OR (paid subscription active).
    """
    # Check trial status
    if clinic.subscription_status == "trial":
        if clinic.trial_ends_at and datetime.utcnow() < clinic.trial_ends_at:
            return True
        return False

    # Check paid subscription status
    if clinic.subscription_status == "active":
        if clinic.subscription_ends_at:
            return datetime.utcnow() < clinic.subscription_ends_at
        return True

    return False


def get_access_status(clinic) -> dict:
    """Return detailed access status for a clinic."""
    if clinic.subscription_status == "trial":
        if clinic.trial_ends_at:
            if datetime.utcnow() < clinic.trial_ends_at:
                days_left = (clinic.trial_ends_at - datetime.utcnow()).days + 1
                return {
                    "active": True,
                    "status": "trial",
                    "days_remaining": days_left,
                    "message": f"Trial active ({days_left} days remaining)"
                }
            return {
                "active": False,
                "status": "trial_expired",
                "message": "Trial has expired"
            }
        return {"active": False, "status": "trial_no_date", "message": "Trial date not set"}

    if clinic.subscription_status == "active":
        if clinic.subscription_ends_at:
            if datetime.utcnow() < clinic.subscription_ends_at:
                days_left = (clinic.subscription_ends_at - datetime.utcnow()).days + 1
                return {
                    "active": True,
                    "status": "paid_active",
                    "days_remaining": days_left,
                    "message": f"Subscription active ({days_left} days remaining)"
                }
            return {
                "active": False,
                "status": "subscription_expired",
                "message": "Subscription has expired"
            }
        return {"active": True, "status": "paid_active", "message": "Subscription active (no end date)"}

    if clinic.subscription_status == "past_due":
        return {
            "active": False,
            "status": "past_due",
            "message": "Payment failed, please update payment method"
        }

    if clinic.subscription_status == "trial_expired":
        return {
            "active": False,
            "status": "trial_expired",
            "message": "Trial expired, please upgrade to continue"
        }

    return {
        "active": False,
        "status": "unknown",
        "message": "Unknown subscription status"
    }
