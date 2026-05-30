import json

handlers = []

def register_mock_handler(keywords, tool_code, tool_name, parameters, escalated=False):
    """Registers a new mock handler."""
    keywords = [k.lower() for k in keywords]
    handlers.append({
        "keywords": keywords,
        "tool_code": tool_code,
        "tool_name": tool_name,
        "parameters": parameters,
        "escalated": escalated
    })

# Registering handlers
register_mock_handler(
    keywords=["intake form", "pre-appointment questions", "pre-visit form"],
    tool_code="send_intake_form",
    tool_name="Send Intake Form",
    parameters={
        "patient_name": "John Doe"
    }
)
register_mock_handler(
    keywords=["appointment", "check"],
    tool_code="check_appointment_availability",
    tool_name="Check Appointment Availability",
    parameters={
        "time": "tomorrow",
        "date": "10/10/2024"
    }
)
register_mock_handler(
    keywords=["appointment", "book"],
    tool_code="book_appointment",
    tool_name="Book Appointment",
    parameters={
        "time": "10am",
        "date": "10/10/2024",
        "patient_name": "John Doe"
    }
)
register_mock_handler(
    keywords=["insurance"],
    tool_code="verify_insurance",
    tool_name="Verify Insurance",
    parameters={
        "patient_name": "John Doe"
    }
)
register_mock_handler(
    keywords=["balance", "bill", "pay"],
    tool_code="get_patient_balance",
    tool_name="Get Patient Balance",
    parameters={
        "patient_name": "John Doe"
    }
)
register_mock_handler(
    keywords=["payment link"],
    tool_code="send_payment_link",
    tool_name="Send Payment Link",
    parameters={
        "patient_name": "John Doe",
        "amount": "100.00"
    }
)
register_mock_handler(
    keywords=["escalate", "human agent", "representative"],
    tool_code="escalate_to_human",
    tool_name="Escalate to Human Agent",
    parameters={
        "reason": "The AI could not resolve the issue"
    },
    escalated=True
)

def mock_chat(messages: list[dict]) -> tuple[str, bool]:
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    last = user_msgs[-1].strip().lower() if user_msgs else ""

    # Emergency handling (highest priority)
    if "chest pain" in last or "left arm" in last:
        return (
            "Please call 911 immediately — chest pain with arm numbness are signs of a "
            "possible heart attack requiring emergency medical attention right away. "
            "Do not drive yourself. I'm alerting our team now.",
            True,
        )
    if ("can't swallow" in last or "cannot swallow" in last or "swollen" in last) and "swallow" in last:
        return (
            "This sounds like a medical emergency. Please call 911 or go to the nearest "
            "emergency room immediately — swelling that affects swallowing can be life-threatening. "
            "Do not wait for an appointment.",
            True,
        )
    
    for handler in handlers:
        if any(keyword in last for keyword in handler["keywords"]):
            response_json = json.dumps({
                "tool_code": handler["tool_code"],
                "tool_name": handler["tool_name"],
                "parameters": handler["parameters"]
            })
            return response_json, handler["escalated"]

    return json.dumps({"tool_code": "respond_with_json", "tool_name": "Respond with JSON", "parameters": {"response": f"AI response to: {last}"}}), False
