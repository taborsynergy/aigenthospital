"""Phase 2 Clinic Setup tests — Appointment Types, Holidays, Notification Preferences."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_phase2.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, AppointmentType, ClinicHoliday
from backend.routers.clinic_auth import hash_password

_ctr = 0


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
    global _ctr
    _ctr += 1
    slug = f"p2-clinic-{_ctr}"
    c = Clinic(
        slug=slug, name=f"Phase2 Clinic {_ctr}", specialty="Family Medicine",
        email=f"{slug}@test.com", phone="5551234567",
        subscription_status="active", plan="professional",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c); db.commit(); db.refresh(c)
    yield c
    db.query(AppointmentType).filter(AppointmentType.clinic_id == c.id).delete()
    db.query(ClinicHoliday).filter(ClinicHoliday.clinic_id == c.id).delete()
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def token(client, clinic):
    r = client.post("/api/clinic-auth/login",
                    json={"email": clinic.email, "password": "testpass123"})
    return r.json()["token"]


# ── Appointment Types ─────────────────────────────────────────────────────────

class TestAppointmentTypes:

    def test_list_empty_initially(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/appointment-types",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        assert r.json()["appointment_types"] == []

    def test_create_appointment_type(self, client, clinic, token):
        r = client.post(f"/api/{clinic.slug}/appointment-types",
                        json={"name": "New Patient Visit", "duration_minutes": 60,
                              "description": "First-time visit, full exam"},
                        headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "New Patient Visit"
        assert d["duration_minutes"] == 60
        assert "id" in d

    def test_list_shows_created_type(self, client, clinic, token):
        client.post(f"/api/{clinic.slug}/appointment-types",
                    json={"name": "Follow-up", "duration_minutes": 30},
                    headers={"X-Clinic-Token": token})
        r = client.get(f"/api/{clinic.slug}/appointment-types",
                       headers={"X-Clinic-Token": token})
        names = [t["name"] for t in r.json()["appointment_types"]]
        assert "Follow-up" in names

    def test_update_appointment_type(self, client, clinic, token):
        r = client.post(f"/api/{clinic.slug}/appointment-types",
                        json={"name": "Annual Physical", "duration_minutes": 45},
                        headers={"X-Clinic-Token": token})
        appt_id = r.json()["id"]
        r2 = client.patch(f"/api/{clinic.slug}/appointment-types/{appt_id}",
                          json={"name": "Annual Physical (Updated)", "duration_minutes": 60},
                          headers={"X-Clinic-Token": token})
        assert r2.status_code == 200
        assert r2.json()["name"] == "Annual Physical (Updated)"
        assert r2.json()["duration_minutes"] == 60

    def test_delete_appointment_type(self, client, clinic, token):
        r = client.post(f"/api/{clinic.slug}/appointment-types",
                        json={"name": "Sick Visit", "duration_minutes": 15},
                        headers={"X-Clinic-Token": token})
        appt_id = r.json()["id"]
        r2 = client.delete(f"/api/{clinic.slug}/appointment-types/{appt_id}",
                           headers={"X-Clinic-Token": token})
        assert r2.status_code == 200
        assert r2.json()["ok"] is True
        # Verify it's gone
        r3 = client.get(f"/api/{clinic.slug}/appointment-types",
                        headers={"X-Clinic-Token": token})
        ids = [t["id"] for t in r3.json()["appointment_types"]]
        assert appt_id not in ids

    def test_create_requires_auth(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/appointment-types",
                        json={"name": "Test", "duration_minutes": 30})
        assert r.status_code == 403

    def test_empty_name_rejected(self, client, clinic, token):
        r = client.post(f"/api/{clinic.slug}/appointment-types",
                        json={"name": "", "duration_minutes": 30},
                        headers={"X-Clinic-Token": token})
        assert r.status_code == 400

    def test_cross_clinic_isolation(self, client, db, token):
        """Appointment type from clinic A cannot be accessed by clinic B's token."""
        global _ctr
        _ctr += 1
        slug2 = f"p2-other-{_ctr}"
        other = Clinic(
            slug=slug2, name="Other", specialty="Dental",
            email=f"{slug2}@test.com", subscription_status="active",
            plan="professional", customer_password_hash=hash_password("pass"),
            is_active=True,
        )
        db.add(other); db.commit(); db.refresh(other)
        r = client.get(f"/api/{other.slug}/appointment-types",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 403
        db.query(Clinic).filter(Clinic.id == other.id).delete(); db.commit()

    def test_system_prompt_contains_appointment_types(self, clinic, db):
        """build_system_prompt includes configured appointment types."""
        from backend.agent.prompts import build_system_prompt
        at = AppointmentType(
            clinic_id=clinic.id,
            name="Telehealth Visit",
            duration_minutes=30,
            description="Virtual consultation",
            is_active=True,
        )
        db.add(at); db.commit()
        clinic._db = db
        prompt = build_system_prompt(clinic, db=db)
        assert "Telehealth Visit" in prompt
        assert "30 min" in prompt
        db.query(AppointmentType).filter(AppointmentType.id == at.id).delete(); db.commit()


# ── Clinic Holidays ───────────────────────────────────────────────────────────

class TestClinicHolidays:

    def test_list_empty_initially(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/holidays",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        assert r.json()["holidays"] == []

    def test_add_holiday(self, client, clinic, token):
        r = client.post(f"/api/{clinic.slug}/holidays",
                        json={"date": "2026-07-04", "reason": "Independence Day"},
                        headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        d = r.json()
        assert d["date"] == "2026-07-04"
        assert d["reason"] == "Independence Day"
        assert "id" in d

    def test_holiday_appears_in_list(self, client, clinic, token):
        client.post(f"/api/{clinic.slug}/holidays",
                    json={"date": "2026-12-25", "reason": "Christmas"},
                    headers={"X-Clinic-Token": token})
        r = client.get(f"/api/{clinic.slug}/holidays",
                       headers={"X-Clinic-Token": token})
        dates = [h["date"] for h in r.json()["holidays"]]
        assert "2026-12-25" in dates

    def test_duplicate_date_rejected(self, client, clinic, token):
        client.post(f"/api/{clinic.slug}/holidays",
                    json={"date": "2026-11-26", "reason": "Thanksgiving"},
                    headers={"X-Clinic-Token": token})
        r = client.post(f"/api/{clinic.slug}/holidays",
                        json={"date": "2026-11-26", "reason": "Thanksgiving again"},
                        headers={"X-Clinic-Token": token})
        assert r.status_code == 409

    def test_invalid_date_format_rejected(self, client, clinic, token):
        r = client.post(f"/api/{clinic.slug}/holidays",
                        json={"date": "July 4 2026"},
                        headers={"X-Clinic-Token": token})
        assert r.status_code == 400

    def test_delete_holiday(self, client, clinic, token):
        r = client.post(f"/api/{clinic.slug}/holidays",
                        json={"date": "2026-09-07", "reason": "Labor Day"},
                        headers={"X-Clinic-Token": token})
        hol_id = r.json()["id"]
        r2 = client.delete(f"/api/{clinic.slug}/holidays/{hol_id}",
                           headers={"X-Clinic-Token": token})
        assert r2.status_code == 200
        assert r2.json()["ok"] is True
        r3 = client.get(f"/api/{clinic.slug}/holidays",
                        headers={"X-Clinic-Token": token})
        ids = [h["id"] for h in r3.json()["holidays"]]
        assert hol_id not in ids

    def test_add_holiday_requires_auth(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/holidays",
                        json={"date": "2026-08-10"})
        assert r.status_code == 403

    def test_system_prompt_contains_holidays(self, clinic, db):
        """build_system_prompt includes closed dates so Aria never offers them."""
        from backend.agent.prompts import build_system_prompt
        h = ClinicHoliday(
            clinic_id=clinic.id, date="2026-07-04", reason="Independence Day"
        )
        db.add(h); db.commit()
        clinic._db = db
        prompt = build_system_prompt(clinic, db=db)
        assert "2026-07-04" in prompt
        assert "NEVER" in prompt
        db.query(ClinicHoliday).filter(ClinicHoliday.id == h.id).delete(); db.commit()


# ── Notification Preferences ──────────────────────────────────────────────────

class TestNotificationPreferences:

    def test_profile_returns_notification_fields(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/profile",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        d = r.json()
        assert "reminder_72h_enabled" in d
        assert "reminder_24h_enabled" in d
        assert "custom_confirmation_msg" in d

    def test_profile_returns_agent_name(self, client, clinic, token):
        """Profile GET must return agent_name (was missing before Phase 2 fix)."""
        r = client.get(f"/api/{clinic.slug}/profile",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        assert "agent_name" in r.json()

    def test_notification_defaults_are_enabled(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/profile",
                       headers={"X-Clinic-Token": token})
        d = r.json()
        assert d["reminder_72h_enabled"] is True
        assert d["reminder_24h_enabled"] is True

    def test_disable_72h_reminder(self, client, clinic, token):
        r = client.patch(f"/api/{clinic.slug}/profile",
                         json={"reminder_72h_enabled": False},
                         headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        # Verify persisted
        r2 = client.get(f"/api/{clinic.slug}/profile",
                        headers={"X-Clinic-Token": token})
        assert r2.json()["reminder_72h_enabled"] is False

    def test_save_custom_confirmation_message(self, client, clinic, token):
        msg = "Please arrive 10 minutes early and bring your insurance card."
        r = client.patch(f"/api/{clinic.slug}/profile",
                         json={"custom_confirmation_msg": msg},
                         headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        r2 = client.get(f"/api/{clinic.slug}/profile",
                        headers={"X-Clinic-Token": token})
        assert r2.json()["custom_confirmation_msg"] == msg

    def test_toggle_both_reminders_off(self, client, clinic, token):
        r = client.patch(f"/api/{clinic.slug}/profile",
                         json={"reminder_72h_enabled": False,
                               "reminder_24h_enabled": False},
                         headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        r2 = client.get(f"/api/{clinic.slug}/profile",
                        headers={"X-Clinic-Token": token})
        d = r2.json()
        assert d["reminder_72h_enabled"] is False
        assert d["reminder_24h_enabled"] is False

    def test_notif_prefs_requires_auth(self, client, clinic):
        r = client.patch(f"/api/{clinic.slug}/profile",
                         json={"reminder_72h_enabled": False})
        assert r.status_code == 403
