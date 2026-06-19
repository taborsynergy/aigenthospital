"""Integration resilience (GAP2-API-RETRY, REL-SCHED, REL-BATCH): SendGrid
transient-failure retry/backoff, reminder catch-up after a missed run, and recall
batch isolation (one bad recipient doesn't abort the rest)."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_resint.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, RecallCampaign
from backend.services import email_svc, recall_svc, reminders_svc

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


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(email_svc, "_BACKOFF_BASE", 0)   # no real sleeps in tests


def _clinic(db, **kw):
    global _n
    _n += 1
    base = dict(slug=f"ri-{_n}", name=f"RI {_n}", specialty="FM", email=f"ri{_n}@x.com",
                phone="555", plan="professional", subscription_status="active",
                timezone="UTC", customer_password_hash="x", is_active=True)
    base.update(kw)
    c = Clinic(**base)
    db.add(c); db.commit(); db.refresh(c)
    return c


# ── GAP2-API-RETRY: SendGrid transient failures are retried, permanent aren't ─

def _mock_sg(monkeypatch, statuses):
    """Return a list of HTTP statuses to yield in order; capture call count."""
    import httpx
    calls = {"n": 0}

    class _Resp:
        def __init__(self, code): self.status_code = code; self.text = "x"

    def _post(url, headers=None, json=None, timeout=None):
        i = min(calls["n"], len(statuses) - 1)
        calls["n"] += 1
        return _Resp(statuses[i])

    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.test", raising=False)
    monkeypatch.setattr(settings, "email_from", "v@x.com", raising=False)
    monkeypatch.setattr(httpx, "post", _post)
    return calls


def test_retry_succeeds_after_transient_5xx(monkeypatch):
    calls = _mock_sg(monkeypatch, [503, 503, 202])
    assert email_svc.send_email("p@x.com", "s", "b") is True
    assert calls["n"] == 3   # retried twice then succeeded


def test_retry_on_429_then_success(monkeypatch):
    calls = _mock_sg(monkeypatch, [429, 202])
    assert email_svc.send_email("p@x.com", "s", "b") is True
    assert calls["n"] == 2


def test_permanent_4xx_not_retried(monkeypatch):
    calls = _mock_sg(monkeypatch, [400, 400, 400])
    assert email_svc.send_email("p@x.com", "s", "b") is False
    assert calls["n"] == 1   # 400 is permanent -> fail fast, no retry


def test_gives_up_after_max_retries(monkeypatch):
    calls = _mock_sg(monkeypatch, [503])
    assert email_svc.send_email("p@x.com", "s", "b") is False
    assert calls["n"] == email_svc._MAX_SEND_RETRIES


# ── GAP2-REL-SCHED: a missed run is caught up on the next run ──────────────────

def _due_appt(db, clinic, ts):
    global _n
    _n += 1
    a = Appointment(clinic_id=clinic.id, confirmation_number=f"RI{_n}", patient_name="Pat",
                    patient_email="pat@x.com", appointment_type="Physical",
                    appointment_datetime="soon", appointment_ts=ts, status="scheduled",
                    reminder_24h_sent=False, created_at=dt.datetime.utcnow())
    db.add(a); db.commit(); db.refresh(a)
    return a


def test_missed_run_caught_up_within_window(db, monkeypatch):
    monkeypatch.setattr(email_svc, "send_email", lambda **kw: True)
    c = _clinic(db)
    # Appt slightly PAST the exact 24h target (a run was missed ~3h ago) — still
    # inside the catch-up window, so the next run picks it up.
    ts = dt.datetime.utcnow() + dt.timedelta(hours=24) - dt.timedelta(minutes=90 + 180)
    appt = _due_appt(db, c, ts)
    reminders_svc.send_due_reminders(db)
    db.refresh(appt)
    assert appt.reminder_24h_sent is True


def test_appt_far_outside_window_not_caught(db, monkeypatch):
    monkeypatch.setattr(email_svc, "send_email", lambda **kw: True)
    c = _clinic(db)
    # 10h before the 24h target — beyond window+catchup -> not (yet) reminded
    ts = dt.datetime.utcnow() + dt.timedelta(hours=24) - dt.timedelta(hours=10)
    appt = _due_appt(db, c, ts)
    reminders_svc.send_due_reminders(db)
    db.refresh(appt)
    assert appt.reminder_24h_sent is False


# ── GAP2-REL-BATCH: one bad recipient doesn't abort the recall batch ──────────

def test_recall_batch_continues_past_failure(db, monkeypatch):
    c = _clinic(db)
    old = dt.datetime.utcnow() - dt.timedelta(days=400)
    for i in range(4):
        db.add(Appointment(clinic_id=c.id, confirmation_number=f"RB{c.id}-{i}",
                           patient_name=f"P{i}", patient_email=f"p{i}-{c.id}@x.com",
                           appointment_type="Physical", appointment_datetime="last year",
                           appointment_ts=old, status="completed", created_at=old))
    camp = RecallCampaign(clinic_id=c.id, name="A", visit_type="annual physical",
                          interval_months=12, is_active=True, message_template="")
    db.add(camp); db.commit(); db.refresh(camp)

    # The 2nd recipient raises; the batch must still send the other 3.
    state = {"n": 0}

    def _flaky(**kw):
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("smtp blew up for this recipient")
        return True

    monkeypatch.setattr(email_svc, "send_email", _flaky)
    stats = recall_svc.run_campaign(db, c, camp)
    assert stats["sent"] == 3
    assert stats["errors"] >= 1
