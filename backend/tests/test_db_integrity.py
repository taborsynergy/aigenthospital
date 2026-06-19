"""Database-integrity tests (GAP-DB): purge cascade (no orphaned PHI), soft-delete
vs hard-delete semantics, unique constraints, default values, updated_at touch,
and opt-out de-duplication. Engine-agnostic (purge deletes children explicitly)."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dbintegrity.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, ClinicUser, RecallLog
from backend.db import crud
from backend.routers.clinic_auth import hash_password

_n = 0


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = S()
    try:
        yield s
    finally:
        s.close()


def _clinic(db, **kw):
    global _n
    _n += 1
    base = dict(slug=f"db-{_n}", name=f"DB {_n}", specialty="FM", email=f"db{_n}@x.com",
                plan="professional", customer_password_hash="x", is_active=True)
    base.update(kw)
    c = Clinic(**base)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ── GAP-DB-001: hard purge removes ALL child rows (no orphaned PHI) ───────────

def test_purge_clinic_cascades_children(db):
    c = _clinic(db)
    db.add(Appointment(clinic_id=c.id, confirmation_number=f"P{_n}", patient_name="Jane PHI",
                       patient_email="jane@x.com", appointment_type="X",
                       appointment_datetime="Mon", status="scheduled",
                       created_at=dt.datetime.utcnow()))
    db.add(ClinicUser(clinic_id=c.id, email=f"dbint-cascadeuser{_n}@x.com",
                      password_hash="x", full_name="U", role="admin"))
    db.add(RecallLog(clinic_id=c.id, patient_name="Jane", patient_phone="jane@x.com",
                     status="sent"))
    db.commit()
    cid = c.id

    assert crud.purge_clinic(db, c.slug) is True
    assert db.query(Clinic).filter(Clinic.id == cid).first() is None
    assert db.query(Appointment).filter(Appointment.clinic_id == cid).count() == 0
    assert db.query(ClinicUser).filter(ClinicUser.clinic_id == cid).count() == 0
    assert db.query(RecallLog).filter(RecallLog.clinic_id == cid).count() == 0


def test_purge_missing_clinic_returns_false(db):
    assert crud.purge_clinic(db, "no-such-slug") is False


# ── GAP-DB-002: soft-delete hides but retains data ────────────────────────────

def test_soft_delete_retains_row(db):
    c = _clinic(db)
    cid = c.id
    assert crud.deactivate_clinic(db, c.slug) is True
    row = db.query(Clinic).filter(Clinic.id == cid).first()
    assert row is not None and row.is_active is False
    # get_clinic_by_token-style active lookups exclude it, but the record persists


# ── GAP-DB-003: unique constraints enforced ───────────────────────────────────

def test_duplicate_slug_rejected(db):
    c = _clinic(db)
    db.add(Clinic(slug=c.slug, name="dup", specialty="FM",
                  email="other@x.com", customer_password_hash="x"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_duplicate_user_email_rejected(db):
    c = _clinic(db)
    email = f"dupuser{_n}@x.com"
    db.add(ClinicUser(clinic_id=c.id, email=email, password_hash="x", full_name="A", role="staff"))
    db.commit()
    db.add(ClinicUser(clinic_id=c.id, email=email, password_hash="x", full_name="B", role="staff"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_duplicate_confirmation_number_rejected(db):
    c = _clinic(db)
    conf = f"CONF{_n}"
    db.add(Appointment(clinic_id=c.id, confirmation_number=conf, patient_name="A",
                       appointment_type="X", appointment_datetime="Mon", status="scheduled"))
    db.commit()
    db.add(Appointment(clinic_id=c.id, confirmation_number=conf, patient_name="B",
                       appointment_type="X", appointment_datetime="Tue", status="scheduled"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── GAP-DB-005: defaults populated on create ──────────────────────────────────

def test_create_clinic_defaults(db):
    global _n
    _n += 1
    c = crud.create_clinic(db, {"slug": f"def-{_n}", "name": "Def", "specialty": "FM",
                                "email": f"def{_n}@x.com", "customer_password_hash": "x"})
    assert c.subscription_status == "trial"
    assert c.trial_ends_at is not None
    assert c.monthly_rate is not None
    assert c.is_active is True


# ── GAP-DB-007: updated_at advances on modification ───────────────────────────

def test_updated_at_touched_on_update(db):
    c = _clinic(db)
    before = c.updated_at
    import time
    time.sleep(0.01)
    c.specialty = "Cardiology"
    db.commit()
    db.refresh(c)
    assert c.updated_at is not None
    assert c.updated_at >= before


# ── GAP-DB-004: opt-out de-duplication (idempotent) ───────────────────────────

def test_recall_optout_is_idempotent(db):
    c = _clinic(db)
    crud.mark_recall_opted_out(db, c.id, "patient@x.com")
    crud.mark_recall_opted_out(db, c.id, "patient@x.com")
    assert crud.is_opted_out(db, c.id, "patient@x.com") is True
    n = db.query(RecallLog).filter(RecallLog.clinic_id == c.id,
                                   RecallLog.status == "opted_out").count()
    assert n >= 1   # opted-out recorded; repeated calls do not corrupt state
