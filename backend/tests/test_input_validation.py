"""Negative / injection / input-validation tests (GAP-NEG): oversized payloads,
SQL-injection literals, stored HTML/XSS round-trip, malformed bodies, wrong
content-type, bad method, null fields, path traversal, unicode, and email
header-injection. Includes the new length caps + CRLF email sanitization."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_inputval.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, ClinicUser
from backend.db import crud
from backend.auth import create_access_token
from backend.routers.clinic_auth import hash_password
from backend.services import email_svc

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


def _clinic(db):
    global _n
    _n += 1
    c = Clinic(slug=f"iv-{_n}", name=f"IV {_n}", specialty="FM", email=f"iv{_n}@x.com",
               phone="5551112222", plan="professional", subscription_status="active",
               customer_password_hash=hash_password("testpass123"), is_active=True,
               subscription_ends_at=datetime.utcnow() + timedelta(days=30))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _clinic_with_jwt(db):
    c = _clinic(db)
    u = ClinicUser(clinic_id=c.id, email=f"u{_n}@x.com", password_hash=hash_password("pw"),
                   full_name="Owner", role="admin")
    db.add(u)
    db.commit()
    db.refresh(u)
    return c, {"Authorization": f"Bearer {create_access_token({'user_id': u.id, 'clinic_id': c.id})}"}


# ── GAP-NEG-005: oversized payloads rejected (new length caps) ────────────────

def test_oversized_chat_message_rejected(client, db):
    c = _clinic(db)
    r = client.post(f"/api/{c.slug}/chat", json={"message": "A" * 5000})
    assert r.status_code == 422


def test_oversized_profile_field_rejected(client, db):
    c, headers = _clinic_with_jwt(db)
    r = client.patch(f"/api/clinic/onboarding/{c.slug}/profile",
                     json={"address": "B" * 600}, headers=headers)
    assert r.status_code == 422


def test_chat_message_at_cap_accepted(client, db):
    c = _clinic(db)
    r = client.post(f"/api/{c.slug}/chat", json={"message": "C" * 4000})
    assert r.status_code == 200


# ── GAP-NEG-003/010: SQL injection treated as a literal, never executed ───────

def test_sqli_in_slug_is_inert(client, db):
    c = _clinic(db)
    r = client.post("/api/'; DROP TABLE clinics;--/chat", json={"message": "hi"})
    assert r.status_code in (404, 400)
    # Table intact — the clinic is still queryable
    assert crud.get_clinic(db, c.slug) is not None


def test_sqli_in_login_email_is_inert(client, db):
    c = _clinic(db)
    r = client.post("/api/clinic-auth/login",
                    json={"email": "x' OR '1'='1", "password": "x' OR '1'='1"})
    assert r.status_code == 401
    assert crud.get_clinic(db, c.slug) is not None


def test_sqli_in_chat_message_is_text(client, db):
    c = _clinic(db)
    r = client.post(f"/api/{c.slug}/chat", json={"message": "'; DROP TABLE clinics;--"})
    assert r.status_code == 200
    assert crud.get_clinic(db, c.slug) is not None


# ── GAP-NEG-001/002: stored HTML/XSS round-trips as inert JSON ────────────────

def test_xss_payload_roundtrips_as_json(client, db):
    c, headers = _clinic_with_jwt(db)
    xss = "<script>alert('x')</script>"
    p = client.patch(f"/api/clinic/onboarding/{c.slug}/profile",
                     json={"services_offered": xss}, headers=headers)
    assert p.status_code == 200
    g = client.get(f"/api/clinic/onboarding/{c.slug}/profile", headers=headers)
    # Served as JSON (browsers don't execute scripts in application/json), value preserved
    assert g.headers["content-type"].startswith("application/json")
    assert g.json()["profile"]["services_offered"] == xss


# ── GAP-NEG-006/007/008/009: malformed request handling ───────────────────────

def test_malformed_json_returns_422(client, db):
    c = _clinic(db)
    r = client.post(f"/api/{c.slug}/chat", content='{"message":',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_wrong_content_type_returns_422(client, db):
    c = _clinic(db)
    r = client.post(f"/api/{c.slug}/chat", content="message=hi",
                    headers={"Content-Type": "text/plain"})
    assert r.status_code == 422


def test_method_not_allowed_returns_405(client, db):
    c = _clinic(db)
    assert client.put(f"/api/{c.slug}/chat", json={"message": "x"}).status_code == 405


def test_null_required_field_returns_422(client, db):
    c = _clinic(db)
    assert client.post(f"/api/{c.slug}/chat", json={"message": None}).status_code == 422


# ── GAP-NEG-016: path traversal in slug is inert ──────────────────────────────

def test_path_traversal_slug_is_inert(client):
    for bad in ["../../etc/passwd", "..%2f..%2fetc%2fpasswd"]:
        r = client.get(f"/api/{bad}/plan")
        assert r.status_code in (403, 404)
        assert "root:" not in r.text


# ── GAP-NEG-011: unicode / multibyte round-trips intact ───────────────────────

def test_unicode_multibyte_roundtrips(client, db):
    c, headers = _clinic_with_jwt(db)
    val = "名前 🏥 José — Café"
    client.patch(f"/api/clinic/onboarding/{c.slug}/profile",
                 json={"agent_name": val}, headers=headers)
    g = client.get(f"/api/clinic/onboarding/{c.slug}/profile", headers=headers)
    assert g.json()["profile"]["agent_name"] == val


# ── GAP-API-010: email header injection (CRLF) is sanitized ───────────────────

def test_email_replyto_crlf_sanitized(monkeypatch):
    import httpx
    sent = []

    class _Resp:
        status_code = 202
        text = "OK"

    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.test", raising=False)
    monkeypatch.setattr(settings, "email_from", "verified@taborsynergy.com", raising=False)
    monkeypatch.setattr(httpx, "post",
                        lambda url, headers=None, json=None, timeout=None: (sent.append(json) or _Resp()))

    clinic = SimpleNamespace(name="Evil\r\nBcc: attacker@evil.com", phone="555",
                             email="front@x.com\r\nBcc: attacker@evil.com",
                             address="", cancellation_policy="")
    appt = SimpleNamespace(patient_email="pat@x.com", patient_name="Pat",
                           confirmation_number="C1", appointment_type="Physical",
                           appointment_datetime="Mon", provider="")
    email_svc.send_booking_confirmation_email(clinic, appt)
    p = sent[0]
    assert "\n" not in p["from"]["name"] and "\r" not in p["from"]["name"]
    assert "\n" not in p["reply_to"]["email"] and "\r" not in p["reply_to"]["email"]
