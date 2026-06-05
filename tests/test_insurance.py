"""Custom insurance knowledge tests."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_insurance.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.routers.clinic_auth import hash_password


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
def starter_clinic(db):
    slug = "starter-test"
    c = Clinic(
        slug=slug, name="Starter Clinic", specialty="General Practice",
        email=f"{slug}@test.com",
        subscription_status="active", plan="starter",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        trial_ends_at=datetime.utcnow() + timedelta(days=30),
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.delete(c)
    db.commit()


@pytest.fixture
def professional_clinic(db):
    slug = "professional-test"
    c = Clinic(
        slug=slug, name="Professional Clinic", specialty="Family Medicine",
        email=f"{slug}@test.com",
        subscription_status="active", plan="professional",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        trial_ends_at=datetime.utcnow() + timedelta(days=30),
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.delete(c)
    db.commit()


@pytest.fixture
def prof_token(client, professional_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": professional_clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


class TestInsuranceKnowledge:
    def test_requires_auth(self, client, professional_clinic):
        r = client.get(f"/api/{professional_clinic.slug}/insurance-knowledge")
        assert r.status_code == 403

    def test_starter_plan_blocked(self, client, starter_clinic):
        r = client.post("/api/clinic-auth/login", json={
            "email": starter_clinic.email, "password": "testpass123"
        })
        token = r.json()["token"]
        r = client.get(f"/api/{starter_clinic.slug}/insurance-knowledge",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 403
        assert "not available" in r.json()["error"]

    def test_get_default_knowledge(self, client, professional_clinic, prof_token):
        r = client.get(f"/api/{professional_clinic.slug}/insurance-knowledge",
                       headers={"X-Clinic-Token": prof_token})
        assert r.status_code == 200
        data = r.json()
        assert data["accepted_plans"] == ""
        assert data["copay_info"] == ""

    def test_update_knowledge(self, client, professional_clinic, prof_token):
        r = client.patch(f"/api/{professional_clinic.slug}/insurance-knowledge",
                         json={"accepted_plans": "Blue Cross, Aetna"},
                         headers={"X-Clinic-Token": prof_token})
        assert r.status_code == 200
        assert r.json()["accepted_plans"] == "Blue Cross, Aetna"

    def test_update_multiple_fields(self, client, professional_clinic, prof_token):
        r = client.patch(f"/api/{professional_clinic.slug}/insurance-knowledge",
                         json={
                             "accepted_plans": "Blue Cross, Aetna, United",
                             "copay_info": "Office visit: $25, Lab: $50",
                             "deductible_info": "$1,500 annual",
                         },
                         headers={"X-Clinic-Token": prof_token})
        assert r.status_code == 200
        data = r.json()
        assert data["accepted_plans"] == "Blue Cross, Aetna, United"
        assert data["copay_info"] == "Office visit: $25, Lab: $50"
        assert data["deductible_info"] == "$1,500 annual"

    def test_clinic_isolation(self, client, professional_clinic, prof_token):
        r = client.get("/api/other-clinic/insurance-knowledge",
                       headers={"X-Clinic-Token": prof_token})
        assert r.status_code == 403
