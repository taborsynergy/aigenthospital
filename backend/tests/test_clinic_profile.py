"""Tests for per-clinic profile config: onboarding capture, edit-anytime, isolation.

Each clinic configures its own address, office hours, insurance, services and
contact email. A user may only read/edit their OWN clinic's record.
"""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_profile.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, ClinicUser
from backend.auth import create_access_token
from backend.routers.clinic_auth import hash_password

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


def _clinic_with_user(db):
    """Create a clinic + an admin user, return (clinic, auth_headers)."""
    global _n
    _n += 1
    c = Clinic(slug=f"prof-{_n}", name=f"Clinic {_n}", specialty="Family Medicine",
               email=f"clinic{_n}@x.com", plan="professional",
               subscription_status="active", customer_password_hash="x", is_active=True)
    db.add(c)
    db.commit()
    db.refresh(c)
    u = ClinicUser(clinic_id=c.id, email=f"user{_n}@x.com",
                   password_hash=hash_password("pw"), full_name="Owner", role="admin")
    db.add(u)
    db.commit()
    db.refresh(u)
    token = create_access_token({"user_id": u.id, "clinic_id": c.id})
    return c, {"Authorization": f"Bearer {token}"}


# ── Onboarding step now captures the FULL profile ─────────────────────────────

def test_clinic_info_step_persists_full_profile(client, db):
    c, headers = _clinic_with_user(db)
    payload = {"step": "clinic_info", "data": {
        "address": "12 Main St", "phone": "555-1000",
        "office_hours": "Mon-Fri 8-5, Sat 9-12",
        "insurance_accepted": "Aetna, BCBS, Cigna",
        "services_offered": "Annual physicals, Vaccines",
        "email": "frontdesk@clinic.com",
    }}
    r = client.post(f"/api/clinic/onboarding/{c.slug}/steps/clinic_info",
                    json=payload, headers=headers)
    assert r.status_code == 200, r.text

    db.refresh(c)
    assert c.address == "12 Main St"
    assert c.office_hours == "Mon-Fri 8-5, Sat 9-12"
    assert c.insurance_accepted == "Aetna, BCBS, Cigna"
    assert c.services_offered == "Annual physicals, Vaccines"
    assert c.email == "frontdesk@clinic.com"


# ── Edit anytime via GET/PATCH profile ────────────────────────────────────────

def test_get_and_patch_profile(client, db):
    c, headers = _clinic_with_user(db)

    g = client.get(f"/api/clinic/onboarding/{c.slug}/profile", headers=headers)
    assert g.status_code == 200
    assert "office_hours" in g.json()["profile"]

    p = client.patch(f"/api/clinic/onboarding/{c.slug}/profile",
                     json={"office_hours": "24/7", "insurance_accepted": "Medicare"},
                     headers=headers)
    assert p.status_code == 200, p.text
    assert set(p.json()["updated"]) == {"office_hours", "insurance_accepted"}

    db.refresh(c)
    assert c.office_hours == "24/7"
    assert c.insurance_accepted == "Medicare"
    assert c.specialty == "Family Medicine"  # untouched field preserved


def test_patch_profile_empty_is_400(client, db):
    c, headers = _clinic_with_user(db)
    r = client.patch(f"/api/clinic/onboarding/{c.slug}/profile", json={}, headers=headers)
    assert r.status_code == 400


def test_patch_ignores_non_whitelisted_fields(client, db):
    c, headers = _clinic_with_user(db)
    orig_slug = c.slug
    r = client.patch(f"/api/clinic/onboarding/{c.slug}/profile",
                     json={"slug": "hacked", "plan": "enterprise", "address": "9 New Rd"},
                     headers=headers)
    assert r.status_code == 200
    db.refresh(c)
    assert c.address == "9 New Rd"      # whitelisted field applied
    assert c.slug == orig_slug          # slug not changed
    assert c.plan == "professional"     # plan not changed


# ── Tenant isolation: cannot touch another clinic ─────────────────────────────

def test_cannot_edit_other_clinic_profile(client, db):
    a, a_headers = _clinic_with_user(db)
    b, _ = _clinic_with_user(db)

    # Clinic A's token used against Clinic B's slug → 403, B unchanged
    r = client.patch(f"/api/clinic/onboarding/{b.slug}/profile",
                     json={"address": "BREACH"}, headers=a_headers)
    assert r.status_code == 403
    db.refresh(b)
    assert b.address != "BREACH"

    g = client.get(f"/api/clinic/onboarding/{b.slug}/profile", headers=a_headers)
    assert g.status_code == 403


def test_profile_requires_auth(client, db):
    c, _ = _clinic_with_user(db)
    assert client.get(f"/api/clinic/onboarding/{c.slug}/profile").status_code in (401, 403)
