"""EHR system integration tests."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_ehr.db")
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
def enterprise_clinic(db):
    slug = "enterprise-ehr-test"
    c = Clinic(
        slug=slug, name="Enterprise EHR Clinic", specialty="Family Medicine",
        email=f"{slug}@test.com",
        subscription_status="active", plan="enterprise",
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
def ent_token(client, enterprise_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": enterprise_clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


@pytest.fixture
def db():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = S()
    try:
        yield s
    finally:
        s.close()


class TestEHRIntegration:
    def test_requires_auth(self, client, enterprise_clinic):
        r = client.get(f"/api/{enterprise_clinic.slug}/ehr-config")
        assert r.status_code == 403

    def test_get_default_config(self, client, enterprise_clinic, ent_token):
        r = client.get(f"/api/{enterprise_clinic.slug}/ehr-config",
                       headers={"X-Clinic-Token": ent_token})
        assert r.status_code == 200
        data = r.json()
        assert data["ehr_system"] == ""
        assert data["auto_sync"] is True

    def test_update_ehr_system(self, client, enterprise_clinic, ent_token):
        r = client.patch(f"/api/{enterprise_clinic.slug}/ehr-config",
                         json={
                             "ehr_system": "epic",
                             "api_endpoint": "https://epic.example.com/api",
                             "api_key": "sk-abc123xyz",
                         },
                         headers={"X-Clinic-Token": ent_token})
        assert r.status_code == 200
        data = r.json()
        assert data["ehr_system"] == "epic"
        assert data["api_endpoint"] == "https://epic.example.com/api"

    def test_update_sync_settings(self, client, enterprise_clinic, ent_token):
        r = client.patch(f"/api/{enterprise_clinic.slug}/ehr-config",
                         json={
                             "auto_sync": False,
                             "sync_patients": True,
                         },
                         headers={"X-Clinic-Token": ent_token})
        assert r.status_code == 200
        data = r.json()
        assert data["auto_sync"] is False
        assert data["sync_patients"] is True

    def test_test_connection(self, client, enterprise_clinic, ent_token):
        # First configure the system
        client.patch(f"/api/{enterprise_clinic.slug}/ehr-config",
                     json={"ehr_system": "epic", "api_endpoint": "https://epic.example.com", "api_key": "key"},
                     headers={"X-Clinic-Token": ent_token})

        # Test connection
        r = client.post(f"/api/{enterprise_clinic.slug}/ehr-config/test",
                        headers={"X-Clinic-Token": ent_token})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True

    def test_get_supported_systems(self, client, enterprise_clinic, ent_token):
        r = client.get(f"/api/{enterprise_clinic.slug}/ehr-config/systems",
                       headers={"X-Clinic-Token": ent_token})
        assert r.status_code == 200
        data = r.json()
        assert "supported_systems" in data
        assert "epic" in data["supported_systems"]
