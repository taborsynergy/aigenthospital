"""Tests for email features: booking confirmation, 72h/24h reminders, recall."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, RecallCampaign
from backend.services import appointment_svc, reminders_svc, recall_svc

_n = 0


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = S()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def sent(monkeypatch):
    """Capture SendGrid payloads instead of making HTTP calls."""
    import httpx
    captured = []

    class _Resp:
        status_code = 202
        text = "OK"

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured.append(json)
        return _Resp()

    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.test", raising=False)
    monkeypatch.setattr(settings, "email_from", "from@clinic.com", raising=False)
    monkeypatch.setattr(httpx, "post", _fake_post)
    return captured


def _clinic(db, plan="professional"):
    global _n
    _n += 1
    c = Clinic(slug=f"em-{_n}", name=f"Email Clinic {_n}", specialty="FM",
               plan=plan, phone="555-0100", address="1 Main St",
               subscription_status="active", customer_password_hash="x", is_active=True)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _recipients(payloads):
    return [p["personalizations"][0]["to"][0]["email"] for p in payloads]


# ── Booking confirmation email ────────────────────────────────────────────────

def test_booking_with_email_sends_confirmation(db, sent):
    c = _clinic(db)
    res = appointment_svc.book_appointment(
        c, db, patient_name="Pat A", appointment_type="Checkup",
        datetime_str="Mon 10am", patient_email="pat@x.com", channel="web")
    assert res.get("success") is True
    assert "pat@x.com" in _recipients(sent)


def test_booking_without_email_sends_nothing(db, sent):
    c = _clinic(db)
    res = appointment_svc.book_appointment(
        c, db, patient_name="No Email", appointment_type="Checkup",
        datetime_str="Tue 9am", patient_email="", channel="web")
    assert res.get("success") is True
    assert sent == []


# ── Email reminders (72h / 24h) ───────────────────────────────────────────────

def _appt(db, clinic, conf, hours_ahead, email="pat@x.com"):
    appt = Appointment(
        clinic_id=clinic.id, confirmation_number=conf, patient_name="Pat",
        patient_email=email, appointment_type="Checkup", appointment_datetime="soon",
        appointment_ts=dt.datetime.utcnow() + dt.timedelta(hours=hours_ahead),
        status="scheduled", reminder_24h_sent=False, reminder_72h_sent=False,
        created_at=dt.datetime.utcnow())
    db.add(appt)
    db.commit()
    return appt


def test_24h_reminder_emailed_for_growth(db, sent):
    c = _clinic(db, "professional")
    _appt(db, c, "R24", 24)
    stats = reminders_svc.send_due_reminders(db)
    assert stats["sent_24h"] == 1
    assert "pat@x.com" in _recipients(sent)


def test_reminder_not_resent(db, sent):
    c = _clinic(db, "professional")
    _appt(db, c, "R24B", 24)
    reminders_svc.send_due_reminders(db)
    sent.clear()
    reminders_svc.send_due_reminders(db)
    assert sent == []  # flag set → no duplicate


def test_starter_reminder_skipped(db, sent):
    c = _clinic(db, "starter")
    _appt(db, c, "RS", 24)
    stats = reminders_svc.send_due_reminders(db)
    # starter clinic contributes nothing
    assert "RS" not in [a.confirmation_number for a in
                        db.query(Appointment).filter_by(reminder_24h_sent=True).all()]


# ── Recall campaigns (email) ──────────────────────────────────────────────────

def test_recall_emails_due_patient(db, sent):
    c = _clinic(db, "professional")
    old = dt.datetime.utcnow() - dt.timedelta(days=400)
    db.add(Appointment(clinic_id=c.id, confirmation_number="OLD", patient_name="Old Pat",
                       patient_email="old@x.com", appointment_type="Physical",
                       appointment_datetime="last year", appointment_ts=old,
                       status="completed", created_at=old))
    db.commit()
    camp = RecallCampaign(clinic_id=c.id, name="Annual", visit_type="annual physical",
                          interval_months=12, is_active=True, message_template="")
    db.add(camp)
    db.commit()
    stats = recall_svc.run_campaign(db, c, camp)
    assert stats["sent"] == 1
    assert "old@x.com" in _recipients(sent)


def test_recall_skipped_for_starter(db, sent):
    c = _clinic(db, "starter")
    camp = RecallCampaign(clinic_id=c.id, name="Annual", visit_type="physical",
                          interval_months=12, is_active=True, message_template="")
    db.add(camp)
    db.commit()
    stats = recall_svc.run_campaign(db, c, camp)
    assert stats["sent"] == 0
