from sqlalchemy import create_engine, event
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
