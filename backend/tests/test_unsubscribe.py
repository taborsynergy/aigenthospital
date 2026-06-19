"""Tests for recall email unsubscribe (CAN-SPAM): signed token, public endpoint,
link in the email, and that opting out blocks future recall sends."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_unsub.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, RecallCampaign
from backend.db import crud
from backend.unsub import make_unsub_token, verify_unsub_token
from backend.services import recall_svc

_n = 0


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
def sent(monkeypatch):
    import httpx
    captured = []

    class _Resp:
        status_code = 202
        text = "OK"

    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.test", raising=False)
    monkeypatch.setattr(settings, "email_from", "from@clinic.com", raising=False)
    monkeypatch.setattr(httpx, "post",
                        lambda url, headers=None, json=None, timeout=None: (captured.append(json) or _Resp()))
    return captured


def _due_clinic_with_campaign(db):
    global _n
    _n += 1
    c = Clinic(slug=f"unsub-{_n}", name=f"Unsub Clinic {_n}", specialty="FM",
               plan="professional", phone="555", subscription_status="active",
               customer_password_hash="x", is_active=True)
    db.add(c)
    db.commit()
    db.refresh(c)
    old = dt.datetime.utcnow() - dt.timedelta(days=400)
    db.add(Appointment(clinic_id=c.id, confirmation_number=f"O{_n}", patient_name="Old Pat",
                       patient_email="old@x.com", appointment_type="Physical",
                       appointment_datetime="last year", appointment_ts=old,
                       status="completed", created_at=old))
    camp = RecallCampaign(clinic_id=c.id, name="Annual", visit_type="annual physical",
                          interval_months=12, is_active=True, message_template="")
    db.add(camp)
    db.commit()
    db.refresh(camp)
    return c, camp


# ── Token ─────────────────────────────────────────────────────────────────────

def test_token_roundtrip():
    tok = make_unsub_token(7, "a@b.com")
    assert verify_unsub_token(tok) == (7, "a@b.com")


def test_tampered_token_rejected():
    tok = make_unsub_token(7, "a@b.com")
    assert verify_unsub_token(tok[:-2] + "xy") is None
    assert verify_unsub_token("garbage") is None
    assert verify_unsub_token("") is None


# ── Email contains the unsubscribe link ───────────────────────────────────────

def test_recall_email_includes_unsubscribe_link(db, sent):
    c, camp = _due_clinic_with_campaign(db)
    recall_svc.run_campaign(db, c, camp)
    assert len(sent) == 1
    body = sent[0]["content"][0]["value"]
    assert "/api/unsubscribe?token=" in body
    assert "Unsubscribe" in body


# ── Endpoint opts out, and recall then skips the patient ──────────────────────

def test_unsubscribe_endpoint_blocks_future_recall(client, db, sent):
    c, camp = _due_clinic_with_campaign(db)
    # first run sends
    assert recall_svc.run_campaign(db, c, camp)["sent"] == 1

    # patient clicks the unsubscribe link
    token = make_unsub_token(c.id, "old@x.com")
    r = client.get(f"/api/unsubscribe?token={token}")
    assert r.status_code == 200
    assert "unsubscribed" in r.text.lower()
    assert crud.is_opted_out(db, c.id, "old@x.com") is True

    # a later run must NOT email this patient again
    sent.clear()
    stats = recall_svc.run_campaign(db, c, camp)
    assert stats["sent"] == 0
    assert stats["opted_out"] >= 1
    assert sent == []


def test_invalid_unsubscribe_token_400(client):
    r = client.get("/api/unsubscribe?token=not-a-real-token")
    assert r.status_code == 400
