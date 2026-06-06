"""Chat / AI Agent endpoint tests — REST chat, config, analytics, profile."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_chat.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.db import crud
from backend.routers.clinic_auth import hash_password

_test_counter = 0


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
    global _test_counter
    _test_counter += 1
    slug = f"chat-clinic-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Chat Test Clinic {_test_counter}",
        specialty="Family Medicine",
        email=f"{slug}@test.com",
        phone="5551234567",
        subscription_status="active",
        plan="professional",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def expired_clinic(db):
    global _test_counter
    _test_counter += 1
    slug = f"expired-{_test_counter}"
    c = Clinic(
        slug=slug, name=f"Expired {_test_counter}", specialty="Dental",
        email=f"{slug}@test.com", subscription_status="trial",
        plan="starter", customer_password_hash=hash_password("testpass123"),
        is_active=True,
        trial_ends_at=datetime.utcnow() - timedelta(days=1),  # expired
    )
    db.add(c); db.commit(); db.refresh(c)
    yield c
    db.query(Clinic).filter(Clinic.id == c.id).delete(); db.commit()


@pytest.fixture
def token(client, clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": clinic.email, "password": "testpass123"})
    return r.json()["token"]


# ── Health Checks ─────────────────────────────────────────────────────────────

class TestHealthEndpoints:

    def test_health_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_returns_service_name(self, client):
        r = client.get("/api/health")
        assert "service" in r.json()

    def test_ai_health_returns_status(self, client):
        """AI health endpoint always returns a status field."""
        r = client.get("/api/health/ai")
        assert r.status_code == 200
        assert "status" in r.json()  # "ok" when API works, "error" in test env without real key


# ── Clinic Config ─────────────────────────────────────────────────────────────

class TestClinicConfig:

    def test_config_returns_expected_fields(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/config")
        assert r.status_code == 200
        d = r.json()
        assert d["agent_name"] is not None
        assert d["clinic_name"] == clinic.name
        assert d["specialty"] == clinic.specialty

    def test_config_unknown_clinic_returns_404(self, client):
        r = client.get("/api/totally-unknown-clinic-abc/config")
        assert r.status_code == 404

    def test_config_includes_white_label_flag(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/config")
        assert "white_label" in r.json()


# ── REST Chat ─────────────────────────────────────────────────────────────────

class TestRestChat:

    def test_chat_returns_response(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "What are your office hours?"})
        assert r.status_code == 200
        d = r.json()
        assert "content" in d
        assert len(d["content"]) > 0

    def test_chat_returns_session_id(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "Hello"})
        assert r.status_code == 200
        assert "session_id" in r.json()

    def test_chat_preserves_session_id(self, client, clinic):
        """Passing a session_id should return the same one."""
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "Hello", "session_id": "test-session-123"})
        assert r.status_code == 200
        assert r.json()["session_id"] == "test-session-123"

    def test_chat_empty_message_returns_400(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat", json={"message": ""})
        assert r.status_code == 400

    def test_chat_whitespace_only_returns_400(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat", json={"message": "   "})
        assert r.status_code == 400

    def test_chat_unknown_clinic_returns_404(self, client):
        r = client.post("/api/nonexistent-slug-abc/chat",
                        json={"message": "Hello"})
        assert r.status_code == 404

    def test_chat_expired_trial_blocked(self, client, expired_clinic):
        r = client.post(f"/api/{expired_clinic.slug}/chat",
                        json={"message": "Book an appointment"})
        assert r.status_code == 403

    def test_chat_escalated_flag_present(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "I have chest pain"})
        assert r.status_code == 200
        assert "escalated" in r.json()


# ── Profile Endpoints ─────────────────────────────────────────────────────────

class TestProfileEndpoints:

    def test_get_profile_returns_clinic_data(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/profile",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == clinic.name
        assert "specialty" in d
        assert "office_hours" in d

    def test_get_profile_requires_auth(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/profile")
        assert r.status_code == 403

    def test_update_profile_name(self, client, clinic, token):
        r = client.patch(f"/api/{clinic.slug}/profile",
                         json={"name": "Updated Clinic Name"},
                         headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        assert r.json().get("ok") is True or "updated_fields" in r.json()

    def test_update_profile_requires_auth(self, client, clinic):
        r = client.patch(f"/api/{clinic.slug}/profile",
                         json={"agent_name": "Bob"})
        assert r.status_code == 403


# ── Analytics Endpoint ────────────────────────────────────────────────────────

class TestAnalyticsEndpoint:

    def test_analytics_returns_data(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/analytics",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200

    def test_analytics_requires_auth(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/analytics")
        assert r.status_code == 403

    def test_analytics_today_report(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/analytics?report=today",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
