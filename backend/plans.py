"""
Plan definitions and feature-gate helpers.
Single source of truth — import from here everywhere.
"""

PLANS = {
    "starter": {
        "name":                "Starter",
        "price":               297,
        "conversations_limit": 300,       # per month; None = unlimited
        "sms":                 False,
        "widget_embed":        False,
        "custom_agent_name":   False,
        "white_label":         False,
        "max_locations":       1,
        "support":             "Email support",
        "color":               "#6B7280",
        "coming_soon":         [],
    },
    "professional": {
        "name":                "Professional",
        "price":               597,
        "conversations_limit": 1000,
        "sms":                 True,
        "whatsapp":            True,
        "widget_embed":        True,
        "custom_agent_name":   True,
        "white_label":         False,
        "max_locations":       3,
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
        "sms":                 True,
        "whatsapp":            True,
        "widget_embed":        True,
        "custom_agent_name":   True,
        "white_label":         True,
        "max_locations":       None,      # unlimited
        "monthly_reports":     True,
        "custom_insurance":    True,
        "support":             "Dedicated account manager + 24/7 priority",
        "color":               "#7C3AED",
        "coming_soon":         ["ehr_system_integration", "custom_ai_training"],
    },
}

PLAN_RATES = {k: float(v["price"]) for k, v in PLANS.items()}


def get_plan(clinic) -> dict:
    """Return the plan dict for a clinic, defaulting to professional."""
    key = (getattr(clinic, "plan", None) or "professional").lower()
    return PLANS.get(key, PLANS["professional"])


def can_use_sms(clinic) -> bool:
    return get_plan(clinic)["sms"]


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


def can_use_whatsapp(clinic) -> bool:
    """Check if clinic plan supports WhatsApp messaging."""
    return get_plan(clinic).get("whatsapp", False)


def can_use_monthly_reports(clinic) -> bool:
    """Check if clinic plan supports monthly performance reports."""
    return get_plan(clinic).get("monthly_reports", False)


def can_use_custom_insurance(clinic) -> bool:
    """Check if clinic plan supports custom insurance knowledge."""
    return get_plan(clinic).get("custom_insurance", False)
