"""
Tool definitions (JSON schema) and dispatch for the Aria agent.
All tools are specialty-agnostic — appointment_type is a free-form string
so it adapts to any clinic config (dental, dermatology, family medicine, etc.).
"""
from typing import Any
from backend.mocks import pms, insurance, payments

TOOLS: list[dict] = [
    {
        "name": "check_appointment_availability",
        "description": (
            "Check available appointment slots in the practice schedule. "
            "Use this before booking to show the patient real options."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_type": {
                    "type": "string",
                    "description": (
                        "Type of visit in lay terms appropriate to the specialty "
                        "(e.g. 'annual physical', 'sick visit', 'skin check', 'cleaning', "
                        "'follow-up', 'new patient consultation')."
                    ),
                },
                "date_range_start": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD. Defaults to tomorrow if omitted.",
                },
                "date_range_end": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD. Defaults to 7 days from start if omitted.",
                },
                "provider": {
                    "type": "string",
                    "description": "Provider name or 'any'.",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Desired appointment length in minutes.",
                },
            },
            "required": ["appointment_type"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Confirm and book an appointment for a patient after they have selected a slot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":    {"type": "string"},
                "appointment_type": {"type": "string"},
                "datetime":        {"type": "string", "description": "Human-readable, e.g. 'Monday, May 12 at 10:00 AM'"},
                "provider":        {"type": "string"},
                "patient_phone":   {"type": "string"},
                "patient_email":   {"type": "string"},
                "patient_dob":     {"type": "string", "description": "YYYY-MM-DD"},
                "is_new_patient":  {"type": "boolean"},
                "chief_complaint": {"type": "string", "description": "Reason for visit in lay terms"},
            },
            "required": ["patient_name", "appointment_type", "datetime"],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": "Move an existing patient appointment to a new date/time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":            {"type": "string"},
                "patient_dob":             {"type": "string"},
                "current_appointment_date": {"type": "string"},
                "new_datetime":            {"type": "string"},
                "reason":                  {"type": "string"},
            },
            "required": ["patient_name", "new_datetime"],
        },
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel an existing appointment and communicate the cancellation policy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":     {"type": "string"},
                "appointment_date": {"type": "string"},
                "patient_dob":      {"type": "string"},
                "reason":           {"type": "string"},
            },
            "required": ["patient_name", "appointment_date"],
        },
    },
    {
        "name": "verify_insurance",
        "description": "Verify a patient's insurance coverage and explain benefits in plain language.",
        "input_schema": {
            "type": "object",
            "properties": {
                "insurance_company":   {"type": "string"},
                "member_id":           {"type": "string"},
                "group_number":        {"type": "string"},
                "patient_dob":         {"type": "string"},
                "policy_holder_name":  {"type": "string"},
                "procedure_type":      {"type": "string", "description": "Procedure or visit type to estimate coverage for"},
            },
            "required": ["insurance_company", "member_id"],
        },
    },
    {
        "name": "get_patient_balance",
        "description": (
            "Look up a patient's current account balance. "
            "Only call after verifying identity (name + DOB + SSN last 4 or address)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":    {"type": "string"},
                "patient_dob":     {"type": "string", "description": "YYYY-MM-DD"},
                "last_four_ssn":   {"type": "string"},
                "patient_address": {"type": "string"},
            },
            "required": ["patient_name", "patient_dob"],
        },
    },
    {
        "name": "send_payment_link",
        "description": "Send a secure payment link to the patient via SMS or email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "amount":       {"type": "number"},
                "channel":      {"type": "string", "enum": ["sms", "email"]},
                "contact":      {"type": "string", "description": "Phone number or email address"},
            },
            "required": ["patient_name", "amount", "channel", "contact"],
        },
    },
    {
        "name": "send_intake_form",
        "description": "Send a new patient intake form package via a secure link (SMS or email).",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":  {"type": "string"},
                "channel":       {"type": "string", "enum": ["sms", "email"]},
                "patient_email": {"type": "string"},
                "patient_phone": {"type": "string"},
            },
            "required": ["patient_name", "channel"],
        },
    },
    {
        "name": "add_to_waitlist",
        "description": "Add a patient to the next-available or same-day waitlist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":       {"type": "string"},
                "patient_phone":      {"type": "string"},
                "appointment_type":   {"type": "string"},
                "preferred_provider": {"type": "string"},
                "earliest_available": {"type": "string"},
            },
            "required": ["patient_name", "patient_phone", "appointment_type"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalate this conversation to a human staff member. "
            "Use for emergencies, distressed patients, billing disputes >$150, "
            "legal or HIPAA issues, or any clinical question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason":       {"type": "string"},
                "urgency":      {"type": "string", "enum": ["low", "medium", "high", "emergency"]},
                "patient_name": {"type": "string"},
                "summary":      {"type": "string", "description": "Brief summary of the conversation so far"},
            },
            "required": ["reason", "urgency"],
        },
    },
]


async def dispatch_tool(name: str, inputs: dict[str, Any], clinic=None) -> dict[str, Any]:
    """Route tool calls to the appropriate mock service."""
    match name:
        case "check_appointment_availability":
            return pms.check_availability(clinic=clinic, **inputs)
        case "book_appointment":
            return pms.book_appointment(
                clinic=clinic,
                patient_name=inputs["patient_name"],
                appointment_type=inputs["appointment_type"],
                datetime_str=inputs["datetime"],
                provider=inputs.get("provider"),
                patient_phone=inputs.get("patient_phone"),
                patient_email=inputs.get("patient_email"),
                patient_dob=inputs.get("patient_dob"),
                is_new_patient=inputs.get("is_new_patient", False),
                chief_complaint=inputs.get("chief_complaint"),
            )
        case "reschedule_appointment":
            return pms.reschedule_appointment(clinic=clinic, **inputs)
        case "cancel_appointment":
            return pms.cancel_appointment(clinic=clinic, **inputs)
        case "verify_insurance":
            return insurance.verify_insurance(**inputs)
        case "get_patient_balance":
            return pms.get_patient_balance(**inputs)
        case "send_payment_link":
            return payments.send_payment_link(**inputs)
        case "send_intake_form":
            return payments.send_intake_form(**inputs)
        case "add_to_waitlist":
            return pms.add_to_waitlist(**inputs)
        case "escalate_to_human":
            return {
                "escalated": True,
                "reason": inputs["reason"],
                "urgency": inputs["urgency"],
                "staff_alerted": True,
                "message": "Staff has been notified and will join the conversation shortly.",
            }
        case _:
            return {"error": f"Unknown tool: {name}"}
