from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
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
    monthly_rate            = Column(Float,  default=299.0)
    trial_ends_at           = Column(DateTime, nullable=True)
    subscription_ends_at    = Column(DateTime, nullable=True)  # set when payment confirmed; expires after 30 days

    # Customer portal auth
    customer_password_hash  = Column(String, default="")
    session_token           = Column(String, default="", index=True)

    # Sales tracking
    activated_at            = Column(DateTime, nullable=True)   # when first payment confirmed
    admin_notes             = Column(Text, default="")          # internal CRM notes

    is_active   = Column(Boolean,  default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class Appointment(Base):
    __tablename__ = "appointments"

    id                   = Column(Integer,  primary_key=True, index=True)
    clinic_id            = Column(Integer,  ForeignKey("clinics.id"), index=True)
    confirmation_number  = Column(String,   unique=True, index=True)
    patient_name         = Column(String,   nullable=False)
    patient_phone        = Column(String,   default="")
    patient_email        = Column(String,   default="")
    patient_dob          = Column(String,   default="")
    appointment_type     = Column(String,   nullable=False)
    appointment_datetime = Column(String,   nullable=False)   # free-form from Aria, e.g. "Monday, May 21 at 10:00 AM"
    provider             = Column(String,   default="")
    is_new_patient       = Column(Boolean,  default=False)
    chief_complaint      = Column(String,   default="")
    status               = Column(String,   default="scheduled")  # scheduled | cancelled | rescheduled
    channel              = Column(String,   default="web")         # web | sms
    session_id           = Column(String,   default="")
    created_at           = Column(DateTime, default=datetime.utcnow)


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id            = Column(Integer,  primary_key=True, index=True)
    clinic_id     = Column(Integer,  ForeignKey("clinics.id"), index=True)
    session_id    = Column(String)
    channel       = Column(String,   default="web")   # web | sms
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
