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

    # Onboarding email sequence tracking
    # Stores highest day sent: 0=Day0, 1=Day1, 3=Day3, 7=Day7, 12=Day12, 99=complete
    onboarding_emails_sent  = Column(Integer, default=0)

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
    clinic_id           = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    name                = Column(String,   nullable=False)          # "Main Office", "Downtown", etc.
    address             = Column(String,   default="")
    city_state          = Column(String,   default="")
    phone               = Column(String,   default="")
    office_hours        = Column(Text,     default="")              # "Mon-Fri 8am-5pm"
    providers           = Column(Text,     default="")              # CSV: "Dr. Smith, Dr. Jones"
    timezone            = Column(String,   default="US/Eastern")
    # Multi-location routing (Pro+)
    zip_code_coverage   = Column(Text,     default="")              # CSV zip codes: "12345,12346,12347"
    service_categories  = Column(Text,     default="")              # CSV: "General, Pediatrics, Urgent Care"
    is_primary          = Column(Boolean,  default=False)           # Default location if no match
    is_active           = Column(Boolean,  default=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# clinic_id is already indexed via index=True on the column (no separate Index needed)


class Provider(Base):
    """
    Doctor/Provider for a clinic (Growth+ feature: 2-5 doctors per clinic).
    Growth plan: max 5 providers
    Professional plan: max 5 providers
    Enterprise plan: unlimited providers
    """
    __tablename__ = "providers"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    name            = Column(String,   nullable=False)          # "Dr. Jane Smith"
    email           = Column(String,   default="")              # jane@clinic.com
    phone           = Column(String,   default="")              # (555) 555-5555
    specialty       = Column(String,   default="")              # "Pediatrics", "General", etc.
    license_number  = Column(String,   default="")              # Medical license number
    npi_number      = Column(String,   default="")              # National Provider Identifier
    bio             = Column(Text,     default="")              # Provider biography/credentials
    photo_url       = Column(String,   default="")              # URL to provider photo
    is_active       = Column(Boolean,  default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# clinic_id is already indexed via index=True on the column (no separate Index needed)


class OnboardingSession(Base):
    """
    Dedicated onboarding sessions for Pro+ clinics.
    Tracks onboarding request, scheduling, and completion.
    """
    __tablename__ = "onboarding_sessions"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    status          = Column(String,   default="pending")        # pending, scheduled, completed, cancelled
    requested_at    = Column(DateTime, default=datetime.utcnow)
    scheduled_at    = Column(DateTime, nullable=True)            # When onboarding is scheduled
    completed_at    = Column(DateTime, nullable=True)            # When onboarding completed
    contact_name    = Column(String,   default="")               # Primary contact name
    contact_email   = Column(String,   default="")               # Primary contact email
    contact_phone   = Column(String,   default="")               # Primary contact phone
    meeting_link    = Column(String,   default="")               # Zoom/Meet link for session
    meeting_platform= Column(String,   default="zoom")           # zoom, meet, teams, etc.
    duration_minutes= Column(Integer,  default=60)               # Session duration
    notes           = Column(Text,     default="")               # Onboarding notes/topics covered
    topics_covered  = Column(Text,     default="")               # CSV: "dashboard,chat,reports,integration"
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# clinic_id is already indexed via index=True on the column (no separate Index needed)


class Appointment(Base):
    __tablename__ = "appointments"

    id                   = Column(Integer,  primary_key=True, index=True)
    clinic_id            = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    location_id          = Column(Integer,  ForeignKey("locations.id", ondelete="CASCADE"), nullable=True, index=True)
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
    clinic_id     = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    location_id   = Column(Integer,  ForeignKey("locations.id", ondelete="CASCADE"), nullable=True, index=True)
    session_id    = Column(String)
    channel       = Column(String,   default="web")
    input_tokens  = Column(Integer,  default=0)
    output_tokens = Column(Integer,  default=0)
    created_at    = Column(DateTime, default=datetime.utcnow)


class SmsConversation(Base):
    __tablename__ = "sms_conversations"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    patient_phone   = Column(String,   index=True)
    session_id      = Column(String,   unique=True)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    created_at      = Column(DateTime, default=datetime.utcnow)


class ChatSession(Base):
    """Persistent conversation history — survives restarts and enables horizontal scaling."""
    __tablename__ = "chat_sessions"

    id          = Column(Integer,  primary_key=True, index=True)
    clinic_id   = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
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
    clinic_id        = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
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
    campaign_id     = Column(Integer,  ForeignKey("recall_campaigns.id", ondelete="CASCADE"), nullable=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
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
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), unique=True, index=True)
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


class CustomAITraining(Base):
    """
    Custom AI training data for clinic-specific agent customization.
    Allows clinics to teach Aria about their specific procedures, policies, and preferences.
    """
    __tablename__ = "custom_ai_training"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    # Training content
    training_type   = Column(String,   default="")              # "procedure", "policy", "faq", "custom"
    title           = Column(String,   nullable=False)          # e.g., "Telehealth Policy", "Intake Form"
    content         = Column(Text,     nullable=False)          # Training data (max 5000 chars)
    # Status
    is_active       = Column(Boolean,  default=True)            # Whether to include in agent prompt
    priority        = Column(Integer,  default=0)               # 0-10, higher = more important
    # Metadata
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# clinic_id is already indexed via index=True on the column (no separate Index needed)


class EHRConfiguration(Base):
    """
    EHR system integration configuration for clinics.
    Allows clinics to sync appointments and patient data with their EHR.
    """
    __tablename__ = "ehr_configurations"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), unique=True, index=True)
    # EHR system type
    ehr_system      = Column(String,   default="")              # "epic", "cerner", "athenahealth", etc.
    # Connection details (encrypted at rest)
    api_endpoint    = Column(String,   default="")              # API base URL
    api_key         = Column(String,   default="")              # Encrypted API key
    client_id       = Column(String,   default="")              # OAuth client ID
    # Sync settings
    auto_sync       = Column(Boolean,  default=True)            # Auto-sync appointments to EHR
    sync_patients   = Column(Boolean,  default=False)           # Sync patient data
    last_sync_at    = Column(DateTime, nullable=True)           # Last successful sync
    sync_status     = Column(String,   default="inactive")      # inactive, syncing, active, error
    error_message   = Column(Text,     default="")              # Last error if any
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
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), unique=True, index=True)
    # Insurance info
    accepted_plans  = Column(Text,     default="")              # CSV: "Blue Cross, Aetna, United Healthcare"
    copay_info      = Column(Text,     default="")              # e.g., "Office visit: $25, Lab: $50"
    deductible_info = Column(Text,     default="")              # e.g., "Annual: $1,500"
    prior_auth_notes= Column(Text,     default="")              # Prior authorization requirements
    custom_knowledge= Column(Text,     default="")              # Any custom insurance info
    # Metadata
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WhitelabelConfig(Base):
    """
    White label configuration for Enterprise plan clinics.
    Enables custom branding, domain mapping, and multi-tenant reselling.
    """
    __tablename__ = "whitelabel_configs"

    id                      = Column(Integer,  primary_key=True, index=True)
    clinic_id               = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), unique=True, index=True)

    # Branding
    logo_url                = Column(String,   default="")              # Custom logo URL
    primary_color           = Column(String,   default="#007ACC")       # Brand primary color
    secondary_color         = Column(String,   default="#F0F0F0")       # Brand secondary color
    accent_color            = Column(String,   default="#FF6B6B")       # Accent color
    font_family             = Column(String,   default="Segoe UI, sans-serif")
    company_name            = Column(String,   default="")              # Custom company name in UI

    # Branding removal
    remove_tabor_branding   = Column(Boolean,  default=False)           # Hide "Tabor" logo/footer
    remove_powered_by       = Column(Boolean,  default=False)           # Hide "Powered by Tabor"
    custom_footer_text      = Column(String,   default="")              # Custom footer text

    # Domain
    custom_domain           = Column(String,   default="")              # e.g., "clinic.yourdomain.com"
    domain_verified         = Column(Boolean,  default=False)           # DNS verification status
    ssl_certificate_url     = Column(String,   default="")              # SSL cert path for custom domain

    # Reseller capabilities
    is_reseller             = Column(Boolean,  default=False)           # Can create sub-tenants
    reseller_commission     = Column(Float,    default=0.0)             # Commission % (20.0 = 20%)
    max_sub_clinics         = Column(Integer,  default=0)               # 0 = unlimited

    # Source code access
    can_access_source       = Column(Boolean,  default=False)           # Source code transfer granted
    source_access_granted_at= Column(DateTime, nullable=True)
    self_host_enabled       = Column(Boolean,  default=False)           # Self-hosting permitted

    # Metadata
    created_at              = Column(DateTime, default=datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

Index("ix_whitelabel_clinic", WhitelabelConfig.clinic_id)
Index("ix_whitelabel_reseller", WhitelabelConfig.is_reseller)
Index("ix_whitelabel_domain", WhitelabelConfig.custom_domain)


class ClinicUser(Base):
    """
    Admin/staff users for a clinic.
    Each clinic can have multiple users with different roles.
    """
    __tablename__ = "clinic_users"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    email           = Column(String,   unique=True, nullable=False, index=True)
    password_hash   = Column(String,   nullable=False)
    full_name       = Column(String,   nullable=False)
    role            = Column(String,   default="staff")        # admin | manager | staff | billing
    is_active       = Column(Boolean,  default=True)
    # Password reset
    reset_token     = Column(String,   default="", index=True)
    reset_token_expires = Column(DateTime, nullable=True)
    # Login tracking
    last_login_at   = Column(DateTime, nullable=True)
    failed_login_attempts = Column(Integer, default=0)
    locked_until    = Column(DateTime, nullable=True)
    # Metadata
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Note: clinic_id and email already get indexes via index=True on the columns above;
    # no explicit Index() needed (a same-named explicit index would collide on create_all).


class OnboardingChecklist(Base):
    """
    Tracks setup checklist completion for clinics (Day 1-5 onboarding).
    Used to monitor progress and trigger go-live actions.
    """
    __tablename__ = "onboarding_checklists"

    id              = Column(Integer,  primary_key=True, index=True)
    clinic_id       = Column(Integer,  ForeignKey("clinics.id", ondelete="CASCADE"), unique=True, index=True)

    # Step 1: Clinic Info
    clinic_info_completed = Column(Boolean, default=False)
    clinic_info_data = Column(Text, default="{}")  # JSON: specialty, address, etc.

    # Step 2: Branding
    branding_completed = Column(Boolean, default=False)
    branding_data = Column(Text, default="{}")  # JSON: logo_url, primary_color, etc.

    # Step 3: Email Config (SMTP)
    email_config_completed = Column(Boolean, default=False)
    email_config_data = Column(Text, default="{}")  # JSON: smtp_host, smtp_port, etc.
    email_config_tested = Column(Boolean, default=False)

    # Step 4: SMS Config (Twilio)
    sms_config_completed = Column(Boolean, default=False)
    sms_config_data = Column(Text, default="{}")  # JSON: twilio_account_sid, etc.
    sms_config_tested = Column(Boolean, default=False)

    # Step 5: EMR Integration
    emr_integration_completed = Column(Boolean, default=False)
    emr_integration_data = Column(Text, default="{}")  # JSON: ehr_system, api_endpoint, etc.

    # Step 6: Staff Training
    staff_training_completed = Column(Boolean, default=False)
    staff_training_date = Column(DateTime, nullable=True)

    # Go-Live
    go_live_date = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

Index("ix_onboarding_checklist_clinic", OnboardingChecklist.clinic_id)
