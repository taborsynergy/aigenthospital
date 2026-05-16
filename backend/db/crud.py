from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.models import Clinic, UsageLog, SmsConversation


# ── Clinics ──────────────────────────────────────────────────────────────────

def get_clinic(db: Session, slug: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.slug == slug, Clinic.is_active == True).first()


def get_clinic_by_id(db: Session, clinic_id: int) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.id == clinic_id).first()


def get_clinic_by_twilio_number(db: Session, phone: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.twilio_phone == phone, Clinic.is_active == True).first()


def get_clinic_by_stripe_customer(db: Session, customer_id: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.stripe_customer_id == customer_id).first()


def list_clinics(db: Session) -> list[Clinic]:
    return db.query(Clinic).order_by(Clinic.created_at.desc()).all()


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
    """Mark a clinic as active and set subscription_ends_at 30 days from now."""
    clinic = get_clinic(db, slug)
    if not clinic:
        return None
    clinic.subscription_status = "active"
    clinic.subscription_ends_at = datetime.utcnow() + timedelta(days=30)
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
