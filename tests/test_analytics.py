"""
Analytics dashboard tests — real data computation from the DB.
Covers: each report type, format_for_aria text generation, REST endpoint,
conversation limit tracking, and provider breakdown.
"""
import os
import pytest
from datetime import date, datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_analytics.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, UsageLog
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


def _make_clinic(db, slug="analytics-test", plan="professional"):
    existing = db.query(Clinic).filter(Clinic.slug == slug).first()
    if existing:
        return existing
    c = Clinic(
        slug=slug, name="Analytics Clinic", specialty="Family Medicine",
        email=f"{slug}@test.com", phone="5550001234",
        subscription_status="active", plan=plan,
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        providers="Dr. Smith, Dr. Jones",
        trial_ends_at=datetime.utcnow() + timedelta(days=30),
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_appt(db, clinic, hours_offset: float, status="scheduled",
               provider="Dr. Smith", appt_type="Annual Physical",
               phone="+15550001111", is_new=False) -> Appointment:
    import uuid
    ts = datetime.utcnow() + timedelta(hours=hours_offset)
    a = Appointment(
        clinic_id=clinic.id,
        confirmation_number=f"ANA-{uuid.uuid4().hex[:6].upper()}",
        patient_name="Test Patient",
        patient_phone=phone,
        appointment_type=appt_type,
        appointment_datetime=f"{ts.strftime('%A, %B')} {ts.day} at 10:00 AM",
        appointment_ts=ts,
        provider=provider,
        status=status,
        is_new_patient=is_new,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_usage(db, clinic, sessions=5):
    import uuid
    for i in range(sessions):
        db.add(UsageLog(
            clinic_id=clinic.id,
            session_id=f"sess-{uuid.uuid4().hex[:8]}",
            channel="web",
            input_tokens=100,
            output_tokens=200,
        ))
    db.commit()


@pytest.fixture
def analytics_clinic(db):
    c = _make_clinic(db, "analytics-test-pro")
    yield c
    db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
    db.query(UsageLog).filter(UsageLog.clinic_id == c.id).delete()
    db.delete(c)
    db.commit()


@pytest.fixture
def auth_token(client, analytics_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": analytics_clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


# ── Today's appointments ──────────────────────────────────────────────────────

class TestTodayAppointments:
    def test_empty_returns_zero(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_today_appointments
        result = get_today_appointments(db, analytics_clinic.id)
        assert isinstance(result["total"], int)
        assert "date" in result

    def test_counts_today_appointments(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_today_appointments
        _make_appt(db, analytics_clinic, hours_offset=1, status="scheduled")
        _make_appt(db, analytics_clinic, hours_offset=2, status="confirmed")
        _make_appt(db, analytics_clinic, hours_offset=3, status="completed")
        result = get_today_appointments(db, analytics_clinic.id)
        assert result["total"] >= 3
        assert result["scheduled"] >= 1
        assert result["confirmed"] >= 1
        assert result["completed"] >= 1

    def test_no_show_counted(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_today_appointments
        _make_appt(db, analytics_clinic, hours_offset=-1, status="no_show")
        result = get_today_appointments(db, analytics_clinic.id)
        assert result["no_show"] >= 1
        assert len(result["no_show_details"]) >= 1

    def test_provider_breakdown_populated(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_today_appointments
        _make_appt(db, analytics_clinic, hours_offset=4, provider="Dr. Jones")
        result = get_today_appointments(db, analytics_clinic.id)
        assert "by_provider" in result


# ── Weekly summary ────────────────────────────────────────────────────────────

class TestWeeklySummary:
    def test_returns_expected_keys(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_weekly_summary
        result = get_weekly_summary(db, analytics_clinic.id)
        assert "total" in result
        assert "by_day" in result
        assert "daily_average" in result
        assert "peak_day" in result

    def test_this_week_appt_counted(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_weekly_summary
        _make_appt(db, analytics_clinic, hours_offset=0)
        result = get_weekly_summary(db, analytics_clinic.id)
        assert result["total"] >= 1


# ── Monthly summary ───────────────────────────────────────────────────────────

class TestMonthlySummary:
    def test_returns_kpis(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_monthly_summary
        result = get_monthly_summary(db, analytics_clinic.id)
        assert "month" in result
        assert "cancellation_rate" in result
        assert "no_show_rate" in result
        assert "new_patient_rate" in result

    def test_new_patient_flag(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_monthly_summary
        _make_appt(db, analytics_clinic, hours_offset=0, is_new=True)
        result = get_monthly_summary(db, analytics_clinic.id)
        assert result["new_patients"] >= 1

    def test_cancelled_counted(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_monthly_summary
        _make_appt(db, analytics_clinic, hours_offset=0, status="cancelled")
        result = get_monthly_summary(db, analytics_clinic.id)
        assert result["cancelled"] >= 1


# ── Conversation stats ────────────────────────────────────────────────────────

class TestConversationStats:
    def test_returns_usage(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_conversation_stats
        _make_usage(db, analytics_clinic, sessions=10)
        result = get_conversation_stats(db, analytics_clinic.id, analytics_clinic)
        assert result["sessions_this_month"] >= 10
        assert result["daily_average"] > 0

    def test_plan_limit_shown(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_conversation_stats
        result = get_conversation_stats(db, analytics_clinic.id, analytics_clinic)
        assert result["plan_limit"] == 1000  # professional plan
        assert result["sessions_remaining"] is not None

    def test_enterprise_unlimited(self, db):
        from backend.services.analytics_svc import get_conversation_stats
        ent = _make_clinic(db, "analytics-enterprise", plan="enterprise")
        result = get_conversation_stats(db, ent.id, ent)
        assert result["plan_limit"] is None
        assert result["percent_used"] == "Unlimited"
        db.delete(ent)
        db.commit()


# ── No-shows ──────────────────────────────────────────────────────────────────

class TestNoShows:
    def test_empty_no_shows(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_no_shows
        result = get_no_shows(db, analytics_clinic.id, days_back=1)
        assert "count" in result
        assert "patients" in result

    def test_recent_no_show_detected(self, db, analytics_clinic):
        from backend.services.analytics_svc import get_no_shows
        _make_appt(db, analytics_clinic, hours_offset=-2, status="no_show")
        result = get_no_shows(db, analytics_clinic.id, days_back=7)
        assert result["count"] >= 1
        assert any(p["name"] == "Test Patient" for p in result["patients"])


# ── Aria text formatting ──────────────────────────────────────────────────────

class TestAriaFormatting:
    def test_today_empty_message(self):
        from backend.services.analytics_svc import format_for_aria
        data = {"total": 0, "date": "Thursday, June 5, 2026",
                "scheduled": 0, "confirmed": 0, "completed": 0,
                "no_show": 0, "cancelled": 0, "rescheduled": 0,
                "by_provider": {}, "by_type": {}, "no_show_details": []}
        msg = format_for_aria("today_appointments", data)
        assert "No appointments" in msg

    def test_today_with_data(self):
        from backend.services.analytics_svc import format_for_aria
        data = {"total": 12, "date": "Thursday, June 5, 2026",
                "scheduled": 5, "confirmed": 4, "completed": 3,
                "no_show": 0, "cancelled": 0, "rescheduled": 0,
                "by_provider": {"Dr. Smith": 7, "Dr. Jones": 5},
                "by_type": {}, "no_show_details": []}
        msg = format_for_aria("today_appointments", data)
        assert "12" in msg
        assert "Dr. Smith" in msg

    def test_no_shows_message(self):
        from backend.services.analytics_svc import format_for_aria
        data = {"period": "Last 7 days", "count": 2,
                "patients": [
                    {"name": "Jane Smith", "phone": "+15551111", "time": "9am", "type": "checkup"},
                    {"name": "Bob Jones",  "phone": "+15552222", "time": "2pm", "type": "followup"},
                ]}
        msg = format_for_aria("no_shows", data)
        assert "Jane Smith" in msg
        assert "follow" in msg.lower() or "staff" in msg.lower()

    def test_conversations_with_limit(self):
        from backend.services.analytics_svc import format_for_aria
        data = {"sessions_this_month": 450, "plan_limit": 1000,
                "sessions_remaining": 550, "percent_used": "45.0%",
                "daily_average": 15.0, "plan": "professional"}
        msg = format_for_aria("conversations", data)
        assert "450" in msg
        assert "1000" in msg or "1,000" in msg or "550" in msg

    def test_recall_no_campaigns(self):
        from backend.services.analytics_svc import format_for_aria
        data = {"campaigns": 0, "total_sent": 0, "booked": 0, "opted_out": 0}
        msg = format_for_aria("recall_performance", data)
        assert "No recall" in msg


# ── REST endpoint ─────────────────────────────────────────────────────────────

class TestAnalyticsEndpoint:
    def test_full_dashboard(self, client, analytics_clinic, auth_token):
        r = client.get(f"/api/{analytics_clinic.slug}/analytics",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        data = r.json()
        assert "today" in data
        assert "monthly" in data
        assert "conversations" in data
        assert "recall" in data

    def test_today_report_only(self, client, analytics_clinic, auth_token):
        r = client.get(f"/api/{analytics_clinic.slug}/analytics?report=today",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert "total" in r.json()

    def test_requires_auth(self, client, analytics_clinic):
        r = client.get(f"/api/{analytics_clinic.slug}/analytics")
        assert r.status_code == 403

    def test_invalid_report_type(self, client, analytics_clinic, auth_token):
        r = client.get(f"/api/{analytics_clinic.slug}/analytics?report=made_up",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 400
