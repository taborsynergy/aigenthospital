from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from backend.config import settings

# ── Engine — connection pooling configured for production ────────────────────
_is_sqlite = "sqlite" in settings.database_url

engine = create_engine(
    settings.database_url,
    # SQLite: disable same-thread check (FastAPI uses threads)
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    # PostgreSQL: production-grade pool settings
    **({} if _is_sqlite else {
        "pool_size":         20,    # base connections kept alive
        "max_overflow":      10,    # extra connections under spike (total 30)
        "pool_timeout":      30,    # seconds to wait for a connection
        "pool_recycle":      1800,  # recycle connections every 30 min
        "pool_pre_ping":     True,  # discard stale connections silently
    })
)

# Enable WAL mode for SQLite — dramatically better concurrency
if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except (OperationalError, DBAPIError) as exc:
        # DB unreachable mid-request (e.g. Supabase/Render restart). Convert to a
        # clean 503 instead of a 500 stack trace; pool_pre_ping recycles the stale
        # connection so the next request recovers automatically.
        import logging
        logging.getLogger(__name__).error("DB unavailable: %s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=503,
                            detail="Service temporarily unavailable. Please try again in a moment.")
    finally:
        db.close()


def init_db():
    from backend.db import models  # noqa: F401 — registers all models
    Base.metadata.create_all(bind=engine)


