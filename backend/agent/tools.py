"""
Tool definitions (JSON schema) and dispatch for the Aria agent.
All tools are specialty-agnostic — appointment_type is a free-form string
so it adapts to any clinic config (dental, dermatology, family medicine, etc.).
"""
import logging
from typing import Any
from backend.mocks import pms, insurance, payments

logger = logging.getLogger(__name__)


def _notify_escalation(inputs: dict, clinic) -> None:
    """Send a real email alert when Aria escalates to a human."""
    try:
        from backend.services.email_svc import _build_msg, _send
        from backend.config import settings

        urgency      = inputs.get("urgency", "unknown").upper()
        reason       = inputs.get("reason", "No reason provided")
        patient_name = inputs.get("patient_name", "Unknown patient")
        summary      = inputs.get("summary", "")
        clinic_name  = getattr(clinic, "name", "Unknown clinic")
        clinic_phone = getattr(clinic, "phone", "")
        escalation_contact = getattr(clinic, "escalation_contact", "") or settings.notify_email

        subject = f"[{urgency}] Aria escalation — {clinic_name}: {reason[:60]}"
        plain   = "\n".join([
            f"Aria has escalated a patient conversation at {clinic_name}.",
            "",
            f"Urgency:      {urgency}",
            f"Reason:       {reason}",
            f"Patient:      {patient_name}",
            f"Clinic phone: {clinic_phone}",
            "",
            "Conversation summary:",
            summary or "(none provided)",
            "",
            "Please contact the patient immediately.",
            "— Tabor Synergy automated alert",
        ])
        html = f"""<html><body style="font-family:Arial,sans-serif;color:#333">
<div style="background:#DC2626;padding:16px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">⚠️ Patient Escalation — {urgency}</h2>
  <p style="color:#fecaca;margin:4px 0 0">{clinic_name}</p>
</div>
<div style="background:#FEF2F2;padding:20px;border:1px solid #FCA5A5;border-radius:0 0 8px 8px">
  <p><strong>Reason:</strong> {reason}</p>
  <p><strong>Patient:</strong> {patient_name}</p>
  <p><strong>Clinic Phone:</strong> {clinic_phone}</p>
  {f'<p><strong>Summary:</strong> {summary}</p>' if summary else ''}
  <p style="color:#991B1B;font-weight:700">Please contact the patient immediately.</p>
</div>
</body></html>"""
        msg = _build_msg(subject, plain, html)
        # Override recipient to escalation contact if set
        if escalation_contact and escalation_contact != settings.notify_email:
            msg.replace_header("To", escalation_contact)
        _send(msg)
    except Exception:
        logger.exception("escalate_to_human: failed to send email alert")

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
        "description": "Send a secure payment link to the patient via email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "amount":       {"type": "number"},
                "channel":      {"type": "string", "enum": ["email"]},
                "contact":      {"type": "string", "description": "Patient email address"},
            },
            "required": ["patient_name", "amount", "channel", "contact"],
        },
    },
    {
        "name": "send_intake_form",
        "description": "Send a new patient intake form package via a secure link by email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":  {"type": "string"},
                "channel":       {"type": "string", "enum": ["email"]},
                "patient_email": {"type": "string"},
            },
            "required": ["patient_name", "channel", "patient_email"],
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
    {
        "name": "lookup_patient_in_ehr",
        "description": (
            "Look up an existing patient in the clinic's EHR system by name and date of birth. "
            "Use this when a returning patient contacts the clinic and you need to confirm they are on file, "
            "retrieve their contact info, or pre-populate an intake form. "
            "Only call after the patient has provided their name and date of birth. "
            "Requires the clinic to have an EHR integration configured (Pro/Enterprise plans)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {
                    "type": "string",
                    "description": "Full name of the patient as they provided it.",
                },
                "date_of_birth": {
                    "type": "string",
                    "description": "Patient date of birth in YYYY-MM-DD format.",
                },
            },
            "required": ["patient_name", "date_of_birth"],
        },
    },
    {
        "name": "get_available_slots_from_ehr",
        "description": (
            "Fetch real-time open appointment slots directly from the clinic's EHR system. "
            "Use this instead of check_appointment_availability when the clinic has an EHR "
            "integration configured — it returns live slots from Epic/Cerner/Athenahealth "
            "rather than the local mock schedule. "
            "Requires Pro or Enterprise plan with EHR connected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_type": {
                    "type": "string",
                    "description": "Type of visit the patient needs (e.g. 'annual physical', 'follow-up', 'new patient').",
                },
                "date_start": {
                    "type": "string",
                    "description": "Earliest date to search for slots, YYYY-MM-DD. Defaults to tomorrow.",
                },
                "date_end": {
                    "type": "string",
                    "description": "Latest date to search, YYYY-MM-DD. Defaults to 7 days from date_start.",
                },
                "provider_name": {
                    "type": "string",
                    "description": "Filter by specific provider name, or omit for any available provider.",
                },
            },
            "required": ["appointment_type"],
        },
    },
    {
        "name": "get_clinic_analytics",
        "description": (
            "Get real-time analytics and reports for the clinic. "
            "Use this whenever a clinic admin or staff member asks about appointments, "
            "no-shows, provider workload, conversation usage, or recall campaign results. "
            "Always use this tool instead of guessing — it returns live data from the database."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": [
                        "today_appointments",
                        "weekly_summary",
                        "monthly_summary",
                        "no_shows",
                        "provider_breakdown",
                        "conversations",
                        "recall_performance",
                    ],
                    "description": (
                        "today_appointments — today's schedule with status breakdown; "
                        "weekly_summary — this week's appointment counts by day; "
                        "monthly_summary — month totals with KPIs; "
                        "no_shows — recent no-show patients for follow-up; "
                        "provider_breakdown — appointments per provider this month; "
                        "conversations — AI chat session usage vs. plan limit; "
                        "recall_performance — recall campaign send/book/opt-out stats."
                    ),
                },
            },
            "required": ["report_type"],
        },
    },
]


