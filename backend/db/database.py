from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from backend.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

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
    """Add any columns that may be missing from older PostgreSQL deployments.
    SQLAlchemy create_all only creates new tables, not new columns in existing tables.
    This function safely adds missing columns without dropping any data.
    """
    import logging
    from sqlalchemy import text
    log = logging.getLogger(__name__)

    is_pg = "postgresql" in str(engine.url) or "postgres" in str(engine.url)

    # (column_name, sql_type, default_clause)
    columns = [
        ("customer_password_hash", "VARCHAR",   "DEFAULT ''"),
        ("session_token",          "VARCHAR",   "DEFAULT ''"),
        ("subscription_ends_at",   "TIMESTAMP", ""),
        ("trial_ends_at",          "TIMESTAMP", ""),
        ("activated_at",           "TIMESTAMP", ""),
        ("admin_notes",            "TEXT",      "DEFAULT ''"),
        ("monthly_rate",           "FLOAT",     "DEFAULT 299.0"),
        ("subscription_status",    "VARCHAR",   "DEFAULT 'trial'"),
        ("stripe_customer_id",     "VARCHAR",   "DEFAULT ''"),
        ("stripe_subscription_id", "VARCHAR",   "DEFAULT ''"),
        ("website",                "VARCHAR",   "DEFAULT ''"),
        ("twilio_phone",           "VARCHAR",   "DEFAULT ''"),
        ("is_active",              "BOOLEAN",   "DEFAULT TRUE"),
    ]

    with engine.connect() as conn:
        for col, col_type, default in columns:
            col_def = f"{col} {col_type} {default}".strip()
            if is_pg:
                sql = f"ALTER TABLE clinics ADD COLUMN IF NOT EXISTS {col_def}"
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    log.debug("migrate_db skip %s: %s", col, exc)
            else:
                # SQLite: IF NOT EXISTS not supported in older versions
                try:
                    conn.execute(text(f"ALTER TABLE clinics ADD COLUMN {col_def}"))
                    conn.commit()
                    log.info("migrate_db added column: %s", col)
                except Exception:
                    conn.rollback()  # column already exists — fine
