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
    },
    "professional": {
        "name":                "Professional",
        "price":               597,
        "conversations_limit": 1000,
        "sms":                 True,
        "widget_embed":        True,
        "custom_agent_name":   True,
        "white_label":         False,
        "max_locations":       3,
        "support":             "Priority email support",
        "color":               "#1E40AF",
    },
    "enterprise": {
        "name":                "Enterprise",
        "price":               997,
        "conversations_limit": None,      # unlimited
        "sms":                 True,
        "widget_embed":        True,
        "custom_agent_name":   True,
        "white_label":         True,
        "max_locations":       None,      # unlimited
        "support":             "Dedicated account manager + 24/7 priority",
        "color":               "#7C3AED",
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
