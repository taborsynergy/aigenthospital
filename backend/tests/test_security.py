"""Tests for recent security work: admin-gated clinic-user create, password policy,
empty-reset-token guard, plan gating (widget + agent name), and tenant isolation."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_security.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, ClinicUser
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


def _make_clinic(db, plan="professional"):
    global _n
    _n += 1
    slug = f"sec-{_n}"
    c = Clinic(slug=slug, name=f"Sec Clinic {_n}", specialty="FM", plan=plan,
               email=f"{slug}@test.com", subscription_status="active",
               customer_password_hash=hash_password("testpass123"), is_active=True,
               subscription_ends_at=datetime.utcnow() + timedelta(days=30))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _login(client, clinic):
    r = client.post("/api/clinic-auth/login",
                    json={"email": clinic.email, "password": "testpass123"})
    return r.json()["token"]


# ── Clinic-user create is admin-gated + has a password policy ──────────────────

def test_user_create_requires_admin(client, db):
    c = _make_clinic(db)
    r = client.post("/api/clinic/users/create", json={
        "clinic_slug": c.slug, "email": f"u{c.slug}@x.com", "full_name": "U",
        "password": "Secret123", "role": "admin"})
    assert r.status_code in (401, 403)


def test_user_create_with_admin_succeeds(client, db):
    c = _make_clinic(db)
    r = client.post("/api/clinic/users/create", headers=ADMIN, json={
        "clinic_slug": c.slug, "email": f"ok{c.slug}@x.com", "full_name": "U",
        "password": "Secret123", "role": "admin"})
    assert r.status_code == 200


def test_user_create_weak_password_rejected(client, db):
    c = _make_clinic(db)
    r = client.post("/api/clinic/users/create", headers=ADMIN, json={
        "clinic_slug": c.slug, "email": f"weak{c.slug}@x.com", "full_name": "U",
        "password": "x", "role": "admin"})
    assert r.status_code == 400


def test_empty_reset_token_rejected(client):
    r = client.post("/api/clinic/users/reset-password",
                    json={"token": "", "new_password": "NewSecret123"})
    assert r.status_code == 400


# ── Plan gating: widget + custom agent name (Growth+) ─────────────────────────

def test_widget_gated_to_growth(client, db):
    pro = _make_clinic(db, "professional")
    starter = _make_clinic(db, "starter")
    assert client.get(f"/api/{pro.slug}/widget/config",
                      headers={"x-clinic-token": _login(client, pro)}).status_code == 200
    assert client.get(f"/api/{starter.slug}/widget/config",
                      headers={"x-clinic-token": _login(client, starter)}).status_code == 403


def test_agent_name_gated_to_growth(client, db):
    pro = _make_clinic(db, "professional")
    starter = _make_clinic(db, "starter")
    assert client.patch(f"/api/{pro.slug}/profile",
                        headers={"x-clinic-token": _login(client, pro)},
                        json={"agent_name": "Bella"}).status_code == 200
    assert client.patch(f"/api/{starter.slug}/profile",
                        headers={"x-clinic-token": _login(client, starter)},
                        json={"agent_name": "Bella"}).status_code == 403


# ── Tenant isolation: one clinic cannot read another's patient data ───────────

def test_cross_tenant_appointments_blocked(client, db):
    a = _make_clinic(db)
    b = _make_clinic(db)
    # plant a patient (PHI) in clinic B
    db.add(Appointment(clinic_id=b.id, confirmation_number=f"PHI-{b.slug}",
                       patient_name="Jane PHI", patient_phone="555-0000",
                       patient_email="jane@x.com", appointment_type="Checkup",
                       appointment_datetime="Mon", status="scheduled",
                       created_at=datetime.utcnow()))
    db.commit()
    a_tok = _login(client, a)
    # A's token cannot read B's appointments
    r = client.get(f"/api/{b.slug}/appointments", headers={"x-clinic-token": a_tok})
    assert r.status_code == 403
    assert "Jane PHI" not in r.text
    # B's own token can
    b_tok = _login(client, b)
    r2 = client.get(f"/api/{b.slug}/appointments", headers={"x-clinic-token": b_tok})
    assert r2.status_code == 200
    assert "Jane PHI" in r2.text
