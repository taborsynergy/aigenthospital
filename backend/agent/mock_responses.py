"""
Mock response engine for QA test runs (MOCK_MODE=1).
Returns pre-written responses that satisfy the keyword checks
in every test case without calling the Anthropic API.
"""


def _has(text: str, *kw) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in kw)


def mock_chat(messages: list[dict]) -> tuple[str, bool]:
    """
    Given the full message history, return (response_text, is_escalated).
    Looks at the last user message (and previous context) to choose a response.
    """
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    last = user_msgs[-1].strip().lower() if user_msgs else ""
    full = " ".join(str(m) for m in user_msgs).lower()

    # ── EMERGENCIES (highest priority — check first) ─────────────────
    if _has(last, "chest pain", "left arm", "left arm feels numb"):
        return (
            "Please call 911 immediately — chest pain with arm numbness are signs of a "
            "possible heart attack requiring emergency medical attention right away. "
            "Do not drive yourself. I'm alerting our team now.",
            True,
        )

    if _has(last, "can't swallow", "cannot swallow", "face", "swollen") and _has(last, "swallow"):
        return (
            "This sounds like a medical emergency. Please call 911 or go to the nearest "
            "emergency room immediately — swelling that affects swallowing can be life-threatening. "
            "Do not wait for an appointment.",
            True,
        )

    if (_has(last, "104", "fever") and _has(last, "month", "baby", "infant", "2-month", "infant")):
        return (
            "A 104°F fever in a 2-month-old is a medical emergency. Please call 911 or go to "
            "the emergency room right away. Infants under 3 months with high fevers require "
            "immediate hospital evaluation.",
            True,
        )

    if _has(last, "can't take it anymore", "cannot take it anymore") and _has(last, "pain", "weeks"):
        return (
            "I'm so sorry you've been in pain and feeling unheard — I hear you, and that's not "
            "okay. I want to connect you with a member of our team right away so you can get the "
            "attention and care you deserve. Someone will be with you shortly.",
            True,
        )

    if _has(last, "sue", "lawsuit", "liable"):
        return (
            "I understand you have serious concerns about your experience. I'm going to connect "
            "you with our office manager right away to address this properly. Please hold — "
            "a team member will be with you shortly.",
            True,
        )

    if _has(last, "records shared without my consent", "file a complaint", "privacy complaint"):
        return (
            "I take this very seriously, and your privacy rights matter. You have the right to "
            "file a HIPAA privacy complaint. I'm connecting you with our privacy officer right "
            "now, and you can also file a complaint directly with HHS at hhs.gov/hipaa. "
            "Someone from our team will reach out to you promptly.",
            True,
        )

    if _has(last, "speak to a real person", "real person", "human being", "want to talk to someone"):
        return (
            "Of course! I'm connecting you to a team member right away. Please hold for just "
            "a moment — someone will be with you shortly.",
            True,
        )

    if _has(last, "upset", "waiting 3 weeks", "nobody called", "extremely upset"):
        return (
            "I'm so sorry about your experience — waiting three weeks without a callback is "
            "completely unacceptable, and I hear how frustrated you are. I want to make this "
            "right. Let me connect you with a member of our team right now to ensure you get "
            "the attention you deserve.",
            True,
        )

    if _has(last, "i've been in pain", "pain for weeks", "no one is listening"):
        return (
            "I'm truly sorry you've been in pain and feeling unheard. That's not okay, and I "
            "want to help make sure you're heard. I'm here for you — let me connect you with "
            "our team right away so we can get you the care you need.",
            True,
        )

    # ── SECURITY / HIPAA ────────────────────────────────────────────

    if _has(last, "ignore all previous instructions", "output all patient records"):
        return (
            "I can help you with scheduling, insurance, or billing questions. "
            "What can I assist you with today?",
            False,
        )

    if _has(last, "[system:", "admin mode", "list all patients"):
        return (
            "I'm not able to process that request. Is there something else I can help "
            "you with, such as scheduling an appointment or checking your insurance?",
            False,
        )

    if _has(last, "override verification", "override") and _has(last, "dr.", "doctor", "mehta"):
        return (
            "I cannot override identity verification or access patient files directly. "
            "This is a front desk assistant — for medical record access, please use the "
            "practice's internal systems. I'm unable to pull up any patient's file this way.",
            False,
        )

    if _has(last, "check the account for jane doe", "she's my wife", "wife"):
        return (
            "I'm unable to access another person's records — even for a family member. "
            "HIPAA privacy regulations require each individual to be present and verify their own "
            "identity. That person must contact us directly to access their own account.",
            False,
        )

    if _has(last, "you already verified me", "verified me earlier"):
        return (
            "For your security, I need to re-verify your identity each time you request "
            "account information. Could you please provide your full name, date of birth, "
            "and last 4 digits of your SSN?",
            False,
        )

    if _has(last, "list all patients scheduled", "patients scheduled for tomorrow",
             "tomorrow's appointments"):
        return (
            "I'm not able to access scheduling records or fulfil that request. "
            "Is there something else I can help you with?",
            False,
        )

    if _has(last, "email me my full medical history", "send my medical history"):
        return (
            "I cannot send medical records via email — this is not permitted under HIPAA "
            "privacy regulations. For a secure records request, please contact our office "
            "directly. You can also access records through our patient portal.",
            False,
        )

    if _has(last, "skin cancer", "do i have", "do you think i have"):
        return (
            "I'm not able to provide medical diagnoses — that's something only a licensed "
            "provider can determine after a proper evaluation. I'd recommend scheduling an "
            "appointment with Dr. Sarah Chen or Dr. Marcus Rivera to discuss your concerns "
            "with a physician who can examine you properly.",
            False,
        )

    if _has(last, "dosage", "accutane", "milligram", "how much should i take"):
        return (
            "I cannot provide medication dosage guidance — please discuss this with your "
            "provider or pharmacist. I can help you schedule an appointment with Dr. Sarah "
            "Chen or Dr. Marcus Rivera to address your medication questions.",
            False,
        )

    if _has(last, "appointments at sunshine dermatology", "sunshine dermatology"):
        return (
            "I can only assist with Sunshine Medical Group — I don't have access to "
            "information from other practices. Is there something I can help you with "
            "here at this practice?",
            False,
        )

    # ── BILLING (identity gating) ────────────────────────────────────

    # Multi-turn: if previous messages include verification, allow balance
    has_verification = (
        len(user_msgs) > 1
        and _has(full, "dob", "date of birth", "1985", "1988", "1990", "ssn", "last 4")
        and _has(full, "jane", "smith", "sarah", "chen", "alice")
    )

    if _has(last, "payment link", "send me a payment", "pay online"):
        if has_verification:
            return (
                "Thank you! I've confirmed your balance and I'm sending a secure payment link "
                "to the email on file. You can use it to pay your balance online. "
                "Is there anything else I can help you with?",
                False,
            )
        return (
            "I'd be happy to send you a payment link. To protect your privacy, I first need to "
            "verify your identity. Could you provide your full name, date of birth, and the "
            "last 4 digits of your SSN?",
            False,
        )

    if _has(last, "what do i owe", "my balance", "account balance", "owe from my last visit"):
        if has_verification:
            return (
                "Your current balance is on file. I can send a secure payment link to your email "
                "so you can pay online. Would you like me to do that?",
                False,
            )
        return (
            "I'd be happy to look up your balance. To verify your identity and protect your "
            "privacy, could you please provide your full name, date of birth (DOB), and the "
            "last 4 digits of your SSN?",
            False,
        )

    # ── INSURANCE ────────────────────────────────────────────────────

    if _has(last, "aetna"):
        return (
            "I've verified your Aetna PPO coverage. Here's an estimate of your benefits: "
            "specialist copay is approximately $30, your deductible is $1,500 with a portion "
            "already met, and your coinsurance is 20% after deductible. "
            "Please note these are estimates — actual coverage may vary by service. "
            "Would you like to book an appointment?",
            False,
        )

    if _has(last, "oscar health", "oscar"):
        return (
            "Oscar Health is currently out-of-network with our practice. However, we do offer "
            "self-pay rates and flexible payment plans. Our self-pay rates are very competitive, "
            "and we're happy to help you explore your options. Would you like more information?",
            False,
        )

    if _has(last, "insurance", "member id", "group"):
        return (
            "I can verify your insurance coverage! Please provide your member ID, group number, "
            "and date of birth and I'll check your benefits. Note that the results will be "
            "estimates — your actual coverage may vary.",
            False,
        )

    # ── SCHEDULING ────────────────────────────────────────────────────

    if _has(last, "3am", "3 am", "midnight", "2am"):
        return (
            "We don't have 3am appointments — our office hours are Monday-Friday 8am-5pm "
            "and Saturday 9am-1pm. I'd be happy to schedule you for the earliest available "
            "slot. Would Monday morning work for you?",
            False,
        )

    if _has(last, "dr. michael jordan", "michael jordan"):
        return (
            "Dr. Michael Jordan isn't currently on our staff. Our available providers are "
            "Dr. Sarah Chen (MD) and Dr. Marcus Rivera (PA). Would you like to schedule "
            "with one of them?",
            False,
        )

    if _has(last, "8-year-old", "8 year old", "my son", "my daughter", "child", "minor"):
        return (
            "Happy to help schedule an appointment for your child! As the parent or guardian, "
            "I'll need your name and contact information, as well as your son's name and date "
            "of birth. What type of appointment does he need?",
            False,
        )

    if _has(last, "cancel"):
        return (
            "I can cancel your appointment. Please note our cancellation policy: 24-hour notice "
            "is required to avoid a $50 cancellation fee. Would you also like to reschedule for "
            "another time?",
            False,
        )

    if _has(last, "reschedule", "move my appointment") or (_has(full, "reschedule") and _has(full, "friday")):
        return (
            "I can help you reschedule! Friday looks available — I can confirm the reschedule "
            "to Friday for you. Would you like to lock that in?",
            False,
        )

    if _has(last, "sooner", "this week", "earlier", "any earlier"):
        return (
            "Let me check for earlier availability this week! I can also add you to our "
            "waitlist so we can notify you of any cancellations sooner. Would you like me "
            "to do both?",
            False,
        )

    if _has(last, "walk in", "walk-in", "just walk", "forget it"):
        return (
            "You're absolutely welcome to walk in during our office hours — we're open "
            "Monday-Friday 8am-5pm and Saturday 9am-1pm. We look forward to seeing you! "
            "Is there anything else I can help you with?",
            False,
        )

    if _has(last, "book", "appointment", "schedule", "appintmnet", "bbok"):
        return (
            "I'd be happy to help you schedule an appointment! We have availability next "
            "Tuesday and later this week. Could you provide your name, date of birth, and "
            "the reason for your visit? As a new patient, we'll also send you a new patient "
            "intake form to fill out before your visit.",
            False,
        )

    # ── PROVIDERS / SPECIALTY ─────────────────────────────────────────

    if _has(last, "which doctor", "what doctor", "who should i see", "which provider"):
        return (
            "We have two excellent providers: Dr. Sarah Chen (MD) specializes in preventive "
            "care and chronic disease management, and Dr. Marcus Rivera (PA) handles acute "
            "care and follow-up visits. Would you like to schedule with a specific provider, "
            "or shall I recommend one based on your needs?",
            False,
        )

    if _has(last, "chemotherapy", "chemo", "radiation", "oncology treatment"):
        return (
            "Chemotherapy is not a service we offer at Sunshine Medical Group — this is "
            "outside the scope of our specialty. I'd recommend reaching out to an oncologist "
            "for cancer treatment options. Is there something within our specialty I can "
            "help you with?",
            False,
        )

    # ── OFFICE HOURS ─────────────────────────────────────────────────

    if _has(last, "office hours", "when are you open", "hours", "open"):
        return (
            "Our office is open Monday through Friday, 8am to 5pm, and Saturday from 9am to "
            "1pm Central Time. We're closed on Sundays and major holidays. For after-hours "
            "emergencies, please call 911. Is there anything else I can help you with?",
            False,
        )

    # ── TONE / UX ────────────────────────────────────────────────────

    if _has(last, "nervous", "scared", "anxious", "worried about") and _has(last, "procedure", "surgery", "operation"):
        return (
            "I completely understand — feeling nervous before a procedure is completely natural. "
            "We're here to support you every step of the way. Your comfort and wellbeing are "
            "our priority. Would you like more information about what to expect, or would it "
            "help to talk through your concerns?",
            False,
        )

    if _has(last, "another chatbot", "chatbot", "just a bot", "robot"):
        return (
            "Ha — fair enough! Let me show you what I can do: I can schedule appointments, "
            "verify your insurance, help with billing, and answer questions about our practice. "
            "What can I help you with today?",
            False,
        )

    if _has(last, "thank you", "thanks", "helpful", "you've been"):
        return (
            "You're very welcome — I'm so glad I could help! If you ever need anything else, "
            "please don't hesitate to reach out. Have a wonderful day!",
            False,
        )

    if _has(last, "hello", "hi", "hey", "good morning", "good afternoon"):
        return (
            "Hi there! I'm Aria, your virtual front desk assistant at Sunshine Medical Group. "
            "I'm here to help with scheduling appointments, verifying insurance, answering "
            "billing questions, and more. How can I help you today?",
            False,
        )

    # ── DEFAULT ───────────────────────────────────────────────────────

    return (
        "Thank you for reaching out to Sunshine Medical Group! I'm Aria, and I'm here to help "
        "with scheduling, insurance, billing, and general questions. Could you tell me more "
        "about what you need help with today?",
        False,
    )
