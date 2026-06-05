from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from backend.db.database import Base


class Clinic(Base):
    __tablename__ = "clinics"

    id                  = Column(Integer, primary_key=True, index=True)
    slug                = Column(String, unique=True, index=True, nullable=False)
    name                = Column(String, nullable=False)
    specialty           = Column(String, nullable=False)
    agent_name          = Column(String, default="Aria")
    city_state          = Column(String, default="")
    timezone            = Column(String, default="Central Time (CT)")
    address             = Column(String, default="")
    phone               = Column(String, default="")
    email               = Column(String, default="")
    website             = Column(String, default="")
    office_hours        = Column(String, default="Mon–Fri 8am–5pm")
    after_hours_protocol= Column(Text,   default="For emergencies call 911.")
    providers           = Column(Text,   default="")
    services_offered    = Column(Text,   default="")
    insurance_accepted  = Column(String, default="")
    pms_system          = Column(String, default="Athenahealth")
    cancellation_policy = Column(String, default="24-hour notice required.")
    escalation_contact  = Column(String, default="")
    hipaa_verify_method = Column(String, default="Full name + date of birth + last 4 digits of SSN")

    # Twilio
    twilio_phone        = Column(String, default="")

    # Stripe billing
    stripe_customer_id      = Column(String, default="")
    stripe_subscription_id  = Column(String, default="")
    subscription_status     = Column(String, default="trial")   # trial | active | past_due | cancelled
    plan                    = Column(String, default="professional")
    monthly_rate            = Column(Float,  default=299.0)
    trial_ends_at           = Column(DateTime, nullable=True)
    subscription_ends_at    = Column(DateTime, nullable=True)

    # Customer portal auth
    customer_password_hash  = Column(String, default="")
    session_token           = Column(String, default="", index=True)
    token_expires_at        = Column(DateTime, nullable=True)   # None = never expires (legacy)
    failed_login_attempts   = Column(Integer, default=0)
    locked_until            = Column(DateTime, nullable=True)   # account lockout

    # Sales tracking
    activated_at            = Column(DateTime, nullable=True)
    admin_notes             = Column(Text, default="")

    is_active   = Column(Boolean,  default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Location(Base):
    """
    Physical location/office for a clinic.
    Clinics can have 1+ locations with separate addresses, phone, office hours, providers.
    """
    __tablename__ = "locations"

    id                  = Column(Integer,  primary_key=True, index=True)
    clinic_id           = Column(Integer,  ForeignKey("clinics.id"), index=True)
    name                = Column(String,   nullable=False)          # "Main Office", "Downtown", etc.
    address             = Column(String,   default="")
    city_state          = Column(String,   default="")
    phone               = Column(String,   default="")
    office_hours        = Column(Text,     default="")              # "Mon-Fri 8am-5pm"
    providers           = Column(Text,     default="")              # CSV: "Dr. Smith, Dr. Jones"
    timezone            = Column(String,   default="US/Eastern")
    is_active           = Column(Boolean,  default=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

Index("ix_locations_clinic", Location.clinic_id)


class Appointment(Base):
    __tablename__ = "appointments"

    id                   = Column(Integer,  primary_key=True, index=True)
    clinic_id            = Column(Integer,  ForeignKey("clinics.id"), index=True)
    location_id          = Column(Integer,  ForeignKey("locations.id"), nullable=True, index=True)
    confirmation_number  = Column(String,   unique=True, index=True)
    patient_name         = Column(String,   nullable=False)
    patient_phone        = Column(String,   default="")
    patient_email        = Column(String,   default="")
    patient_dob          = Column(String,   default="")
    appointment_type     = Column(String,   nullable=False)
    appointment_datetime = Column(String,   nullable=False)   # human-readable: "Monday, June 9 at 10:00 AM"
    appointment_ts       = Column(DateTime, nullable=True)    # structured timestamp for conflict checking
    provider             = Column(String,   default="")
    is_new_patient       = Column(Boolean,  default=False)
    chief_complaint      = Column(String,   default="")
    status               = Column(String,   default="scheduled")
    channel              = Column(String,   default="web")
    session_id           = Column(String,   default="")
    # Reminder tracking — prevents duplicate sends
    confirmation_sent    = Column(Boolean,  default=False)  # sent immediately after booking
    reminder_72h_sent    = Column(Boolean,  default=False)  # sent ~72h before appointment
    reminder_24h_sent    = Column(Boolean,  default=False)  # sent ~24h before appointment
    created_at           = Column(DateTime, default=datetime.utcnow)

# Composite index for fast time-range queries per clinic
Index("ix_appointments_clinic_created", Appointment.clinic_id, Appointment.created_at)
# Index for reminder queries — clinic + ts + statuses
Index("ix_appointments_reminders", Appointment.clinic_id, Appointment.appointment_ts)


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id            = Column(Integer,  primary_key=True, index=True)
    clinic_id     = Column(Integer,  ForeignKey("clinics.id"), index=True)
    location_id   = Column(Integer,  ForeignKey("locations.id"), nullable=True, index=True)
    session_id    = Column(String)
    channel       = Column(String,   default="web")
    input_tokens  = Column(Integer,  default=0)
    output_tokens = Column(Integer,  default=0)
    created_at    = Column(DateTime, default=datetime.utcnow)


class SmsConversation(Base):
    __tablename__ = "sms_conversations"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id"), index=True)
    patient_phone   = Column(String,   index=True)
    session_id      = Column(String,   unique=True)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    created_at      = Column(DateTime, default=datetime.utcnow)


class ChatSession(Base):
    """Persistent conversation history — survives restarts and enables horizontal scaling."""
    __tablename__ = "chat_sessions"

    id          = Column(Integer,  primary_key=True, index=True)
    clinic_id   = Column(Integer,  ForeignKey("clinics.id"), index=True)
    session_id  = Column(String,   index=True, nullable=False)
    history     = Column(Text,     default="[]")   # JSON array of messages
    channel     = Column(String,   default="web")
    last_active = Column(DateTime, default=datetime.utcnow)
    created_at  = Column(DateTime, default=datetime.utcnow)

Index("ix_chat_sessions_clinic_session", ChatSession.clinic_id, ChatSession.session_id, unique=True)


class AuditLog(Base):
    """Immutable audit trail for all admin and clinic mutations."""
    __tablename__ = "audit_logs"

    id          = Column(Integer,  primary_key=True, index=True)
    actor       = Column(String,   nullable=False)          # "admin" | "clinic:<slug>"
    action      = Column(String,   nullable=False)          # "clinic.create" | "clinic.update" etc.
    target      = Column(String,   default="")              # slug or ID of the affected resource
    detail      = Column(Text,     default="")              # JSON diff or description
    ip_address  = Column(String,   default="")
    created_at  = Column(DateTime, default=datetime.utcnow, index=True)


class RecallCampaign(Base):
    """
    Defines an automated recall campaign for a clinic.
    e.g. "Annual Physical" — send recall SMS to patients not seen in 12 months.
    """
    __tablename__ = "recall_campaigns"

    id               = Column(Integer,  primary_key=True, index=True)
    clinic_id        = Column(Integer,  ForeignKey("clinics.id"), index=True)
    name             = Column(String,   nullable=False)          # "Annual Physical Recall"
    visit_type       = Column(String,   nullable=False)          # "annual physical"
    interval_months  = Column(Integer,  default=12)              # recall after X months
    message_template = Column(Text,     default="")              # {patient_name}, {clinic_name}, {visit_type}
    is_active        = Column(Boolean,  default=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecallLog(Base):
    """
    Tracks every recall SMS sent — prevents duplicate outreach and
    tracks opt-outs per patient/clinic.
    """
    __tablename__ = "recall_logs"

    id              = Column(Integer,  primary_key=True, index=True)
    campaign_id     = Column(Integer,  ForeignKey("recall_campaigns.id"), nullable=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id"), index=True)
    patient_name    = Column(String,   nullable=False)
    patient_phone   = Column(String,   nullable=False, index=True)
    status          = Column(String,   default="sent")   # sent | failed | opted_out | booked
    sent_at         = Column(DateTime, default=datetime.utcnow, index=True)

Index("ix_recall_logs_clinic_phone", RecallLog.clinic_id, RecallLog.patient_phone)


class WidgetConfig(Base):
    """
    Clinic-controlled widget customization.
    Defines branding, colors, text for the embeddable booking widget.
    """
    __tablename__ = "widget_configs"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id"), unique=True, index=True)
    # Branding
    logo_url        = Column(String,   default="")              # clinic logo
    primary_color   = Column(String,   default="#007ACC")       # brand color (hex)
    button_color    = Column(String,   default="#007ACC")       # CTA button color
    font_family     = Column(String,   default="'Segoe UI', sans-serif")
    # Text customization
    widget_title    = Column(String,   default="Book an Appointment")
    widget_subtitle = Column(String,   default="Quick and easy scheduling")
    cta_button_text = Column(String,   default="Schedule Now")
    # Behavior
    show_logo       = Column(Boolean,  default=True)
    show_ratings    = Column(Boolean,  default=True)
    enable_chat     = Column(Boolean,  default=True)
    # Metadata
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InsuranceKnowledge(Base):
    """
    Clinic-specific insurance knowledge for AI agent.
    Allows clinics to customize insurance information and accepted plans.
    """
    __tablename__ = "insurance_knowledge"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id"), unique=True, index=True)
    # Insurance info
    accepted_plans  = Column(Text,     default="")              # CSV: "Blue Cross, Aetna, United Healthcare"
    copay_info      = Column(Text,     default="")              # e.g., "Office visit: $25, Lab: $50"
    deductible_info = Column(Text,     default="")              # e.g., "Annual: $1,500"
    prior_auth_notes= Column(Text,     default="")              # Prior authorization requirements
    custom_knowledge= Column(Text,     default="")              # Any custom insurance info
    # Metadata
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
