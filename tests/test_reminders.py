"""
Appointment reminder tests.
Covers: booking confirmation SMS trigger, 72h/24h reminder detection,
YES/NO SMS reply handling, and the /api/reminders/trigger endpoint.
"""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_reminders.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment
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
def pro_clinic(db):
    """Professional plan clinic with Twilio number (SMS-capable)."""
    slug = "reminder-test-pro"
    existing = db.query(Clinic).filter(Clinic.slug == slug).first()
    if existing:
        yield existing
        return
    c = Clinic(
        slug=slug, name="Reminder Test Clinic", specialty="Family Medicine",
        email="reminder@test.com", phone="5550001111",
        twilio_phone="+15559999999",
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
    db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
    db.delete(c)
    db.commit()


@pytest.fixture
def starter_clinic(db):
    """Starter plan clinic — SMS NOT included."""
    slug = "reminder-test-starter"
    existing = db.query(Clinic).filter(Clinic.slug == slug).first()
    if existing:
        yield existing
        return
    c = Clinic(
        slug=slug, name="Starter Test Clinic", specialty="Dental",
        email="starter@test.com",
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
    db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
    db.delete(c)
    db.commit()


def _make_appt(db, clinic, hours_from_now: float, phone: str = "+15551234567",
               status: str = "scheduled", **overrides) -> Appointment:
    import uuid
    conf = f"REM-{uuid.uuid4().hex[:6].upper()}"
    ts   = datetime.utcnow() + timedelta(hours=hours_from_now)
    data = dict(
        clinic_id=clinic.id,
        confirmation_number=conf,
        patient_name="Test Patient",
        patient_phone=phone,
        appointment_type="Annual Physical",
        appointment_datetime=ts.strftime("%A, %B %-d at %-I:%M %p") if False
            else f"{ts.strftime('%A, %B')} {ts.day} at {ts.hour % 12 or 12}:00 {'AM' if ts.hour < 12 else 'PM'}",
        appointment_ts=ts,
        provider="Dr. Smith",
        status=status,
        reminder_72h_sent=False,
        reminder_24h_sent=False,
        confirmation_sent=False,
    )
    data.update(overrides)
    from backend.db.crud import create_appointment
    return create_appointment(db, data)


# ── Plan gating ───────────────────────────────────────────────────────────────

class TestPlanGating:
    def test_pro_clinic_can_use_sms(self, pro_clinic):
        from backend.plans import can_use_sms
        assert can_use_sms(pro_clinic) is True

    def test_starter_clinic_cannot_use_sms(self, starter_clinic):
        from backend.plans import can_use_sms
        assert can_use_sms(starter_clinic) is False


# ── Reminder detection ────────────────────────────────────────────────────────

class TestReminderDetection:
    def test_72h_due_detected(self, db, pro_clinic):
        from backend.services.reminders_svc import _find_due
        appt = _make_appt(db, pro_clinic, hours_from_now=72.0)
        due = _find_due(db, pro_clinic.id, hours_before=72, sent_flag="reminder_72h_sent")
        conf_nums = [a.confirmation_number for a in due]
        assert appt.confirmation_number in conf_nums

    def test_24h_due_detected(self, db, pro_clinic):
        from backend.services.reminders_svc import _find_due
        appt = _make_appt(db, pro_clinic, hours_from_now=24.0)
        due = _find_due(db, pro_clinic.id, hours_before=24, sent_flag="reminder_24h_sent")
        conf_nums = [a.confirmation_number for a in due]
        assert appt.confirmation_number in conf_nums

    def test_already_sent_not_detected(self, db, pro_clinic):
        from backend.services.reminders_svc import _find_due
        appt = _make_appt(db, pro_clinic, hours_from_now=72.0,
                          reminder_72h_sent=True)
        due = _find_due(db, pro_clinic.id, hours_before=72, sent_flag="reminder_72h_sent")
        conf_nums = [a.confirmation_number for a in due]
        assert appt.confirmation_number not in conf_nums

    def test_cancelled_appt_not_reminded(self, db, pro_clinic):
        from backend.services.reminders_svc import _find_due
        appt = _make_appt(db, pro_clinic, hours_from_now=72.0, status="cancelled")
        due = _find_due(db, pro_clinic.id, hours_before=72, sent_flag="reminder_72h_sent")
        conf_nums = [a.confirmation_number for a in due]
        assert appt.confirmation_number not in conf_nums

    def test_no_phone_not_reminded(self, db, pro_clinic):
        from backend.services.reminders_svc import _find_due
        appt = _make_appt(db, pro_clinic, hours_from_now=72.0, phone="")
        due = _find_due(db, pro_clinic.id, hours_before=72, sent_flag="reminder_72h_sent")
        conf_nums = [a.confirmation_number for a in due]
        assert appt.confirmation_number not in conf_nums

    def test_far_future_not_detected(self, db, pro_clinic):
        from backend.services.reminders_svc import _find_due
        appt = _make_appt(db, pro_clinic, hours_from_now=120.0)  # 5 days away
        due = _find_due(db, pro_clinic.id, hours_before=72, sent_flag="reminder_72h_sent")
        conf_nums = [a.confirmation_number for a in due]
        assert appt.confirmation_number not in conf_nums


# ── YES/NO reply handling ─────────────────────────────────────────────────────

class TestSmsReplyHandling:
    def test_yes_confirms_appointment(self, db, pro_clinic):
        from backend.services.reminders_svc import handle_sms_reply
        appt = _make_appt(db, pro_clinic, hours_from_now=24.0,
                          phone="+15550001234")
        result = handle_sms_reply(db, pro_clinic, "+15550001234", "YES")
        assert result is not None
        assert "Confirmed" in result
        db.refresh(appt)
        assert appt.status == "confirmed"

    def test_no_cancels_appointment(self, db, pro_clinic):
        from backend.services.reminders_svc import handle_sms_reply
        appt = _make_appt(db, pro_clinic, hours_from_now=48.0,
                          phone="+15550001235")
        result = handle_sms_reply(db, pro_clinic, "+15550001235", "NO")
        assert result is not None
        assert "cancelled" in result.lower()
        db.refresh(appt)
        assert appt.status == "cancelled"

    def test_y_is_accepted(self, db, pro_clinic):
        from backend.services.reminders_svc import handle_sms_reply
        appt = _make_appt(db, pro_clinic, hours_from_now=36.0,
                          phone="+15550001236")
        result = handle_sms_reply(db, pro_clinic, "+15550001236", "y")
        assert result is not None
        db.refresh(appt)
        assert appt.status == "confirmed"

    def test_unrecognised_reply_returns_none(self, db, pro_clinic):
        from backend.services.reminders_svc import handle_sms_reply
        result = handle_sms_reply(db, pro_clinic, "+15550009999", "What time is my appointment?")
        assert result is None  # falls through to Aria

    def test_no_appointment_returns_none(self, db, pro_clinic):
        from backend.services.reminders_svc import handle_sms_reply
        result = handle_sms_reply(db, pro_clinic, "+10000000000", "YES")
        assert result is None


# ── API endpoint ──────────────────────────────────────────────────────────────

class TestRemindersEndpoint:
    def test_trigger_requires_admin(self, client):
        r = client.post("/api/reminders/trigger")
        assert r.status_code == 401

    def test_trigger_wrong_password(self, client):
        r = client.post("/api/reminders/trigger",
                        headers={"X-Admin-Password": "wrongpassword"})
        assert r.status_code == 401

    def test_trigger_success(self, client):
        r = client.post("/api/reminders/trigger",
                        headers={"X-Admin-Password": "test-admin-secret"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "sent_72h" in data
        assert "sent_24h" in data
        assert "errors" in data

    def test_resend_confirmation_not_found(self, client):
        r = client.post("/api/reminders/send-confirmation/FAKE-XXXX",
                        headers={"X-Admin-Password": "test-admin-secret"})
        assert r.status_code == 404
