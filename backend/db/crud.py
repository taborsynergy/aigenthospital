from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.models import Clinic, UsageLog, SmsConversation, Appointment


# ── Clinics ──────────────────────────────────────────────────────────────────

def get_clinic(db: Session, slug: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.slug == slug, Clinic.is_active == True).first()


def get_clinic_by_id(db: Session, clinic_id: int) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.id == clinic_id).first()


def get_clinic_by_twilio_number(db: Session, phone: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.twilio_phone == phone, Clinic.is_active == True).first()


def get_clinic_by_stripe_customer(db: Session, customer_id: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(Clinic.stripe_customer_id == customer_id).first()


def get_clinic_by_email(db: Session, email: str) -> Optional[Clinic]:
    return db.query(Clinic).filter(
        func.lower(Clinic.email) == email.lower().strip(),
        Clinic.is_active == True,
    ).first()


def get_clinic_by_token(db: Session, token: str) -> Optional[Clinic]:
    if not token:
        return None
    return db.query(Clinic).filter(Clinic.session_token == token, Clinic.is_active == True).first()


def set_session_token(db: Session, clinic_id: int, token: str) -> None:
    clinic = get_clinic_by_id(db, clinic_id)
    if clinic:
        clinic.session_token = token
        db.commit()


def list_clinics(db: Session) -> list[Clinic]:
    return db.query(Clinic).filter(Clinic.is_active == True).order_by(Clinic.created_at.desc()).all()


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
    """Mark a clinic as active and add 30 days — stacks on top of any remaining days."""
    clinic = get_clinic(db, slug)
    if not clinic:
        return None
    now = datetime.utcnow()
    clinic.subscription_status = "active"
    # Extend from current end if still in the future, otherwise from now
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
    """Return number of conversations started this calendar month."""
    from sqlalchemy import extract
    now = datetime.utcnow()
    count = (
        db.query(func.count(UsageLog.id))
        .filter(
            UsageLog.clinic_id == clinic_id,
            extract("year",  UsageLog.created_at) == now.year,
            extract("month", UsageLog.created_at) == now.month,
        )
        .scalar()
    )
    return count or 0


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