async def dispatch_tool(
    name: str,
    inputs: dict[str, Any],
    clinic=None,
    db=None,
    session_id: str = "",
    channel: str = "web",
) -> dict[str, Any]:
    """Route tool calls to the appropriate service."""
    from backend.services.appointment_svc import (
        generate_slots, book_appointment, reschedule_appointment,
        cancel_appointment, add_to_waitlist,
    )

    match name:
        case "check_appointment_availability":
            slots = generate_slots(
                clinic=clinic,
                date_start=inputs.get("date_range_start"),
                date_end=inputs.get("date_range_end"),
                duration_minutes=inputs.get("duration_minutes", 30),
                db=db,
                provider_filter=inputs.get("provider"),
            )
            return {"available_slots": slots, "appointment_type": inputs.get("appointment_type", "")}

        case "book_appointment":
            return book_appointment(
                clinic=clinic,
                db=db,
                session_id=session_id,
                channel=channel,
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
            return reschedule_appointment(
                clinic=clinic,
                db=db,
                patient_name=inputs["patient_name"],
                new_datetime=inputs["new_datetime"],
                patient_dob=inputs.get("patient_dob"),
                current_appointment_date=inputs.get("current_appointment_date"),
                reason=inputs.get("reason"),
            )

        case "cancel_appointment":
            return cancel_appointment(
                clinic=clinic,
                db=db,
                patient_name=inputs["patient_name"],
                appointment_date=inputs["appointment_date"],
                patient_dob=inputs.get("patient_dob"),
                reason=inputs.get("reason"),
            )

        case "verify_insurance":
            return insurance.verify_insurance(**inputs)

        case "get_patient_balance":
            return pms.get_patient_balance(**inputs)

        case "send_payment_link":
            return payments.send_payment_link(**inputs)

        case "send_intake_form":
            return payments.send_intake_form(**inputs)

        case "add_to_waitlist":
            return add_to_waitlist(
                clinic=clinic,
                db=db,
                patient_name=inputs["patient_name"],
                patient_phone=inputs["patient_phone"],
                appointment_type=inputs["appointment_type"],
                preferred_provider=inputs.get("preferred_provider"),
                earliest_available=inputs.get("earliest_available"),
            )
        case "lookup_patient_in_ehr":
            from backend.plans import can_use_ehr_integration
            if not can_use_ehr_integration(clinic):
                return {
                    "error": "EHR integration is available on Professional and Enterprise plans only.",
                    "found": False,
                }
            from backend.services.ehr_svc import lookup_patient
            patient = lookup_patient(
                clinic_id=clinic.id,
                patient_name=inputs["patient_name"],
                date_of_birth=inputs["date_of_birth"],
                db=db,
            )
            if patient:
                return {"found": True, "patient": patient}
            return {
                "found": False,
                "message": f"No patient record found for {inputs['patient_name']} (DOB {inputs['date_of_birth']}) in the EHR.",
            }

        case "get_available_slots_from_ehr":
            from backend.plans import can_use_ehr_integration
            if not can_use_ehr_integration(clinic):
                return {
                    "error": "EHR integration is available on Professional and Enterprise plans only.",
                    "slots": [],
                }
            from datetime import date, timedelta
            from backend.services.ehr_svc import get_available_slots
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            date_start = inputs.get("date_start") or tomorrow
            date_end   = inputs.get("date_end") or (
                date.fromisoformat(date_start) + timedelta(days=7)
            ).isoformat()
            slots = get_available_slots(
                clinic_id=clinic.id,
                appointment_type=inputs["appointment_type"],
                date_start=date_start,
                date_end=date_end,
                provider_name=inputs.get("provider_name"),
                db=db,
            )
            if slots:
                return {"slots": slots, "count": len(slots)}
            return {
                "slots": [],
                "message": "No open slots found in the EHR for the requested date range. Try a wider range or check back later.",
            }

        case "escalate_to_human":
            _notify_escalation(inputs, clinic)
            return {
                "escalated":     True,
                "reason":        inputs["reason"],
                "urgency":       inputs["urgency"],
                "staff_alerted": True,
                "message":       "Staff has been notified and will join the conversation shortly.",
            }

        case "get_clinic_analytics":
            from backend.services.analytics_svc import (
                get_today_appointments, get_weekly_summary, get_monthly_summary,
                get_no_shows, get_provider_breakdown, get_conversation_stats,
                get_recall_performance, format_for_aria,
            )
            report_type = inputs.get("report_type", "today_appointments")
            if not db or not clinic:
                return {"error": "Analytics requires a database connection."}

            dispatch_map = {
                "today_appointments": lambda: get_today_appointments(db, clinic.id),
                "weekly_summary":     lambda: get_weekly_summary(db, clinic.id),
                "monthly_summary":    lambda: get_monthly_summary(db, clinic.id),
                "no_shows":           lambda: get_no_shows(db, clinic.id),
                "provider_breakdown": lambda: get_provider_breakdown(db, clinic.id),
                "conversations":      lambda: get_conversation_stats(db, clinic.id, clinic),
                "recall_performance": lambda: get_recall_performance(db, clinic.id),
            }
            fn = dispatch_map.get(report_type)
            if not fn:
                return {"error": f"Unknown report_type: {report_type}"}

            data    = fn()
            summary = format_for_aria(report_type, data)
            return {"report_type": report_type, "summary": summary, "data": data}

        case _:
            return {"error": f"Unknown tool: {name}"}
