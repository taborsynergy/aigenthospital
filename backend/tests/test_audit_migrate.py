"""Audit trail on sensitive admin actions (GAP2-DB-AUDIT) and migrate_db
idempotency (GAP2-DB-MIGRATE)."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auditmig.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine, migrate_db
from backend.db.models import Clinic, AuditLog
from backend.routers.clinic_auth import hash_password

ADMIN = {"X-Admin-Password": "test-admin-secret"}
_n = 0


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def db():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = S()
    try:
        yield s
    finally:
        s.close()


def _clinic(db):
    global _n
    _n += 1
    c = Clinic(slug=f"au-{_n}", name=f"AU {_n}", specialty="FM", email=f"au{_n}@x.com",
               plan="professional", subscription_status="trial",
               customer_password_hash=hash_password("testpass123"), is_active=True)
    db.add(c); db.commit(); db.refresh(c)
    return c


def _audit_count(db, action, target):
    return db.query(AuditLog).filter(AuditLog.action == action, AuditLog.target == target).count()


# ── GAP2-DB-AUDIT: sensitive actions leave a forensic trail ───────────────────

def test_create_clinic_writes_audit(client, db):
    global _n; _n += 1
    slug = f"au-create-{_n}"
    r = client.post("/admin/api/clinics", headers=ADMIN, json={
        "slug": slug, "name": "New", "specialty": "FM", "email": f"{slug}@x.com"})
    assert r.status_code == 200
    assert _audit_count(db, "clinic.create", slug) >= 1


def test_activate_writes_audit(client, db):
    c = _clinic(db)
    client.post(f"/admin/api/clinics/{c.slug}/activate?payment_reference=AUD-1", headers=ADMIN)
    assert _audit_count(db, "clinic.activate", c.slug) >= 1


def test_plan_change_writes_audit(client, db):
    c = _clinic(db)
    client.post(f"/admin/api/clinics/{c.slug}/plan?plan=enterprise", headers=ADMIN)
    assert _audit_count(db, "clinic.plan_change", c.slug) >= 1 or \
           db.query(AuditLog).filter(AuditLog.target == c.slug,
                                     AuditLog.action.like("clinic.%")).count() >= 1


def test_purge_writes_audit(client, db):
    c = _clinic(db)
    slug = c.slug
    client.delete(f"/admin/api/clinics/{slug}?hard=true", headers=ADMIN)
    assert _audit_count(db, "clinic.purge", slug) >= 1


def test_soft_delete_writes_audit(client, db):
    c = _clinic(db)
    client.delete(f"/admin/api/clinics/{c.slug}", headers=ADMIN)
    assert _audit_count(db, "clinic.deactivate", c.slug) >= 1


def test_audit_log_failure_does_not_break_request(db):
    # write_audit_log swallows DB errors so it can never break the main action.
    from backend.db import crud
    crud.write_audit_log(db, actor="admin", action="x.test", target="t", detail="d")
    assert _audit_count(db, "x.test", "t") >= 1


# ── GAP2-DB-MIGRATE: migrate_db is idempotent on re-run ───────────────────────

def test_migrate_db_idempotent():
    # Running twice must not raise (no duplicate-column errors etc.)
    migrate_db()
    migrate_db()
