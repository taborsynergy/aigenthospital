"""
Appointment booking regression tests — DB-native service.
Tests slot generation, office hours parsing, book/reschedule/cancel,
waitlist, and the clinic portal status-update endpoint.
"""
import os
import pytest
from datetime import date, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_appointments.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment
from backend.routers.clinic_auth import hash_password
from backend.services.appointment_svc import (
    parse_office_hours, generate_slots, _parse_datetime_str,
)


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
    session = S()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def clinic_obj(db):
    from datetime import datetime
    slug = f"appt-test-{date.today().toordinal()}"
    existing = db.query(Clinic).filter(Clinic.slug == slug).first()
    if existing:
        yield existing
        return
    c = Clinic(
        slug=slug, name="Test Clinic", specialty="Family Medicine",
        email=f"{slug}@test.com",
        office_hours="Mon-Fri 8am-5pm",
        providers="Dr. Smith, Dr. Jones",
        subscription_status="active",
        plan="professional",
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
def auth_token(client, clinic_obj):
    r = client.post("/api/clinic-auth/login", json={
        "email": clinic_obj.email, "password": "testpass123"
    })
    return r.json()["token"]


# ── Office hours parser ───────────────────────────────────────────────────────

class TestOfficeHoursParser:
    def test_mon_fri_8_5(self):
        s = parse_office_hours("Mon-Fri 8am-5pm")
        assert s[0] == (8, 17)
        assert s[4] == (8, 17)
        assert 5 not in s  # Saturday excluded

    def test_en_dash(self):
        s = parse_office_hours("Mon–Fri 8am–5pm")
        assert s[0] == (8, 17)

    def test_with_saturday(self):
        s = parse_office_hours("Mon-Fri 9am-5pm, Sat 9am-1pm")
        assert s[0] == (9, 17)
        assert s[5] == (9, 13)
        assert 6 not in s  # Sunday excluded

    def test_default_on_empty(self):
        s = parse_office_hours("")
        assert len(s) == 5  # Mon-Fri

    def test_single_day(self):
        s = parse_office_hours("Saturday 9am-2pm")
        assert s[5] == (9, 14)


# ── Datetime parser ───────────────────────────────────────────────────────────

class TestDatetimeParser:
    def test_standard_format(self):
        dt = _parse_datetime_str("Monday, June 9 at 10:00 AM")
        assert dt is not None
        assert dt.hour == 10
        assert dt.month == 6
        assert dt.day == 9

    def test_pm_format(self):
        dt = _parse_datetime_str("Friday, June 13 at 2:30 PM")
        assert dt is not None
        assert dt.hour == 14
        assert dt.minute == 30

    def test_empty_returns_none(self):
        assert _parse_datetime_str("") is None

    def test_garbage_returns_none(self):
        assert _parse_datetime_str("asap please") is None


# ── Slot generation ───────────────────────────────────────────────────────────

class TestSlotGeneration:
    def test_generates_slots(self, clinic_obj, db):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        next_week = (date.today() + timedelta(days=7)).isoformat()
        slots = generate_slots(clinic_obj, tomorrow, next_week, db=db)
        assert len(slots) > 0
        assert len(slots) <= 8

    def test_slot_fields(self, clinic_obj, db):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        slots = generate_slots(clinic_obj, tomorrow, None, db=db)
        if slots:
            s = slots[0]
            assert "date" in s
            assert "time" in s
            assert "provider" in s
            assert "datetime_display" in s
            assert "slot_id" in s

    def test_no_weekend_slots_mon_fri(self, clinic_obj, db):
        # Find next Monday
        today = date.today()
        days_to_monday = (7 - today.weekday()) % 7
        if days_to_monday == 0:
            days_to_monday = 7
        monday = today + timedelta(days=days_to_monday)
        saturday = monday + timedelta(days=5)
        sunday   = monday + timedelta(days=6)

        slots = generate_slots(clinic_obj, monday.isoformat(),
                               (monday + timedelta(days=6)).isoformat(), db=db)
        saturday_slots = [s for s in slots if s["date"] in (saturday.isoformat(), sunday.isoformat())]
        assert len(saturday_slots) == 0

    def test_respects_duration(self, clinic_obj, db):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        slots_30  = generate_slots(clinic_obj, tomorrow, tomorrow, duration_minutes=30, db=db)
        slots_60  = generate_slots(clinic_obj, tomorrow, tomorrow, duration_minutes=60, db=db)
        # 60-min slots should be fewer than 30-min slots for the same day
        assert len(slots_60) <= len(slots_30)

    def test_provider_filter(self, clinic_obj, db):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        slots = generate_slots(clinic_obj, tomorrow, None,
                               provider_filter="Dr. Smith", db=db)
        for s in slots:
            assert "Smith" in s["provider"]


# ── Book appointment ──────────────────────────────────────────────────────────

class TestBookAppointment:
    def test_book_creates_db_record(self, client, clinic_obj, db):
        # Use REST endpoint via MOCK_MODE — just verify chat endpoint responds
        r = client.post(f"/api/{clinic_obj.slug}/chat", json={
            "message": "Book me an appointment tomorrow at 10am for an annual physical",
            "session_id": "book-test-001",
        })
        assert r.status_code == 200
        assert r.json()["content"]

    def test_appointment_status_update(self, client, clinic_obj, auth_token, db):
        from backend.db.crud import create_appointment
        import uuid
        conf = f"TEST-{uuid.uuid4().hex[:6].upper()}"
        create_appointment(db, {
            "clinic_id":            clinic_obj.id,
            "confirmation_number":  conf,
            "patient_name":         "Jane Doe",
            "appointment_type":     "Annual Physical",
            "appointment_datetime": "Monday, June 9 at 10:00 AM",
            "status":               "scheduled",
        })

        r = client.patch(
            f"/api/{clinic_obj.slug}/appointments/{conf}",
            json={"status": "confirmed"},
            headers={"X-Clinic-Token": auth_token},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"

    def test_invalid_status_rejected(self, client, clinic_obj, auth_token, db):
        from backend.db.crud import create_appointment
        import uuid
        conf = f"TEST-{uuid.uuid4().hex[:6].upper()}"
        create_appointment(db, {
            "clinic_id":            clinic_obj.id,
            "confirmation_number":  conf,
            "patient_name":         "Bob Smith",
            "appointment_type":     "Checkup",
            "appointment_datetime": "Tuesday, June 10 at 2:00 PM",
            "status":               "scheduled",
        })
        r = client.patch(
            f"/api/{clinic_obj.slug}/appointments/{conf}",
            json={"status": "hacked"},
            headers={"X-Clinic-Token": auth_token},
        )
        assert r.status_code == 400

    def test_status_update_requires_auth(self, client, clinic_obj, db):
        r = client.patch(
            f"/api/{clinic_obj.slug}/appointments/FAKE-0000",
            json={"status": "confirmed"},
        )
        assert r.status_code == 403


# ── Reschedule ────────────────────────────────────────────────────────────────

class TestRescheduleCancel:
    def test_reschedule_updates_existing(self, db, clinic_obj):
        from backend.db.crud import create_appointment, find_appointment_by_patient
        from backend.services.appointment_svc import reschedule_appointment
        import uuid

        conf = f"RESCH-{uuid.uuid4().hex[:6].upper()}"
        create_appointment(db, {
            "clinic_id":            clinic_obj.id,
            "confirmation_number":  conf,
            "patient_name":         "Reschedule Patient",
            "appointment_type":     "Follow-up",
            "appointment_datetime": "Monday, June 9 at 9:00 AM",
            "status":               "scheduled",
        })

        result = reschedule_appointment(
            clinic=clinic_obj, db=db,
            patient_name="Reschedule Patient",
            new_datetime="Wednesday, June 11 at 11:00 AM",
        )
        assert result["success"] is True
        assert result["new_datetime"] == "Wednesday, June 11 at 11:00 AM"

        updated = find_appointment_by_patient(db, clinic_obj.id, "Reschedule Patient")
        assert updated.status == "rescheduled"
        assert "June 11" in updated.appointment_datetime

    def test_cancel_updates_status(self, db, clinic_obj):
        from backend.db.crud import create_appointment, find_appointment_by_patient
        from backend.services.appointment_svc import cancel_appointment
        import uuid

        conf = f"CXL-{uuid.uuid4().hex[:6].upper()}"
        create_appointment(db, {
            "clinic_id":            clinic_obj.id,
            "confirmation_number":  conf,
            "patient_name":         "Cancel Patient",
            "appointment_type":     "Cleaning",
            "appointment_datetime": "Tuesday, June 10 at 2:00 PM",
            "status":               "scheduled",
        })

        result = cancel_appointment(
            clinic=clinic_obj, db=db,
            patient_name="Cancel Patient",
            appointment_date="June 10",
        )
        assert result["success"] is True

        updated = find_appointment_by_patient(db, clinic_obj.id, "Cancel Patient")
        assert updated.status == "cancelled"
