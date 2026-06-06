"""Dedicated onboarding session tests — Pro+ feature."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_onboarding.db")
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


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


_test_counter = 0


@pytest.fixture
def enterprise_clinic(db, request):
    """Enterprise plan clinic (has onboarding)."""
    global _test_counter
    _test_counter += 1
    slug = f"ent-onb-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Enterprise Onboarding Test {_test_counter}",
        specialty="Family Medicine",
        email=f"{slug}@test.com",
        subscription_status="active",
        plan="enterprise",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    from backend.db.models import OnboardingSession
    db.query(OnboardingSession).filter(OnboardingSession.clinic_id == c.id).delete()
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def growth_clinic(db, request):
    """Growth clinic (no onboarding)."""
    global _test_counter
    _test_counter += 1
    slug = f"growth-onb-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Growth Onboarding Test {_test_counter}",
        specialty="Pediatrics",
        email=f"{slug}@test.com",
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
def ent_token(client, enterprise_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": enterprise_clinic.email,
        "password": "testpass123"
    })
    return r.json()["token"]


@pytest.fixture
def growth_token(client, growth_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": growth_clinic.email,
        "password": "testpass123"
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


class TestOnboardingRequest:
    """Test onboarding session request."""

    def test_request_onboarding(self, client, enterprise_clinic, ent_token):
        """POST /api/{clinic}/onboarding/request creates session."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_name": "Jane Clinic Manager",
                "contact_email": "jane@clinic.com",
                "contact_phone": "(555) 555-5555",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["contact_name"] == "Jane Clinic Manager"
        assert data["status"] == "pending"

    def test_request_without_name(self, client, enterprise_clinic, ent_token):
        """Requesting without contact_name rejected."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_email": "jane@clinic.com",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 400

    def test_request_invalid_email(self, client, enterprise_clinic, ent_token):
        """Requesting with invalid email rejected."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_name": "Jane",
                "contact_email": "notanemail",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 400

    def test_growth_cannot_request_onboarding(self, client, growth_clinic, growth_token):
        """Growth plan cannot access onboarding (403)."""
        r = client.post(
            f"/api/{growth_clinic.slug}/onboarding/request",
            json={
                "contact_name": "Manager",
                "contact_email": "mgr@clinic.com",
            },
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 403


class TestOnboardingScheduling:
    """Test scheduling onboarding sessions."""

    def test_schedule_onboarding(self, client, enterprise_clinic, ent_token):
        """POST /api/{clinic}/onboarding/{id}/schedule schedules session."""
        # Create session
        create_r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_name": "John Manager",
                "contact_email": "john@clinic.com",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        session_id = create_r.json()["id"]

        # Schedule it
        schedule_r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/{session_id}/schedule",
            json={
                "scheduled_at": "2026-06-15T10:00:00Z",
                "meeting_platform": "zoom",
                "duration_minutes": 60,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert schedule_r.status_code == 200
        data = schedule_r.json()
        assert data["status"] == "scheduled"
        assert data["meeting_link"]  # Auto-generated Zoom link
        assert "zoom" in data["meeting_link"].lower()

    def test_schedule_with_custom_link(self, client, enterprise_clinic, ent_token):
        """Schedule with custom meeting link."""
        create_r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_name": "Manager",
                "contact_email": "mgr@clinic.com",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        session_id = create_r.json()["id"]

        schedule_r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/{session_id}/schedule",
            json={
                "scheduled_at": "2026-06-15T10:00:00Z",
                "meeting_link": "https://meet.google.com/abc-defg-hij",
                "meeting_platform": "meet",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert schedule_r.status_code == 200
        assert schedule_r.json()["meeting_link"] == "https://meet.google.com/abc-defg-hij"


class TestOnboardingCompletion:
    """Test completing onboarding sessions."""

    def test_complete_onboarding(self, client, enterprise_clinic, ent_token):
        """POST /api/{clinic}/onboarding/{id}/complete marks done."""
        # Create and schedule
        create_r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_name": "Manager",
                "contact_email": "mgr@clinic.com",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        session_id = create_r.json()["id"]

        client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/{session_id}/schedule",
            json={"scheduled_at": "2026-06-15T10:00:00Z"},
            headers={"X-Clinic-Token": ent_token}
        )

        # Complete it
        r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/{session_id}/complete",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"


class TestOnboardingCancellation:
    """Test cancelling onboarding sessions."""

    def test_cancel_onboarding(self, client, enterprise_clinic, ent_token):
        """POST /api/{clinic}/onboarding/{id}/cancel marks cancelled."""
        create_r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_name": "Manager",
                "contact_email": "mgr@clinic.com",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        session_id = create_r.json()["id"]

        r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/{session_id}/cancel",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"


class TestOnboardingRetrieval:
    """Test retrieving onboarding sessions."""

    def test_get_current_onboarding(self, client, enterprise_clinic, ent_token):
        """GET /api/{clinic}/onboarding/current gets latest session."""
        # Create session
        create_r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_name": "John Manager",
                "contact_email": "john@clinic.com",
                "contact_phone": "(555) 555-1234",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert create_r.status_code == 200

        # Get current
        get_r = client.get(
            f"/api/{enterprise_clinic.slug}/onboarding/current",
            headers={"X-Clinic-Token": ent_token}
        )
        assert get_r.status_code == 200
        data = get_r.json()
        assert data["contact_name"] == "John Manager"
        assert data["status"] == "pending"

    def test_get_current_not_found(self, client, enterprise_clinic, ent_token):
        """GET /api/{clinic}/onboarding/current returns 404 if no session."""
        r = client.get(
            f"/api/{enterprise_clinic.slug}/onboarding/current",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 404


class TestOnboardingUpdate:
    """Test updating onboarding sessions."""

    def test_update_onboarding_notes(self, client, enterprise_clinic, ent_token):
        """PATCH /api/{clinic}/onboarding/{id} updates notes."""
        create_r = client.post(
            f"/api/{enterprise_clinic.slug}/onboarding/request",
            json={
                "contact_name": "Manager",
                "contact_email": "mgr@clinic.com",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        session_id = create_r.json()["id"]

        patch_r = client.patch(
            f"/api/{enterprise_clinic.slug}/onboarding/{session_id}",
            json={
                "notes": "Discussed dashboard and chat features",
                "topics_covered": "dashboard,chat,reports",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert patch_r.status_code == 200
        assert patch_r.json()["notes"] == "Discussed dashboard and chat features"
