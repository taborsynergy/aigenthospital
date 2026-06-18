"""Tests for the admin change-plan endpoint (upgrade/downgrade across all tiers)."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_change_plan.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Provider
from backend import plans as P

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


@pytest.fixture
def clinic(db):
    global _n
    _n += 1
    slug = f"plan-clinic-{_n}"
    c = Clinic(slug=slug, name=f"Plan Clinic {_n}", specialty="Family Medicine",
               plan="professional", monthly_rate=597.0, subscription_status="trial",
               customer_password_hash="x", is_active=True)
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.query(Provider).filter(Provider.clinic_id == c.id).delete()
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


def _plan(db, slug):
    db.expire_all()  # endpoint committed on a separate session; drop cached state
    c = db.query(Clinic).filter_by(slug=slug).first()
    return c.plan, c.monthly_rate


def test_downgrade_professional_to_starter(client, db, clinic):
    r = client.post(f"/admin/api/clinics/{clinic.slug}/plan?plan=starter", headers=ADMIN)
    assert r.status_code == 200
    j = r.json()
    assert j["plan"] == "starter"
    assert j["previous_plan"] == "professional"
    assert j["monthly_rate"] == 297
    assert _plan(db, clinic.slug) == ("starter", 297.0)


def test_gating_follows_downgrade(client, db, clinic):
    client.post(f"/admin/api/clinics/{clinic.slug}/plan?plan=starter", headers=ADMIN)
    c = db.query(Clinic).filter_by(slug=clinic.slug).first()
    db.refresh(c)
    assert P.can_use_reminders(c) is False
    assert P.can_embed_widget(c) is False


def test_upgrade_to_enterprise(client, db, clinic):
    r = client.post(f"/admin/api/clinics/{clinic.slug}/plan?plan=enterprise", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["monthly_rate"] == 997
    c = db.query(Clinic).filter_by(slug=clinic.slug).first()
    db.refresh(c)
    assert P.is_white_label(c) is True
    assert P.monthly_conversation_limit(c) is None


def test_invalid_plan_rejected(client, clinic):
    r = client.post(f"/admin/api/clinics/{clinic.slug}/plan?plan=platinum", headers=ADMIN)
    assert r.status_code == 400


def test_unknown_clinic_404(client):
    r = client.post("/admin/api/clinics/does-not-exist/plan?plan=starter", headers=ADMIN)
    assert r.status_code == 404


def test_requires_admin_password(client, clinic):
    r = client.post(f"/admin/api/clinics/{clinic.slug}/plan?plan=starter")
    assert r.status_code == 401


def test_downgrade_warns_on_over_limit_providers(client, db, clinic):
    for i in range(3):
        db.add(Provider(clinic_id=clinic.id, name=f"Dr {i}", is_active=True))
    db.commit()
    r = client.post(f"/admin/api/clinics/{clinic.slug}/plan?plan=starter", headers=ADMIN)
    assert r.status_code == 200
    assert len(r.json()["warnings"]) >= 1
