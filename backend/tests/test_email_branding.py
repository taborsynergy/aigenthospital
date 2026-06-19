"""Per-clinic email branding (Option A): patient-facing emails show the clinic's
name as sender and route replies to the clinic, while the real From address stays
the verified SendGrid sender."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_branding.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ["TESTING"] = "1"

from types import SimpleNamespace
import pytest

from backend.config import settings
from backend.services import email_svc, recall_svc, reminders_svc


@pytest.fixture
def sg(monkeypatch):
    """Capture the JSON payload POSTed to SendGrid."""
    import httpx
    sent = []

    class _Resp:
        status_code = 202
        text = "OK"

    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.test", raising=False)
    monkeypatch.setattr(settings, "email_from", "verified@taborsynergy.com", raising=False)
    monkeypatch.setattr(httpx, "post",
                        lambda url, headers=None, json=None, timeout=None: (sent.append(json) or _Resp()))
    return sent


def _clinic(**kw):
    base = dict(id=1, slug="britepath", name="BritePath Medical", phone="555-2000",
                email="frontdesk@britepath.com", address="12 Main St",
                cancellation_policy="24-hour notice required.")
    base.update(kw)
    return SimpleNamespace(**base)


# ── send_email low-level ──────────────────────────────────────────────────────

def test_send_email_applies_clinic_branding(sg):
    email_svc.send_email("patient@x.com", "Hi", "body",
                         from_name="BritePath Medical", reply_to="frontdesk@britepath.com")
    p = sg[0]
    assert p["from"]["name"] == "BritePath Medical"
    assert p["from"]["email"] == "verified@taborsynergy.com"   # real sender unchanged
    assert p["reply_to"]["email"] == "frontdesk@britepath.com"


def test_send_email_defaults_when_unbranded(sg):
    email_svc.send_email("patient@x.com", "Hi", "body")
    p = sg[0]
    assert p["from"]["name"] == "Tabor Synergy"
    assert "reply_to" not in p


# ── Appointment confirmation ──────────────────────────────────────────────────

def test_confirmation_email_branded(sg):
    appt = SimpleNamespace(patient_email="pat@x.com", patient_name="Pat",
                           confirmation_number="C123", appointment_type="Physical",
                           appointment_datetime="Mon 9am", provider="")
    assert email_svc.send_booking_confirmation_email(_clinic(), appt) is True
    p = sg[0]
    assert p["from"]["name"] == "BritePath Medical"
    assert p["reply_to"]["email"] == "frontdesk@britepath.com"
    assert p["from"]["email"] == "verified@taborsynergy.com"


def test_confirmation_no_replyto_when_clinic_has_no_email(sg):
    appt = SimpleNamespace(patient_email="pat@x.com", patient_name="Pat",
                           confirmation_number="C1", appointment_type="Physical",
                           appointment_datetime="Mon", provider="")
    email_svc.send_booking_confirmation_email(_clinic(email=""), appt)
    p = sg[0]
    assert p["from"]["name"] == "BritePath Medical"
    assert "reply_to" not in p   # no clinic inbox -> no reply-to


# ── Reminders + recall pass the same branding ─────────────────────────────────

def test_reminder_passes_branding(monkeypatch):
    captured = {}
    monkeypatch.setattr(email_svc, "send_email", lambda **kw: captured.update(kw) or True)
    monkeypatch.setattr("backend.db.crud.update_appointment", lambda *a, **k: None)
    appt = SimpleNamespace(patient_email="pat@x.com", patient_name="Pat",
                           appointment_type="Physical", appointment_datetime="Tue",
                           provider="", confirmation_number="C9")
    reminders_svc._send(_clinic(), appt, db=None, hours=24, sent_flag="reminder_24h_sent")
    assert captured["from_name"] == "BritePath Medical"
    assert captured["reply_to"] == "frontdesk@britepath.com"


def test_recall_passes_branding(monkeypatch):
    captured = {}
    monkeypatch.setattr(email_svc, "send_email", lambda **kw: captured.update(kw) or True)
    monkeypatch.setattr("backend.plans.can_use_reminders", lambda c: True)
    monkeypatch.setattr("backend.db.crud.find_patients_due_for_recall",
                        lambda db, cid, im: [{"patient_email": "pat@x.com", "patient_name": "Pat"}])
    monkeypatch.setattr("backend.db.crud.get_recall_log", lambda *a, **k: [])
    monkeypatch.setattr("backend.db.crud.is_opted_out", lambda *a, **k: False)
    monkeypatch.setattr("backend.db.crud.log_recall_sent", lambda *a, **k: None)
    campaign = SimpleNamespace(id=1, is_active=True, message_template="",
                               visit_type="annual physical", interval_months=12)
    stats = recall_svc.run_campaign(db=None, clinic=_clinic(), campaign=campaign)
    assert stats["sent"] == 1
    assert captured["from_name"] == "BritePath Medical"
    assert captured["reply_to"] == "frontdesk@britepath.com"
