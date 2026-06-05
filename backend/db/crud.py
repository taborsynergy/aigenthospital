import json
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.models import (
    Clinic, UsageLog, SmsConversation, Appointment, ChatSession, AuditLog,
    RecallCampaign, RecallLog, Location, WidgetConfig, InsuranceKnowledge,
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


def get_clinic_by_stripe_customer(db: Session, customer_id: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.stripe_customer_id == customer_id).first()


def get_clinic_by_email(db: Session, email: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(
        func.lower(Clinic.email) == email.lower().strip(),
        Clinic.is_active.is_(True),
    ).first()


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


def activate_subscription(db: Session, slug: str) -> Optional[Clinic]:
    clinic = get_clinic(db, slug)
    if not clinic:
        return None
    now = datetime.utcnow()
    clinic.subscription_status = "active"
    base = clinic.subscription_ends_at if (clinic.subscription_ends_at and clinic.subscription_ends_at > now) else now
    clinic.subscription_ends_at = base + timedelta(days=30)
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
    interval_months ago and who have a phone number on file.
    Returns list of dicts with patient_name, patient_phone, last_visit_ts.
    """
    cutoff = datetime.utcnow() - timedelta(days=interval_months * 30)

    rows = (
        db.query(
            Appointment.patient_name,
            Appointment.patient_phone,
            func.max(Appointment.appointment_ts).label("last_visit"),
        )
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.status.in_(["scheduled", "confirmed", "completed", "rescheduled"]),
            Appointment.patient_phone != "",
            Appointment.patient_phone.isnot(None),
            Appointment.appointment_ts.isnot(None),
        )
        .group_by(Appointment.patient_name, Appointment.patient_phone)
        .having(func.max(Appointment.appointment_ts) < cutoff)
        .all()
    )
    return [
        {
            "patient_name":  r.patient_name,
            "patient_phone": r.patient_phone,
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
