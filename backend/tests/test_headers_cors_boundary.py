"""Security headers + CORS (GAP-SEC-011/012), boundary values (GAP-BVA), and
reliability of background jobs on empty/edge input (GAP-REL)."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_hcb.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, ClinicUser
from backend.db import crud
from backend.auth import create_access_token
from backend.routers.clinic_auth import hash_password
from backend.services import reminders_svc

ALLOWED_ORIGIN = "https://aifrontdesk.taborsynergy.com"
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


def _clinic_with_jwt(db):
    global _n
    _n += 1
    c = Clinic(slug=f"hcb-{_n}", name=f"HCB {_n}", specialty="FM", email=f"hcb{_n}@x.com",
               plan="professional", subscription_status="active",
               customer_password_hash=hash_password("pw"), is_active=True,
               subscription_ends_at=datetime.utcnow() + timedelta(days=30))
    db.add(c); db.commit(); db.refresh(c)
    u = ClinicUser(clinic_id=c.id, email=f"hcbuser{_n}@x.com", password_hash=hash_password("pw"),
                   full_name="O", role="admin")
    db.add(u); db.commit(); db.refresh(u)
    return c, {"Authorization": f"Bearer {create_access_token({'user_id': u.id, 'clinic_id': c.id})}"}


# ── GAP-SEC-011: security headers present on every response ───────────────────

def test_security_headers_present(client):
    h = client.get("/api/health").headers
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert "max-age=" in (h.get("strict-transport-security") or "")
    assert "frame-ancestors 'none'" in (h.get("content-security-policy") or "")
    assert h.get("referrer-policy") == "strict-origin-when-cross-origin"


# ── GAP-SEC-012: CORS allows configured origin, rejects others ────────────────

def test_cors_allows_configured_origin(client):
    r = client.get("/api/health", headers={"Origin": ALLOWED_ORIGIN})
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_cors_rejects_unknown_origin(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example.com"})
    # Starlette omits ACAO for disallowed origins (never echoes the attacker origin)
    assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"


def test_cors_preflight_allowed_origin(client):
    r = client.options("/api/health", headers={
        "Origin": ALLOWED_ORIGIN,
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


# ── GAP-BVA: input length boundaries (just over the cap) ──────────────────────

def test_chat_message_one_over_cap_rejected(client, db):
    global _n
    _n += 1
    c = Clinic(slug=f"hcbchat-{_n}", name="X", specialty="FM", email=f"hcbchat{_n}@x.com",
               plan="professional", subscription_status="active", customer_password_hash="x",
               is_active=True, subscription_ends_at=datetime.utcnow() + timedelta(days=30))
    db.add(c); db.commit()
    assert client.post(f"/api/{c.slug}/chat", json={"message": "A" * 4001}).status_code == 422


def test_profile_field_boundary(client, db):
    c, headers = _clinic_with_jwt(db)
    url = f"/api/clinic/onboarding/{c.slug}/profile"
    assert client.patch(url, json={"agent_name": "A" * 100}, headers=headers).status_code == 200
    assert client.patch(url, json={"agent_name": "A" * 101}, headers=headers).status_code == 422


# ── GAP-REL: background jobs are safe on empty / ungated input ────────────────

def test_reminders_run_on_empty_db_is_safe(db):
    stats = reminders_svc.send_due_reminders(db)
    assert isinstance(stats, dict)            # no crash, returns a stats dict


def test_recall_gated_off_for_starter_plan(db, monkeypatch):
    from backend.services import recall_svc, email_svc
    monkeypatch.setattr(email_svc, "send_email", lambda **kw: True)
    global _n
    _n += 1
    starter = Clinic(slug=f"hcbstart-{_n}", name="S", specialty="FM",
                     email=f"hcbstart{_n}@x.com", plan="starter", subscription_status="active",
                     customer_password_hash="x", is_active=True)
    db.add(starter); db.commit(); db.refresh(starter)
    from backend.db.models import RecallCampaign
    camp = RecallCampaign(clinic_id=starter.id, name="C", visit_type="annual",
                          interval_months=12, is_active=True, message_template="")
    db.add(camp); db.commit(); db.refresh(camp)
    stats = recall_svc.run_campaign(db, starter, camp)
    assert stats["sent"] == 0                 # starter has no reminders/recall entitlement
