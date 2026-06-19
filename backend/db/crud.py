import json
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.models import (
    Clinic, UsageLog, SmsConversation, Appointment, ChatSession, AuditLog,
    RecallCampaign, RecallLog, Location, WidgetConfig, InsuranceKnowledge,
    EHRConfiguration, CustomAITraining, Provider, OnboardingSession,
    WhitelabelConfig,
)

_TOKEN_TTL_DAYS = 30
_MAX_LOGIN_FAILURES = 10
_LOCKOUT_MINUTES = 30


# ── Clinics ──────────────────────────────────────────────────────────────────

def get_clinic(db: Session, slug: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.slug == slug, Clinic.is_active.is_(True)).first()


def get_clinic_by_id(db: Session, clinic_id: int) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.id == clinic_id).first()


def get_clinic_by_twilio_number(db: Session, phone: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.twilio_phone == phone, Clinic.is_active.is_(True)).first()



def get_clinic_by_email(db: Session, email: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(
        func.lower(Clinic.email) == email.lower().strip(),
        Clinic.is_active.is_(True),
    ).first()


def create_trial_clinic(db: Session, email: str, slug: str, name: str, specialty: str,
                        password_hash: str) -> Optional[Clinic]:
    """Create a new trial clinic (14-day free trial on Starter plan)."""
    # Verify email not already used
    if get_clinic_by_email(db, email):
        return None

    # Verify slug not already used
    if get_clinic(db, slug):
        return None

    clinic = Clinic(
        slug=slug.lower(),
        email=email.lower().strip(),
        name=name.strip(),
        specialty=specialty.strip(),
        plan="starter",
        subscription_status="trial",
        customer_password_hash=password_hash,
        is_active=True,
        trial_ends_at=datetime.utcnow() + timedelta(days=14),
        subscription_ends_at=None,  # No paid subscription yet
        monthly_rate=297.0,  # Starter plan rate
    )
    db.add(clinic)
    db.commit()
    db.refresh(clinic)
    return clinic


def get_clinic_by_token(db: Session, token: str) -> Optional[Clinic]:
    if not token:
        return None
    clinic = db.query(Clinic).filter(
        Clinic.session_token == token,
        Clinic.is_active.is_(True),
    ).first()
    if not clinic:
        return None
    # Honour token expiry when set
    if clinic.token_expires_at and datetime.utcnow() > clinic.token_expires_at:
        clinic.session_token = ""
        clinic.token_expires_at = None
        db.commit()
        return None
    return clinic


def set_session_token(db: Session, clinic_id: int, token: str) -> None:
    clinic = get_clinic_by_id(db, clinic_id)
    if clinic:
        clinic.session_token = token
        clinic.token_expires_at = (
            datetime.utcnow() + timedelta(days=_TOKEN_TTL_DAYS) if token else None
        )
        db.commit()


def record_failed_login(db: Session, clinic: Clinic) -> int:
    """Increment failure counter; lock account after threshold. Returns attempt count."""
    clinic.failed_login_attempts = (clinic.failed_login_attempts or 0) + 1
    if clinic.failed_login_attempts >= _MAX_LOGIN_FAILURES:
        clinic.locked_until = datetime.utcnow() + timedelta(minutes=_LOCKOUT_MINUTES)
    db.commit()
    return clinic.failed_login_attempts


def reset_failed_logins(db: Session, clinic: Clinic) -> None:
    clinic.failed_login_attempts = 0
    clinic.locked_until = None
    db.commit()


def list_clinics(db: Session) -> list[Clinic]:
    return db.query(Clinic).filter(Clinic.is_active.is_(True)).order_by(Clinic.created_at.desc()).all()


def create_clinic(db: Session, data: dict) -> Clinic:
    if "trial_ends_at" not in data:
        data = {**data, "trial_ends_at": datetime.utcnow() + timedelta(days=14)}
    clinic = Clinic(**data)
    db.add(clinic)
    db.commit()
    db.refresh(clinic)
    return clinic


def update_clinic(db: Session, slug: str, data: dict) -> Optional[Clinic]:
    clinic = get_clinic(db, slug)
    if not clinic:
        return None
    for k, v in data.items():
        setattr(clinic, k, v)
    db.commit()
    db.refresh(clinic)
    return clinic


def change_plan(db: Session, slug: str, new_plan: str) -> Optional[Clinic]:
    """
    Switch a clinic's plan tier (upgrade OR downgrade) and sync monthly_rate from
    PLAN_RATES. Feature gating follows clinic.plan automatically, so every tier
    combination is honored immediately. Caller must validate new_plan first.
    Returns the updated clinic, or None if the clinic doesn't exist.
    """
    from backend.plans import PLAN_RATES
    clinic = get_clinic(db, slug)
    if not clinic:
        return None
    clinic.plan = new_plan
    clinic.monthly_rate = PLAN_RATES[new_plan]
    db.commit()
    db.refresh(clinic)
    return clinic


def activate_subscription(db: Session, slug: str) -> Optional[Clinic]:
    clinic = get_clinic(db, slug)
    if not clinic:
        return None
    now = datetime.utcnow()
    # Idempotency guard: if the clinic is already active with a nearly-full month
    # remaining, treat this as an accidental double-activation (e.g. admin double
    # click) and do NOT stack another 30 days. Real monthly renewals call this when
    # the period is near/after expiry, so they still extend correctly.
    if (clinic.subscription_status == "active"
            and clinic.subscription_ends_at
            and clinic.subscription_ends_at > now + timedelta(days=29)):
        return clinic
    clinic.subscription_status = "active"
    base = clinic.subscription_ends_at if (clinic.subscription_ends_at and clinic.subscription_ends_at > now) else now
    clinic.subscription_ends_at = base + timedelta(days=30)
    clinic.renewal_reminder_day = None  # re-arm renewal reminders for the new cycle
    if not clinic.activated_at:
        clinic.activated_at = now
    db.commit()
    db.refresh(clinic)
    return clinic


def update_notes(db: Session, slug: str, notes: str) -> Optional[Clinic]:
    clinic = get_clinic(db, slug)
    if not clinic:
        return None
    clinic.admin_notes = notes
    db.commit()
    db.refresh(clinic)
    return clinic


def deactivate_clinic(db: Session, slug: str) -> bool:
    clinic = get_clinic(db, slug)
    if not clinic:
        return False
    clinic.is_active = False
    db.commit()
    return True


def purge_clinic(db: Session, slug: str) -> bool:
    """
    Permanently delete a clinic and ALL its data (right-to-be-forgotten / GDPR/HIPAA
    data minimization). Irreversible — use deactivate_clinic for the normal reversible
    soft-delete.

    Child rows are deleted explicitly by clinic_id rather than relying on ON DELETE
    CASCADE: Postgres enforces the FK cascade, but SQLite does not enable foreign-key
    enforcement by default, which would otherwise leave orphaned PHI behind. Explicit
    deletion guarantees no orphans on either engine and auto-covers new child tables.
    """
    from backend.db.database import Base
    clinic = get_clinic(db, slug)
    if not clinic:
        return False
    cid = clinic.id
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if cls is Clinic:
            continue
        if hasattr(cls, "clinic_id"):
            db.query(cls).filter(cls.clinic_id == cid).delete(synchronize_session=False)
    db.delete(clinic)
    db.commit()
    return True


# ── Appointments ─────────────────────────────────────────────────────────────

def create_appointment(db: Session, data: dict) -> Appointment:
    appt = Appointment(**data)
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


def list_appointments(db: Session, clinic_id: int, limit: int = 200) -> list[Appointment]:
    return (
        db.query(Appointment)
        .filter(Appointment.clinic_id == clinic_id)
        .order_by(Appointment.created_at.desc())
        .limit(limit)
        .all()
    )


def get_appointment_by_confirmation(db: Session, confirmation_number: str, clinic_id: int) -> Optional[Appointment]:
    return db.query(Appointment).filter(
        Appointment.confirmation_number == confirmation_number,
        Appointment.clinic_id == clinic_id,
    ).first()


def update_appointment_status(db: Session, confirmation_number: str, status: str) -> Optional[Appointment]:
    appt = db.query(Appointment).filter(Appointment.confirmation_number == confirmation_number).first()
    if appt:
        appt.status = status
        db.commit()
        db.refresh(appt)
    return appt


def update_appointment(db: Session, confirmation_number: str, data: dict) -> Optional[Appointment]:
    """Update arbitrary fields on an appointment by confirmation number."""
    appt = db.query(Appointment).filter(Appointment.confirmation_number == confirmation_number).first()
    if appt:
        for k, v in data.items():
            setattr(appt, k, v)
        db.commit()
        db.refresh(appt)
    return appt


def find_appointment_by_patient(
    db: Session,
    clinic_id: int,
    patient_name: str,
    patient_dob: Optional[str] = None,
    date_hint: Optional[str] = None,
    status: Optional[str] = None,
) -> Optional[Appointment]:
    """
    Find the most recent appointment for a patient by name (case-insensitive partial match).
    Optionally filters by status and narrows by date_hint or DOB.
    """
    q = (
        db.query(Appointment)
        .filter(
            Appointment.clinic_id == clinic_id,
            func.lower(Appointment.patient_name).contains(patient_name.lower().strip()),
        )
    )
    if status:
        q = q.filter(Appointment.status == status)
    if patient_dob:
        q = q.filter(Appointment.patient_dob == patient_dob)
    if date_hint:
        q = q.filter(Appointment.appointment_datetime.ilike(f"%{date_hint}%"))
    return q.order_by(Appointment.created_at.desc()).first()


def list_appointments_by_status(
    db: Session, clinic_id: int, status: str, limit: int = 100
) -> list[Appointment]:
    return (
        db.query(Appointment)
        .filter(Appointment.clinic_id == clinic_id, Appointment.status == status)
        .order_by(Appointment.appointment_ts.asc())
        .limit(limit)
        .all()
    )


# ── Chat sessions (persistent) ────────────────────────────────────────────────

def get_chat_history(db: Session, clinic_id: int, session_id: str) -> list[dict]:
    row = db.query(ChatSession).filter(
        ChatSession.clinic_id == clinic_id,
        ChatSession.session_id == session_id,
    ).first()
    if not row:
        return []
    try:
        return json.loads(row.history)
    except Exception:
        return []


def save_chat_history(db: Session, clinic_id: int, session_id: str,
                      history: list[dict], channel: str = "web") -> None:
    row = db.query(ChatSession).filter(
        ChatSession.clinic_id == clinic_id,
        ChatSession.session_id == session_id,
    ).first()
    serialized = json.dumps(history)
    now = datetime.utcnow()
    if row:
        row.history = serialized
        row.last_active = now
    else:
        db.add(ChatSession(
            clinic_id=clinic_id,
            session_id=session_id,
            history=serialized,
            channel=channel,
            last_active=now,
        ))
    db.commit()


def delete_chat_session(db: Session, clinic_id: int, session_id: str) -> None:
    db.query(ChatSession).filter(
        ChatSession.clinic_id == clinic_id,
        ChatSession.session_id == session_id,
    ).delete()
    db.commit()


def purge_old_chat_sessions(db: Session, older_than_hours: int = 48) -> int:
    """Remove sessions inactive for longer than `older_than_hours`. Returns count deleted."""
    cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
    count = db.query(ChatSession).filter(ChatSession.last_active < cutoff).delete()
    db.commit()
    return count


# ── Usage logs ────────────────────────────────────────────────────────────────

def log_usage(db: Session, clinic_id: int, session_id: str,
              channel: str, input_tokens: int, output_tokens: int) -> None:
    entry = UsageLog(
        clinic_id=clinic_id,
        session_id=session_id,
        channel=channel,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(entry)
    db.commit()


def get_usage_summary(db: Session, clinic_id: int) -> dict:
    rows = (
        db.query(
            func.count(UsageLog.id).label("messages"),
            func.sum(UsageLog.input_tokens).label("input_tokens"),
            func.sum(UsageLog.output_tokens).label("output_tokens"),
        )
        .filter(UsageLog.clinic_id == clinic_id)
        .first()
    )
    return {
        "messages":      rows.messages      or 0,
        "input_tokens":  rows.input_tokens  or 0,
        "output_tokens": rows.output_tokens or 0,
    }


def get_usage_this_month(db: Session, clinic_id: int) -> int:
    from sqlalchemy import extract
    now = datetime.utcnow()
    count = (
        db.query(func.count(func.distinct(UsageLog.session_id)))
        .filter(
            UsageLog.clinic_id == clinic_id,
            extract("year",  UsageLog.created_at) == now.year,
            extract("month", UsageLog.created_at) == now.month,
        )
        .scalar()
    )
    return count or 0


def get_all_monthly_sessions(db: Session) -> dict:
    from sqlalchemy import extract
    now = datetime.utcnow()
    rows = (
        db.query(
            UsageLog.clinic_id,
            func.count(func.distinct(UsageLog.session_id)).label("sessions"),
        )
        .filter(
            extract("year",  UsageLog.created_at) == now.year,
            extract("month", UsageLog.created_at) == now.month,
        )
        .group_by(UsageLog.clinic_id)
        .all()
    )
    return {r.clinic_id: r.sessions for r in rows}


def get_all_usage_summary(db: Session) -> list[dict]:
    rows = (
        db.query(
            UsageLog.clinic_id,
            func.count(UsageLog.id).label("messages"),
            func.sum(UsageLog.input_tokens + UsageLog.output_tokens).label("tokens"),
        )
        .group_by(UsageLog.clinic_id)
        .all()
    )
    return [{"clinic_id": r.clinic_id, "messages": r.messages, "tokens": r.tokens or 0} for r in rows]


# ── SMS conversations ─────────────────────────────────────────────────────────

def get_or_create_sms_session(db: Session, clinic_id: int, patient_phone: str) -> str:
    import uuid
    conv = (
        db.query(SmsConversation)
        .filter(SmsConversation.clinic_id == clinic_id, SmsConversation.patient_phone == patient_phone)
        .first()
    )
    if conv:
        conv.last_message_at = datetime.utcnow()
        db.commit()
        return conv.session_id

    session_id = f"sms_{uuid.uuid4().hex[:12]}"
    conv = SmsConversation(clinic_id=clinic_id, patient_phone=patient_phone, session_id=session_id)
    db.add(conv)
    db.commit()
    return session_id


def list_sms_conversations(db: Session, clinic_id: int) -> list[SmsConversation]:
    return (
        db.query(SmsConversation)
        .filter(SmsConversation.clinic_id == clinic_id)
        .order_by(SmsConversation.last_message_at.desc())
        .limit(100)
        .all()
    )


# ── Audit log ─────────────────────────────────────────────────────────────────

def write_audit_log(db: Session, actor: str, action: str,
                    target: str = "", detail: str = "", ip: str = "") -> None:
    entry = AuditLog(actor=actor, action=action, target=target, detail=detail, ip_address=ip)
    db.add(entry)
    try:
        db.commit()
    except Exception:
        db.rollback()   # audit failure must never break the main request


# ── Recall campaigns ──────────────────────────────────────────────────────────

def list_recall_campaigns(db: Session, clinic_id: int) -> list[RecallCampaign]:
    return (
        db.query(RecallCampaign)
        .filter(RecallCampaign.clinic_id == clinic_id)
        .order_by(RecallCampaign.created_at.desc())
        .all()
    )


def get_recall_campaign(db: Session, campaign_id: int, clinic_id: int) -> Optional[RecallCampaign]:
    return db.query(RecallCampaign).filter(
        RecallCampaign.id == campaign_id,
        RecallCampaign.clinic_id == clinic_id,
    ).first()


def create_recall_campaign(db: Session, data: dict) -> RecallCampaign:
    campaign = RecallCampaign(**data)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def update_recall_campaign(db: Session, campaign_id: int, clinic_id: int, data: dict) -> Optional[RecallCampaign]:
    campaign = get_recall_campaign(db, campaign_id, clinic_id)
    if not campaign:
        return None
    for k, v in data.items():
        setattr(campaign, k, v)
    db.commit()
    db.refresh(campaign)
    return campaign


def delete_recall_campaign(db: Session, campaign_id: int, clinic_id: int) -> bool:
    campaign = get_recall_campaign(db, campaign_id, clinic_id)
    if not campaign:
        return False
    db.delete(campaign)
    db.commit()
    return True


# ── Recall logs ───────────────────────────────────────────────────────────────

def log_recall_sent(db: Session, campaign_id: int, clinic_id: int,
                    patient_name: str, patient_phone: str, status: str = "sent") -> RecallLog:
    entry = RecallLog(
        campaign_id=campaign_id, clinic_id=clinic_id,
        patient_name=patient_name, patient_phone=patient_phone,
        status=status,
    )
    db.add(entry)
    db.commit()
    return entry


def get_recall_log(db: Session, clinic_id: int, patient_phone: str,
                   since: datetime) -> list[RecallLog]:
    """Return recall logs for a patient since a given datetime."""
    return (
        db.query(RecallLog)
        .filter(
            RecallLog.clinic_id == clinic_id,
            RecallLog.patient_phone == patient_phone,
            RecallLog.sent_at >= since,
        )
        .all()
    )


def mark_recall_opted_out(db: Session, clinic_id: int, patient_phone: str) -> int:
    """
    Mark all recall logs for a patient as opted_out.
    If no prior recall logs exist, creates an opt-out marker so future
    campaigns also respect the opt-out.
    Returns count of records affected.
    """
    count = (
        db.query(RecallLog)
        .filter(RecallLog.clinic_id == clinic_id, RecallLog.patient_phone == patient_phone)
        .update({"status": "opted_out"})
    )
    if count == 0:
        # Create a standalone opt-out marker (no campaign)
        db.add(RecallLog(
            campaign_id=None,
            clinic_id=clinic_id,
            patient_name="",
            patient_phone=patient_phone,
            status="opted_out",
        ))
        count = 1
    db.commit()
    return count


def is_opted_out(db: Session, clinic_id: int, patient_phone: str) -> bool:
    """Check if a patient has opted out of recall messages for this clinic."""
    return db.query(RecallLog).filter(
        RecallLog.clinic_id == clinic_id,
        RecallLog.patient_phone == patient_phone,
        RecallLog.status == "opted_out",
    ).first() is not None


def get_recall_stats(db: Session, campaign_id: int) -> dict:
    rows = (
        db.query(RecallLog.status, func.count(RecallLog.id).label("count"))
        .filter(RecallLog.campaign_id == campaign_id)
        .group_by(RecallLog.status)
        .all()
    )
    stats = {r.status: r.count for r in rows}
    return {
        "sent":      stats.get("sent", 0),
        "failed":    stats.get("failed", 0),
        "opted_out": stats.get("opted_out", 0),
        "booked":    stats.get("booked", 0),
        "total":     sum(stats.values()),
    }


def find_patients_due_for_recall(db: Session, clinic_id: int,
                                  interval_months: int) -> list[dict]:
    """
    Return patients whose last completed/scheduled appointment was more than
    interval_months ago and who have an EMAIL on file (recall is email-based).
    Returns list of dicts with patient_name, patient_email, last_visit_ts.
    """
    cutoff = datetime.utcnow() - timedelta(days=interval_months * 30)

    rows = (
        db.query(
            Appointment.patient_name,
            Appointment.patient_email,
            func.max(Appointment.appointment_ts).label("last_visit"),
        )
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.status.in_(["scheduled", "confirmed", "completed", "rescheduled"]),
            Appointment.patient_email != "",
            Appointment.patient_email.isnot(None),
            Appointment.appointment_ts.isnot(None),
        )
        .group_by(Appointment.patient_name, Appointment.patient_email)
        .having(func.max(Appointment.appointment_ts) < cutoff)
        .all()
    )
    return [
        {
            "patient_name":  r.patient_name,
            "patient_email": r.patient_email,
            "last_visit_ts": r.last_visit,
        }
        for r in rows
    ]


# ── Locations (multi-office support) ──────────────────────────────────────────

def list_locations(db: Session, clinic_id: int) -> list[Location]:
    """All locations for a clinic, active first."""
    return (
        db.query(Location)
        .filter(Location.clinic_id == clinic_id)
        .order_by(Location.is_active.desc(), Location.name.asc())
        .all()
    )


def get_location(db: Session, location_id: int, clinic_id: int) -> Optional[Location]:
    """Get a specific location (must belong to this clinic)."""
    return db.query(Location).filter(
        Location.id == location_id,
        Location.clinic_id == clinic_id,
    ).first()


def create_location(db: Session, data: dict) -> Location:
    """Create a new location for a clinic."""
    location = Location(**data)
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def update_location(db: Session, location_id: int, clinic_id: int, data: dict) -> Optional[Location]:
    """Update a location."""
    location = get_location(db, location_id, clinic_id)
    if not location:
        return None
    for k, v in data.items():
        setattr(location, k, v)
    db.commit()
    db.refresh(location)
    return location


def delete_location(db: Session, location_id: int, clinic_id: int) -> bool:
    """Soft-delete a location (sets is_active=False)."""
    location = get_location(db, location_id, clinic_id)
    if not location:
        return False
    location.is_active = False
    db.commit()
    return True


def get_location_by_name(db: Session, clinic_id: int, name: str) -> Optional[Location]:
    """Find a location by clinic + name."""
    return db.query(Location).filter(
        Location.clinic_id == clinic_id,
        Location.name == name,
        Location.is_active.is_(True),
    ).first()


def set_primary_location(db: Session, clinic_id: int, location_id: int) -> Optional[Location]:
    """Set a location as primary (default) for the clinic."""
    # Unset all other primary locations
    db.query(Location).filter(
        Location.clinic_id == clinic_id,
        Location.is_primary.is_(True),
    ).update({"is_primary": False})

    # Set this location as primary
    location = get_location(db, location_id, clinic_id)
    if location:
        location.is_primary = True
        db.commit()
        db.refresh(location)
    return location


# ── Widget Config ──────────────────────────────────────────────────────────────

def get_widget_config(db: Session, clinic_id: int) -> Optional[WidgetConfig]:
    """Get widget customization for a clinic."""
    return db.query(WidgetConfig).filter(WidgetConfig.clinic_id == clinic_id).first()


def create_widget_config(db: Session, clinic_id: int, data: dict) -> WidgetConfig:
    """Create widget config for a clinic."""
    config = WidgetConfig(clinic_id=clinic_id, **data)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_widget_config(db: Session, clinic_id: int, data: dict) -> Optional[WidgetConfig]:
    """Update widget config for a clinic."""
    config = get_widget_config(db, clinic_id)
    if not config:
        return None
    for k, v in data.items():
        setattr(config, k, v)
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config


def get_or_create_widget_config(db: Session, clinic_id: int) -> WidgetConfig:
    """Get existing widget config or create one with defaults."""
    config = get_widget_config(db, clinic_id)
    if config:
        return config
    return create_widget_config(db, clinic_id, {})


# ── Insurance Knowledge ──────────────────────────────────────────────────────

def get_insurance_knowledge(db: Session, clinic_id: int) -> InsuranceKnowledge | None:
    """Get custom insurance knowledge for a clinic."""
    return db.query(InsuranceKnowledge).filter(InsuranceKnowledge.clinic_id == clinic_id).first()


def create_insurance_knowledge(db: Session, clinic_id: int, data: dict) -> InsuranceKnowledge:
    """Create insurance knowledge for a clinic."""
    knowledge = InsuranceKnowledge(clinic_id=clinic_id, **data)
    db.add(knowledge)
    db.commit()
    db.refresh(knowledge)
    return knowledge


def update_insurance_knowledge(db: Session, clinic_id: int, data: dict) -> InsuranceKnowledge | None:
    """Update insurance knowledge for a clinic."""
    knowledge = get_insurance_knowledge(db, clinic_id)
    if not knowledge:
        return None
    for k, v in data.items():
        setattr(knowledge, k, v)
    knowledge.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(knowledge)
    return knowledge


def get_or_create_insurance_knowledge(db: Session, clinic_id: int) -> InsuranceKnowledge:
    """Get or create insurance knowledge (with defaults)."""
    knowledge = get_insurance_knowledge(db, clinic_id)
    if knowledge:
        return knowledge
    return create_insurance_knowledge(db, clinic_id, {})


# ── EHR Configuration ────────────────────────────────────────────────────────

def get_ehr_configuration(db: Session, clinic_id: int) -> EHRConfiguration | None:
    """Get EHR configuration for a clinic."""
    return db.query(EHRConfiguration).filter(EHRConfiguration.clinic_id == clinic_id).first()


def create_ehr_configuration(db: Session, clinic_id: int, data: dict) -> EHRConfiguration:
    """Create EHR configuration for a clinic."""
    config = EHRConfiguration(clinic_id=clinic_id, **data)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_ehr_configuration(db: Session, clinic_id: int, data: dict) -> EHRConfiguration | None:
    """Update EHR configuration for a clinic."""
    config = get_ehr_configuration(db, clinic_id)
    if not config:
        return None
    for k, v in data.items():
        setattr(config, k, v)
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config


def get_or_create_ehr_configuration(db: Session, clinic_id: int) -> EHRConfiguration:
    """Get or create EHR configuration (with defaults)."""
    config = get_ehr_configuration(db, clinic_id)
    if config:
        return config
    return create_ehr_configuration(db, clinic_id, {})


# ── Custom AI Training ──────────────────────────────────────────────────────

def list_custom_ai_training(db: Session, clinic_id: int) -> list[CustomAITraining]:
    """Get all training items for a clinic, sorted by priority descending."""
    return (
        db.query(CustomAITraining)
        .filter(CustomAITraining.clinic_id == clinic_id)
        .order_by(CustomAITraining.priority.desc(), CustomAITraining.created_at.desc())
        .all()
    )


def get_custom_ai_training(db: Session, training_id: int, clinic_id: int) -> CustomAITraining | None:
    """Get a specific training item (must belong to this clinic)."""
    return db.query(CustomAITraining).filter(
        CustomAITraining.id == training_id,
        CustomAITraining.clinic_id == clinic_id,
    ).first()


def create_custom_ai_training(db: Session, clinic_id: int, data: dict) -> CustomAITraining:
    """Create a new training item for a clinic."""
    training = CustomAITraining(clinic_id=clinic_id, **data)
    db.add(training)
    db.commit()
    db.refresh(training)
    return training


def update_custom_ai_training(db: Session, training_id: int, clinic_id: int, data: dict) -> CustomAITraining | None:
    """Update a training item."""
    training = get_custom_ai_training(db, training_id, clinic_id)
    if not training:
        return None
    for k, v in data.items():
        setattr(training, k, v)
    training.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(training)
    return training


def delete_custom_ai_training(db: Session, training_id: int, clinic_id: int) -> bool:
    """Delete a training item."""
    training = get_custom_ai_training(db, training_id, clinic_id)
    if not training:
        return False
    db.delete(training)
    db.commit()
    return True


def get_active_training_context(db: Session, clinic_id: int) -> str:
    """
    Get all active training items for a clinic formatted as context for the AI agent.
    Returns a single formatted string suitable for system prompt injection.
    """
    items = db.query(CustomAITraining).filter(
        CustomAITraining.clinic_id == clinic_id,
        CustomAITraining.is_active.is_(True),
    ).order_by(CustomAITraining.priority.desc()).all()

    if not items:
        return ""

    context_parts = []
    for item in items:
        context_parts.append(f"[{item.training_type.upper()}] {item.title}\n{item.content}")

    return "\n\n".join(context_parts)


# ── Trial Management ──────────────────────────────────────────────────────────

def is_trial_active(clinic: Clinic) -> bool:
    """Check if a clinic is in active trial (subscription_status='trial' and not expired)."""
    if clinic.subscription_status != "trial":
        return False
    if not clinic.trial_ends_at:
        return False
    return datetime.utcnow() < clinic.trial_ends_at


def is_subscription_active(clinic: Clinic) -> bool:
    """Check if a clinic has an active paid subscription."""
    if clinic.subscription_status == "active":
        if clinic.subscription_ends_at:
            return datetime.utcnow() < clinic.subscription_ends_at
        return True
    return False


def can_access_clinic(clinic: Clinic) -> bool:
    """Check if a clinic can be accessed (trial active OR subscription active)."""
    return is_trial_active(clinic) or is_subscription_active(clinic)


def get_trials_expiring_soon(db: Session, days_until: int = 5) -> list[Clinic]:
    """Get all trial clinics expiring within N days."""
    cutoff = datetime.utcnow() + timedelta(days=days_until)
    return db.query(Clinic).filter(
        Clinic.subscription_status == "trial",
        Clinic.trial_ends_at.isnot(None),
        Clinic.trial_ends_at <= cutoff,
        Clinic.trial_ends_at > datetime.utcnow(),  # Not already expired
    ).all()


def get_active_subscriptions_ending_soon(db: Session, days_until: int = 7) -> list[Clinic]:
    """Active (paid) clinics whose subscription_ends_at is within N days."""
    cutoff = datetime.utcnow() + timedelta(days=days_until)
    return db.query(Clinic).filter(
        Clinic.subscription_status == "active",
        Clinic.subscription_ends_at.isnot(None),
        Clinic.subscription_ends_at <= cutoff,
        Clinic.subscription_ends_at > datetime.utcnow(),  # Not already lapsed
    ).all()


def get_expired_trials(db: Session) -> list[Clinic]:
    """Get all trial clinics that have expired."""
    return db.query(Clinic).filter(
        Clinic.subscription_status == "trial",
        Clinic.trial_ends_at.isnot(None),
        Clinic.trial_ends_at <= datetime.utcnow(),
    ).all()


def expire_trial(db: Session, clinic_id: int) -> Optional[Clinic]:
    """Mark a trial clinic as expired."""
    clinic = get_clinic_by_id(db, clinic_id)
    if clinic and clinic.subscription_status == "trial":
        clinic.subscription_status = "trial_expired"
        db.commit()
        db.refresh(clinic)
    return clinic


def convert_trial_to_paid(db: Session, clinic_id: int, plan: str = "starter") -> Optional[Clinic]:
    """Convert a trial clinic to paid subscription (PayPal-confirmed by admin)."""
    clinic = get_clinic_by_id(db, clinic_id)
    if not clinic:
        return None

    clinic.subscription_status = "active"
    clinic.plan = plan
    clinic.subscription_ends_at = datetime.utcnow() + timedelta(days=30)
    clinic.trial_ends_at = None  # Clear trial
    clinic.renewal_reminder_day = None  # arm renewal reminders for this cycle

    db.commit()
    db.refresh(clinic)
    return clinic


# ── Provider Management (Multi-Doctor) ────────────────────────────────────────

def list_providers(db: Session, clinic_id: int) -> list[Provider]:
    """List all active providers for a clinic."""
    return db.query(Provider).filter(
        Provider.clinic_id == clinic_id,
        Provider.is_active.is_(True),
    ).order_by(Provider.created_at.asc()).all()


def get_provider(db: Session, provider_id: int, clinic_id: int) -> Optional[Provider]:
    """Get a specific provider (with clinic isolation)."""
    return db.query(Provider).filter(
        Provider.id == provider_id,
        Provider.clinic_id == clinic_id,
    ).first()


def create_provider(db: Session, clinic_id: int, data: dict) -> Optional[Provider]:
    """Create a new provider for a clinic."""
    provider = Provider(
        clinic_id=clinic_id,
        name=data.get("name", "").strip(),
        email=(data.get("email") or "").lower().strip(),
        phone=data.get("phone", "").strip(),
        specialty=data.get("specialty", "").strip(),
        license_number=data.get("license_number", "").strip(),
        npi_number=data.get("npi_number", "").strip(),
        bio=data.get("bio", "").strip(),
        photo_url=data.get("photo_url", "").strip(),
        is_active=True,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


def update_provider(db: Session, provider_id: int, clinic_id: int,
                   data: dict) -> Optional[Provider]:
    """Update a provider (with clinic isolation)."""
    provider = get_provider(db, provider_id, clinic_id)
    if not provider:
        return None

    if "name" in data:
        provider.name = data["name"].strip()
    if "email" in data:
        provider.email = (data["email"] or "").lower().strip()
    if "phone" in data:
        provider.phone = data["phone"].strip()
    if "specialty" in data:
        provider.specialty = data["specialty"].strip()
    if "license_number" in data:
        provider.license_number = data["license_number"].strip()
    if "npi_number" in data:
        provider.npi_number = data["npi_number"].strip()
    if "bio" in data:
        provider.bio = data["bio"].strip()
    if "photo_url" in data:
        provider.photo_url = data["photo_url"].strip()
    if "is_active" in data:
        provider.is_active = bool(data["is_active"])

    db.commit()
    db.refresh(provider)
    return provider


def deactivate_provider(db: Session, provider_id: int, clinic_id: int) -> bool:
    """Deactivate a provider (soft delete)."""
    provider = get_provider(db, provider_id, clinic_id)
    if not provider:
        return False

    provider.is_active = False
    db.commit()
    return True


def count_active_providers(db: Session, clinic_id: int) -> int:
    """Count active providers for a clinic."""
    return db.query(Provider).filter(
        Provider.clinic_id == clinic_id,
        Provider.is_active.is_(True),
    ).count()


# ── Onboarding Sessions (Pro+ Feature) ──────────────────────────────────────

def get_onboarding_session(db: Session, session_id: int, clinic_id: int) -> Optional[OnboardingSession]:
    """Get a specific onboarding session (with clinic isolation)."""
    return db.query(OnboardingSession).filter(
        OnboardingSession.id == session_id,
        OnboardingSession.clinic_id == clinic_id,
    ).first()


def get_clinic_onboarding_session(db: Session, clinic_id: int) -> Optional[OnboardingSession]:
    """Get current/latest onboarding session for a clinic."""
    return db.query(OnboardingSession).filter(
        OnboardingSession.clinic_id == clinic_id,
    ).order_by(OnboardingSession.created_at.desc()).first()


def create_onboarding_session(db: Session, clinic_id: int, data: dict) -> Optional[OnboardingSession]:
    """Create a new onboarding session for a clinic."""
    session = OnboardingSession(
        clinic_id=clinic_id,
        contact_name=data.get("contact_name", "").strip(),
        contact_email=(data.get("contact_email") or "").lower().strip(),
        contact_phone=data.get("contact_phone", "").strip(),
        status="pending",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def update_onboarding_session(db: Session, session_id: int, clinic_id: int,
                            data: dict) -> Optional[OnboardingSession]:
    """Update an onboarding session (with clinic isolation)."""
    session = get_onboarding_session(db, session_id, clinic_id)
    if not session:
        return None

    if "contact_name" in data:
        session.contact_name = data["contact_name"].strip()
    if "contact_email" in data:
        session.contact_email = (data["contact_email"] or "").lower().strip()
    if "contact_phone" in data:
        session.contact_phone = data["contact_phone"].strip()
    if "status" in data:
        session.status = data["status"]
    if "scheduled_at" in data and data["scheduled_at"]:
        session.scheduled_at = data["scheduled_at"]
    if "completed_at" in data and data["completed_at"]:
        session.completed_at = data["completed_at"]
    if "meeting_link" in data:
        session.meeting_link = data["meeting_link"].strip()
    if "meeting_platform" in data:
        session.meeting_platform = data["meeting_platform"].strip()
    if "duration_minutes" in data:
        session.duration_minutes = int(data["duration_minutes"]) if data["duration_minutes"] else 60
    if "notes" in data:
        session.notes = data["notes"].strip()
    if "topics_covered" in data:
        session.topics_covered = data["topics_covered"]

    db.commit()
    db.refresh(session)
    return session


def mark_onboarding_completed(db: Session, session_id: int, clinic_id: int) -> Optional[OnboardingSession]:
    """Mark onboarding session as completed."""
    session = get_onboarding_session(db, session_id, clinic_id)
    if not session:
        return None

    session.status = "completed"
    session.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return session


def cancel_onboarding_session(db: Session, session_id: int, clinic_id: int) -> Optional[OnboardingSession]:
    """Cancel an onboarding session."""
    session = get_onboarding_session(db, session_id, clinic_id)
    if not session:
        return None

    session.status = "cancelled"
    db.commit()
    db.refresh(session)
    return session


# ── White Label Config (Enterprise feature) ──────────────────────────────────

def get_whitelabel_config(db: Session, clinic_id: int) -> Optional[WhitelabelConfig]:
    """Get white label config for a clinic (with clinic isolation)."""
    return db.query(WhitelabelConfig).filter(WhitelabelConfig.clinic_id == clinic_id).first()


def create_whitelabel_config(db: Session, clinic_id: int, data: dict) -> WhitelabelConfig:
    """Create white label config for a clinic."""
    config = WhitelabelConfig(clinic_id=clinic_id)
    for key, val in data.items():
        if hasattr(config, key):
            setattr(config, key, val)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_whitelabel_config(db: Session, clinic_id: int, data: dict) -> Optional[WhitelabelConfig]:
    """Update white label config (with clinic isolation)."""
    config = get_whitelabel_config(db, clinic_id)
    if not config:
        return None

    for key, val in data.items():
        if hasattr(config, key) and key not in ("id", "clinic_id", "created_at"):
            setattr(config, key, val)

    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config


def get_resellers(db: Session, limit: int = 100) -> list[WhitelabelConfig]:
    """Get all active resellers (is_reseller=True)."""
    return db.query(WhitelabelConfig).filter(WhitelabelConfig.is_reseller.is_(True)).limit(limit).all()


def get_by_custom_domain(db: Session, domain: str) -> Optional[WhitelabelConfig]:
    """Get white label config by custom domain."""
    return db.query(WhitelabelConfig).filter(
        WhitelabelConfig.custom_domain == domain.lower(),
        WhitelabelConfig.domain_verified.is_(True)
    ).first()


def get_db_clinics_for_onboarding(db: Session) -> list:
    """Get clinics that are in trial or active and need onboarding emails (Day 12 not yet sent)."""
    from backend.db.models import Clinic
    return (
        db.query(Clinic)
        .filter(
            Clinic.email != "",
            Clinic.onboarding_emails_sent < 12,
            Clinic.subscription_status.in_(["trial", "active"]),
            Clinic.is_active.is_(True),
        )
        .all()
    )
