"""API contract + integration-edge tests (GAP-API): public endpoint schemas,
JSON (not HTML) error shape, and graceful handling of email-provider failures."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_apicontract.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.db.database import Base, engine
from backend.services import email_svc


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ── GAP-API-001: public /api/plans schema (regression guard for the sms→reminders fix) ──

def test_plans_endpoint_schema(client):
    r = client.get("/api/plans")
    assert r.status_code == 200, r.text
    plans = r.json()["plans"]
    assert {"starter", "professional", "enterprise"}.issubset(plans.keys())
    for key, p in plans.items():
        assert {"name", "price", "conversations_limit", "features"}.issubset(p.keys())
        # post-SMS-removal: feature flag is 'reminders', never 'sms'
        assert "reminders" in p["features"]
        assert "sms" not in p["features"]


def test_health_schema(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


# ── GAP-API: error responses are JSON, never an HTML stack trace ──────────────

def test_unknown_route_returns_json(client):
    r = client.get("/api/totally/unknown/route")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert "<html" not in r.text.lower()


# ── GAP-API-005: email-provider failures are handled gracefully (no crash) ────

@pytest.fixture
def sg_status(monkeypatch):
    """Make SendGrid return a configurable status; capture nothing else."""
    import httpx

    def _factory(code):
        class _Resp:
            status_code = code
            text = "err" if code >= 400 else "OK"
        monkeypatch.setattr(settings, "sendgrid_api_key", "SG.test", raising=False)
        monkeypatch.setattr(settings, "email_from", "verified@taborsynergy.com", raising=False)
        monkeypatch.setattr(httpx, "post",
                            lambda url, headers=None, json=None, timeout=None: _Resp())
    return _factory


@pytest.mark.parametrize("code", [400, 401, 429, 500, 503])
def test_send_email_returns_false_on_provider_error(sg_status, code):
    sg_status(code)
    assert email_svc.send_email("p@x.com", "Hi", "body") is False   # graceful, no raise


def test_send_email_true_on_accepted(sg_status):
    sg_status(202)
    assert email_svc.send_email("p@x.com", "Hi", "body") is True


def test_send_email_handles_transport_exception(monkeypatch):
    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("network down")
    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.test", raising=False)
    monkeypatch.setattr(httpx, "post", _boom)
    # Must not propagate — returns False so callers never crash on email failure
    assert email_svc.send_email("p@x.com", "Hi", "body") is False
