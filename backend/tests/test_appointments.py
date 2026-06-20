"""Appointment booking, listing, and status update tests."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_appointments.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment
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
    slug = f"appt-clinic-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Appointment Test Clinic {_test_counter}",
        specialty="Family Medicine",
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
    db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def token(client, clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


@pytest.fixture
def seeded_appointment(db, clinic):
    """Create one appointment directly in DB for status update tests."""
    appt = Appointment(
        clinic_id=clinic.id,
        confirmation_number="TEST-CONF-001",
        patient_name="John Doe",
        patient_phone="5551234567",
        patient_email="john@example.com",
        appointment_type="New Patient Visit",
        appointment_datetime="2026-07-01 10:00 AM",
        provider="Dr. Smith",
        status="scheduled",
        channel="web",
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    yield appt
    db.query(Appointment).filter(Appointment.id == appt.id).delete()
    db.commit()


# ── List Appointments ────────────────────────────────────────────────────────

class TestListAppointments:

    def test_list_returns_empty_for_new_clinic(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/appointments",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        assert r.json() == []

    def test_list_requires_auth(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/appointments")
        assert r.status_code == 403

    def test_list_wrong_token_rejected(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/appointments",
                       headers={"X-Clinic-Token": "invalid-token"})
        assert r.status_code == 403

    def test_list_shows_seeded_appointment(self, client, clinic, token, seeded_appointment):
        r = client.get(f"/api/{clinic.slug}/appointments",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        conf_nums = [a["confirmation_number"] for a in data]
        assert "TEST-CONF-001" in conf_nums

    def test_list_contains_expected_fields(self, client, clinic, token, seeded_appointment):
        r = client.get(f"/api/{clinic.slug}/appointments",
                       headers={"X-Clinic-Token": token})
        appt = r.json()[0]
        assert "confirmation_number" in appt
        assert "patient_name" in appt
        assert "status" in appt
        assert "appointment_type" in appt

    def test_clinic_isolation(self, client, db, token):
        """Token from one clinic cannot list another clinic's appointments."""
        global _test_counter
        _test_counter += 1
        slug2 = f"other-clinic-{_test_counter}"
        other = Clinic(
            slug=slug2, name="Other", specialty="Dental",
            email=f"{slug2}@test.com", subscription_status="active",
            plan="professional", customer_password_hash=hash_password("pass"),
            is_active=True,
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        r = client.get(f"/api/{other.slug}/appointments",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 403
        db.query(Clinic).filter(Clinic.id == other.id).delete()
        db.commit()


# ── Update Appointment Status ────────────────────────────────────────────────

class TestAppointmentStatusUpdate:

    def test_update_to_confirmed(self, client, clinic, token, seeded_appointment):
        r = client.patch(
            f"/api/{clinic.slug}/appointments/{seeded_appointment.confirmation_number}",
            json={"status": "confirmed"},
            headers={"X-Clinic-Token": token},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"

    def test_update_to_no_show(self, client, clinic, token, seeded_appointment):
        r = client.patch(
            f"/api/{clinic.slug}/appointments/{seeded_appointment.confirmation_number}",
            json={"status": "no_show"},
            headers={"X-Clinic-Token": token},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "no_show"

    def test_update_to_completed(self, client, clinic, token, seeded_appointment):
        r = client.patch(
            f"/api/{clinic.slug}/appointments/{seeded_appointment.confirmation_number}",
            json={"status": "completed"},
            headers={"X-Clinic-Token": token},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_update_to_cancelled(self, client, clinic, token, seeded_appointment):
        r = client.patch(
            f"/api/{clinic.slug}/appointments/{seeded_appointment.confirmation_number}",
            json={"status": "cancelled"},
            headers={"X-Clinic-Token": token},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

    def test_invalid_status_rejected(self, client, clinic, token, seeded_appointment):
        r = client.patch(
            f"/api/{clinic.slug}/appointments/{seeded_appointment.confirmation_number}",
            json={"status": "flying"},
            headers={"X-Clinic-Token": token},
        )
        assert r.status_code == 400

    def test_nonexistent_appointment_returns_404(self, client, clinic, token):
        r = client.patch(
            f"/api/{clinic.slug}/appointments/FAKE-000",
            json={"status": "confirmed"},
            headers={"X-Clinic-Token": token},
        )
        assert r.status_code == 404

    def test_update_requires_auth(self, client, clinic, seeded_appointment):
        r = client.patch(
            f"/api/{clinic.slug}/appointments/{seeded_appointment.confirmation_number}",
            json={"status": "confirmed"},
        )
        assert r.status_code == 403


# ── Clinic Config ────────────────────────────────────────────────────────────

class TestClinicConfig:

    def test_config_returns_agent_name(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/config")
        assert r.status_code == 200
        data = r.json()
        assert "agent_name" in data
        assert "clinic_name" in data
        assert "specialty" in data

    def test_config_for_unknown_clinic(self, client):
        r = client.get("/api/nonexistent-clinic-xyz/config")
        assert r.status_code == 404


# ── Plan Endpoint ─────────────────────────────────────────────────────────────

class TestPlanEndpoint:

    def test_plan_returns_details(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/plan",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        data = r.json()
        assert "plan_name" in data
        assert "price" in data
        assert "conversations_used" in data
        assert "features" in data

    def test_plan_requires_auth(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/plan")
        assert r.status_code == 403


# ── Cancel Subscription ───────────────────────────────────────────────────────

class TestCancelSubscription:

    def test_cancel_active_subscription(self, client, db):
        global _test_counter
        _test_counter += 1
        slug = f"cancel-test-{_test_counter}"
        c = Clinic(
            slug=slug, name="Cancel Test", specialty="Dental",
            email=f"{slug}@test.com", subscription_status="active",
            plan="professional", customer_password_hash=hash_password("testpass123"),
            is_active=True, subscription_ends_at=datetime.utcnow() + timedelta(days=30),
        )
        db.add(c); db.commit(); db.refresh(c)
        r_login = TestClient(app, raise_server_exceptions=False).post(
            "/api/clinic-auth/login", json={"email": c.email, "password": "testpass123"})
        tok = r_login.json()["token"]
        r = TestClient(app, raise_server_exceptions=False).post(
            f"/api/{slug}/cancel-subscription", headers={"X-Clinic-Token": tok})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        db.query(Clinic).filter(Clinic.id == c.id).delete(); db.commit()

    def test_cancel_already_cancelled_returns_400(self, client, db):
        global _test_counter
        _test_counter += 1
        slug = f"cancel-test2-{_test_counter}"
        c = Clinic(
            slug=slug, name="Cancel Test2", specialty="Dental",
            email=f"{slug}@test.com", subscription_status="cancelled",
            plan="professional", customer_password_hash=hash_password("testpass123"),
            is_active=True,
        )
        db.add(c); db.commit(); db.refresh(c)
        r_login = TestClient(app, raise_server_exceptions=False).post(
            "/api/clinic-auth/login", json={"email": c.email, "password": "testpass123"})
        tok = r_login.json()["token"]
        r = TestClient(app, raise_server_exceptions=False).post(
            f"/api/{slug}/cancel-subscription", headers={"X-Clinic-Token": tok})
        assert r.status_code == 400
        db.query(Clinic).filter(Clinic.id == c.id).delete(); db.commit()

    def test_cancel_trial_returns_400(self, client, db):
        global _test_counter
        _test_counter += 1
        slug = f"cancel-trial-{_test_counter}"
        c = Clinic(
            slug=slug, name="Trial Cancel", specialty="Dental",
            email=f"{slug}@test.com", subscription_status="trial",
            plan="starter", customer_password_hash=hash_password("testpass123"),
            is_active=True, trial_ends_at=datetime.utcnow() + timedelta(days=7),
        )
        db.add(c); db.commit(); db.refresh(c)
        r_login = TestClient(app, raise_server_exceptions=False).post(
            "/api/clinic-auth/login", json={"email": c.email, "password": "testpass123"})
        tok = r_login.json()["token"]
        r = TestClient(app, raise_server_exceptions=False).post(
            f"/api/{slug}/cancel-subscription", headers={"X-Clinic-Token": tok})
        assert r.status_code == 400
        db.query(Clinic).filter(Clinic.id == c.id).delete(); db.commit()


# ── Regression REG-002: appointments visible in portal after Aria books via chat ─
# Bug: Portal showed "Failed to load appointments" even after Aria confirmed booking.
# Root causes:
#   1. signup.py create_clinic omitted is_active=True → potential NULL in DB
#      → get_clinic_by_token filtered is_active IS TRUE → returned None → 403
#   2. loadAppts() JS called r.json() without checking r.ok → non-array JSON
#      → silent "Failed to load appointments" with no useful feedback
# Fixes: explicit is_active=True in signup; r.ok check with actionable message.

class TestAppointmentPortalVisibility:

    def test_appointment_seeded_via_db_appears_in_portal(self, client, clinic, token, db):
        """Appointment written to DB (as Aria's book_appointment tool does) must be
        returned by the portal's /appointments endpoint as a JSON array."""
        from backend.db.models import Appointment as ApptModel
        appt = ApptModel(
            clinic_id=clinic.id,
            confirmation_number="REG-002-SEED",
            patient_name="John Smith",
            appointment_type="New Patient",
            appointment_datetime="Monday at 10:00 AM",
            provider="Dr. Smith",
            status="scheduled",
            channel="web",
        )
        db.add(appt)
        db.commit()

        r = client.get(f"/api/{clinic.slug}/appointments",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200, f"Portal appointments returned {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list), "Expected JSON array from appointments endpoint"
        conf_nums = [a["confirmation_number"] for a in data]
        assert "REG-002-SEED" in conf_nums, "Booked appointment not found in portal list"

        db.query(ApptModel).filter(ApptModel.id == appt.id).delete()
        db.commit()

    def test_appointments_returns_json_array_not_dict(self, client, clinic, token):
        """Appointments endpoint always returns a JSON array when auth is valid."""
        r = client.get(f"/api/{clinic.slug}/appointments",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        assert isinstance(r.json(), list), "Response must be a list, not a dict"

    def test_appointments_unauthenticated_returns_403_json(self, client, clinic):
        """Unauthenticated portal request returns 403 with JSON error body."""
        r = client.get(f"/api/{clinic.slug}/appointments")
        assert r.status_code == 403
        body = r.json()
        assert "error" in body or "detail" in body

    def test_signup_clinic_is_active_true(self, client, db):
        """Clinic created via /api/signup must have is_active=True."""
        r = client.post("/api/signup", json={
            "practice_name": "Reg002 Test Clinic",
            "contact_email":  "reg002@testclinic.com",
            "password":        "password123",
            "specialty":       "Family Medicine",
        })
        assert r.status_code == 200
        slug = r.json()["slug"]
        from backend.db.crud import get_clinic
        clinic_obj = get_clinic(db, slug)
        assert clinic_obj is not None
        assert clinic_obj.is_active is True, "Clinic from /api/signup must have is_active=True"
        db.query(Clinic).filter(Clinic.id == clinic_obj.id).delete()
        db.commit()