def migrate_db():
    """Idempotently add columns/tables missing from older deployments.
    Each migration is wrapped in its own transaction so a failure on one
    column does not block the rest, and errors are surfaced at WARNING level.
    """
    import logging
    from sqlalchemy import text, inspect
    log = logging.getLogger(__name__)

    is_pg = not _is_sqlite

    # (table, column, sql_type, default_clause)
    columns = [
        ("clinics", "customer_password_hash", "VARCHAR",   "DEFAULT ''"),
        ("clinics", "session_token",          "VARCHAR",   "DEFAULT ''"),
        ("clinics", "token_expires_at",       "TIMESTAMP", ""),
        ("clinics", "failed_login_attempts",  "INTEGER",   "DEFAULT 0"),
        ("clinics", "locked_until",           "TIMESTAMP", ""),
        ("clinics", "subscription_ends_at",   "TIMESTAMP", ""),
        ("clinics", "trial_ends_at",          "TIMESTAMP", ""),
        ("clinics", "activated_at",           "TIMESTAMP", ""),
        ("clinics", "admin_notes",            "TEXT",      "DEFAULT ''"),
        ("clinics", "onboarding_emails_sent", "INTEGER",   "DEFAULT 0"),
        ("clinics", "trial_reminder_day",     "INTEGER",   ""),
        ("clinics", "renewal_reminder_day",   "INTEGER",   ""),
        ("clinics", "last_payment_reference", "VARCHAR",   "DEFAULT ''"),
        ("clinics", "monthly_rate",           "FLOAT",     "DEFAULT 299.0"),
        ("clinics", "subscription_status",    "VARCHAR",   "DEFAULT 'trial'"),
        ("clinics", "stripe_customer_id",     "VARCHAR",   "DEFAULT ''"),
        ("clinics", "stripe_subscription_id", "VARCHAR",   "DEFAULT ''"),
        ("clinics", "website",                "VARCHAR",   "DEFAULT ''"),
        ("clinics", "twilio_phone",           "VARCHAR",   "DEFAULT ''"),
        ("clinics", "is_active",              "BOOLEAN",   "DEFAULT TRUE"),
        ("clinics", "plan",                   "VARCHAR",   "DEFAULT 'professional'"),
        ("clinics",      "updated_at",        "TIMESTAMP", ""),
        ("appointments", "appointment_ts",      "TIMESTAMP", ""),
        ("appointments", "confirmation_sent",   "BOOLEAN",   "DEFAULT FALSE"),
        ("appointments", "reminder_72h_sent",   "BOOLEAN",   "DEFAULT FALSE"),
        ("appointments", "reminder_24h_sent",   "BOOLEAN",   "DEFAULT FALSE"),
        ("appointments", "location_id",         "INTEGER",   ""),
        ("usage_logs",   "location_id",         "INTEGER",   ""),
        # Widget config
        ("widget_configs", "logo_url",          "VARCHAR",   "DEFAULT ''"),
        ("widget_configs", "primary_color",     "VARCHAR",   "DEFAULT '#007ACC'"),
        ("widget_configs", "button_color",      "VARCHAR",   "DEFAULT '#007ACC'"),
        ("widget_configs", "font_family",       "VARCHAR",   "DEFAULT 'Segoe UI, sans-serif'"),
        ("widget_configs", "widget_title",      "VARCHAR",   "DEFAULT 'Book an Appointment'"),
        ("widget_configs", "widget_subtitle",   "VARCHAR",   "DEFAULT 'Quick and easy scheduling'"),
        ("widget_configs", "cta_button_text",   "VARCHAR",   "DEFAULT 'Schedule Now'"),
        ("widget_configs", "show_logo",         "BOOLEAN",   "DEFAULT TRUE"),
        ("widget_configs", "show_ratings",      "BOOLEAN",   "DEFAULT TRUE"),
        ("widget_configs", "enable_chat",       "BOOLEAN",   "DEFAULT TRUE"),
        # Insurance knowledge
        ("insurance_knowledge", "accepted_plans",   "TEXT",   "DEFAULT ''"),
        ("insurance_knowledge", "copay_info",      "TEXT",   "DEFAULT ''"),
        ("insurance_knowledge", "deductible_info", "TEXT",   "DEFAULT ''"),
        ("insurance_knowledge", "prior_auth_notes","TEXT",   "DEFAULT ''"),
        ("insurance_knowledge", "custom_knowledge","TEXT",   "DEFAULT ''"),
        # Multi-location routing
        ("locations", "zip_code_coverage",   "TEXT",   "DEFAULT ''"),
        ("locations", "service_categories",  "TEXT",   "DEFAULT ''"),
        ("locations", "is_primary",          "BOOLEAN","DEFAULT FALSE"),
        # EHR integration
        ("ehr_configurations", "ehr_system",    "VARCHAR", "DEFAULT ''"),
        ("ehr_configurations", "api_endpoint",  "VARCHAR", "DEFAULT ''"),
        ("ehr_configurations", "api_key",       "VARCHAR", "DEFAULT ''"),
        ("ehr_configurations", "client_id",     "VARCHAR", "DEFAULT ''"),
        ("ehr_configurations", "auto_sync",     "BOOLEAN", "DEFAULT TRUE"),
        ("ehr_configurations", "sync_patients", "BOOLEAN", "DEFAULT FALSE"),
        ("ehr_configurations", "last_sync_at",  "TIMESTAMP", ""),
        ("ehr_configurations", "sync_status",   "VARCHAR", "DEFAULT 'inactive'"),
        ("ehr_configurations", "error_message", "TEXT",   "DEFAULT ''"),
        # Custom AI training
        ("custom_ai_training", "training_type", "VARCHAR", "DEFAULT ''"),
        ("custom_ai_training", "title",         "VARCHAR", "DEFAULT ''"),
        ("custom_ai_training", "content",       "TEXT",    "DEFAULT ''"),
        ("custom_ai_training", "is_active",     "BOOLEAN", "DEFAULT TRUE"),
        ("custom_ai_training", "priority",      "INTEGER", "DEFAULT 0"),
        # Provider management (multi-doctor)
        ("providers", "name",            "VARCHAR", ""),
        ("providers", "email",           "VARCHAR", "DEFAULT ''"),
        ("providers", "phone",           "VARCHAR", "DEFAULT ''"),
        ("providers", "specialty",       "VARCHAR", "DEFAULT ''"),
        ("providers", "license_number",  "VARCHAR", "DEFAULT ''"),
        ("providers", "npi_number",      "VARCHAR", "DEFAULT ''"),
        ("providers", "bio",             "TEXT",    "DEFAULT ''"),
        ("providers", "photo_url",       "VARCHAR", "DEFAULT ''"),
        ("providers", "is_active",       "BOOLEAN", "DEFAULT TRUE"),
        ("providers", "clinic_id",       "INTEGER", ""),
        ("providers", "created_at",      "TIMESTAMP", ""),
        ("providers", "updated_at",      "TIMESTAMP", ""),
        # Onboarding sessions (Pro+ feature)
        ("onboarding_sessions", "clinic_id",        "INTEGER",   ""),
        ("onboarding_sessions", "status",           "VARCHAR",   "DEFAULT 'pending'"),
        ("onboarding_sessions", "contact_name",     "VARCHAR",   "DEFAULT ''"),
        ("onboarding_sessions", "contact_email",    "VARCHAR",   "DEFAULT ''"),
        ("onboarding_sessions", "contact_phone",    "VARCHAR",   "DEFAULT ''"),
        ("onboarding_sessions", "meeting_link",     "VARCHAR",   "DEFAULT ''"),
        ("onboarding_sessions", "meeting_platform", "VARCHAR",   "DEFAULT 'zoom'"),
        ("onboarding_sessions", "duration_minutes", "INTEGER",   "DEFAULT 60"),
        ("onboarding_sessions", "notes",            "TEXT",      "DEFAULT ''"),
        ("onboarding_sessions", "topics_covered",   "TEXT",      "DEFAULT ''"),
        ("onboarding_sessions", "requested_at",     "TIMESTAMP", ""),
        ("onboarding_sessions", "scheduled_at",     "TIMESTAMP", ""),
        ("onboarding_sessions", "completed_at",     "TIMESTAMP", ""),
        ("onboarding_sessions", "created_at",       "TIMESTAMP", ""),
        ("onboarding_sessions", "updated_at",       "TIMESTAMP", ""),
        # White label configuration (Enterprise feature)
        ("whitelabel_configs", "clinic_id",             "INTEGER",   ""),
        ("whitelabel_configs", "logo_url",              "VARCHAR",   "DEFAULT ''"),
        ("whitelabel_configs", "primary_color",         "VARCHAR",   "DEFAULT '#007ACC'"),
        ("whitelabel_configs", "secondary_color",       "VARCHAR",   "DEFAULT '#F0F0F0'"),
        ("whitelabel_configs", "accent_color",          "VARCHAR",   "DEFAULT '#FF6B6B'"),
        ("whitelabel_configs", "font_family",           "VARCHAR",   "DEFAULT 'Segoe UI, sans-serif'"),
        ("whitelabel_configs", "company_name",          "VARCHAR",   "DEFAULT ''"),
        ("whitelabel_configs", "remove_tabor_branding", "BOOLEAN",   "DEFAULT FALSE"),
        ("whitelabel_configs", "remove_powered_by",     "BOOLEAN",   "DEFAULT FALSE"),
        ("whitelabel_configs", "custom_footer_text",    "VARCHAR",   "DEFAULT ''"),
        ("whitelabel_configs", "custom_domain",         "VARCHAR",   "DEFAULT ''"),
        ("whitelabel_configs", "domain_verified",       "BOOLEAN",   "DEFAULT FALSE"),
        ("whitelabel_configs", "ssl_certificate_url",   "VARCHAR",   "DEFAULT ''"),
        ("whitelabel_configs", "is_reseller",           "BOOLEAN",   "DEFAULT FALSE"),
        ("whitelabel_configs", "reseller_commission",   "FLOAT",     "DEFAULT 0.0"),
        ("whitelabel_configs", "max_sub_clinics",       "INTEGER",   "DEFAULT 0"),
        ("whitelabel_configs", "can_access_source",     "BOOLEAN",   "DEFAULT FALSE"),
        ("whitelabel_configs", "source_access_granted_at", "TIMESTAMP", ""),
        ("whitelabel_configs", "self_host_enabled",     "BOOLEAN",   "DEFAULT FALSE"),
        ("whitelabel_configs", "created_at",            "TIMESTAMP", ""),
        ("whitelabel_configs", "updated_at",            "TIMESTAMP", ""),
        # Phase 2: notification preferences on clinic
        ("clinics", "reminder_72h_enabled",    "BOOLEAN", "DEFAULT TRUE"),
        ("clinics", "reminder_24h_enabled",    "BOOLEAN", "DEFAULT TRUE"),
        ("clinics", "custom_confirmation_msg", "TEXT",    "DEFAULT ''"),
        # Phase 2: appointment types table columns
        ("appointment_types", "clinic_id",        "INTEGER", ""),
        ("appointment_types", "name",             "VARCHAR", ""),
        ("appointment_types", "duration_minutes", "INTEGER", "DEFAULT 30"),
        ("appointment_types", "description",      "TEXT",    "DEFAULT ''"),
        ("appointment_types", "is_active",        "BOOLEAN", "DEFAULT TRUE"),
        ("appointment_types", "created_at",       "TIMESTAMP", ""),
        ("appointment_types", "updated_at",       "TIMESTAMP", ""),
        # Phase 2: clinic holidays table columns
        ("clinic_holidays", "clinic_id",  "INTEGER",   ""),
        ("clinic_holidays", "date",       "VARCHAR",   ""),
        ("clinic_holidays", "reason",     "VARCHAR",   "DEFAULT ''"),
        ("clinic_holidays", "created_at", "TIMESTAMP", ""),
    ]

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    for table, col, col_type, default in columns:
        if table not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        if col in existing_cols:
            continue  # already present — skip

        col_def = f"{col} {col_type} {default}".strip()
        sql = f"ALTER TABLE {table} ADD COLUMN {col_def}"
        if is_pg:
            sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_def}"

        try:
            with engine.begin() as conn:   # auto-commits or rolls back
                conn.execute(text(sql))
            log.info("migrate_db: added %s.%s", table, col)
        except Exception as exc:
            log.warning("migrate_db: could not add %s.%s — %s", table, col, exc)
