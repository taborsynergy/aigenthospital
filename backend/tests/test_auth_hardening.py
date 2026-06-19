"""Auth-hardening tests (GAP-SEC): account lockout, login rate-limit wiring,
JWT expiry/tamper/alg-none/wrong-secret, logout + session-token expiry, and
username-enumeration parity. These lock in controls that already exist in code
but had no test guarding them."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_authhard.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import base64
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.db import crud
from backend.auth import create_access_token
from backend.routers.clinic_auth import hash_password

_n = 0
PW = "testpass123"


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
    c = Clinic(slug=f"auth-{_n}", name=f"Auth {_n}", specialty="FM",
               email=f"auth{_n}@x.com", plan="professional", subscription_status="active",
               customer_password_hash=hash_password(PW), is_active=True,
               subscription_ends_at=datetime.utcnow() + timedelta(days=30))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _login(client, email, password):
    return client.post("/api/clinic-auth/login", json={"email": email, "password": password})


# ── GAP-SEC-001: account lockout after repeated failures ──────────────────────

def test_account_locks_after_max_failures(client, db):
    c = _clinic(db)
    statuses = [_login(client, c.email, "wrong").status_code for _ in range(10)]
    assert 429 in statuses                       # locks within the threshold
    db.refresh(c)
    assert c.locked_until is not None
    # Even the CORRECT password is refused while locked
    assert _login(client, c.email, PW).status_code == 429


def test_successful_login_resets_failure_counter(client, db):
    c = _clinic(db)
    _login(client, c.email, "wrong")
    _login(client, c.email, "wrong")
    assert _login(client, c.email, PW).status_code == 200
    db.refresh(c)
    assert (c.failed_login_attempts or 0) == 0
    assert c.locked_until is None


# ── GAP-SEC-002: login rate-limiter is actually wired ─────────────────────────

def test_login_rate_limited(client, db, monkeypatch):
    """Temporarily disable the test-mode key bypass so the 5/hour limit applies."""
    c = _clinic(db)
    monkeypatch.setenv("TESTING", "0")   # real IP keying -> shared 'testclient' key
    codes = [_login(client, c.email, "wrong").status_code for _ in range(8)]
    assert 429 in codes                  # limiter kicks in within the window


# ── GAP-SEC-004..007: JWT validation on a Bearer-protected route ──────────────

PROTECTED = "/api/clinic/onboarding/any/profile"   # GET requires a valid JWT


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_jwt_expired_rejected(client):
    tok = create_access_token({"user_id": 1}, expires_delta=timedelta(seconds=-5))
    assert client.get(PROTECTED, headers=_bearer(tok)).status_code == 401


def test_jwt_tampered_rejected(client):
    tok = create_access_token({"user_id": 1})
    assert client.get(PROTECTED, headers=_bearer(tok[:-2] + ("aa" if tok[-1] != "a" else "bb"))).status_code == 401


def test_jwt_alg_none_rejected(client):
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    forged = b64({"alg": "none", "typ": "JWT"}) + "." + b64({"user_id": 1}) + "."
    assert client.get(PROTECTED, headers=_bearer(forged)).status_code == 401


def test_jwt_wrong_secret_rejected(client):
    import jwt
    tok = jwt.encode({"user_id": 1, "exp": datetime.utcnow() + timedelta(hours=1)},
                     "attacker-key", algorithm="HS256")
    assert client.get(PROTECTED, headers=_bearer(tok)).status_code == 401


def test_jwt_missing_rejected(client):
    assert client.get(PROTECTED).status_code in (401, 403)


# ── GAP-SEC-010: logout + session-token expiry invalidate the portal token ────

def test_logout_invalidates_session_token(client, db):
    c = _clinic(db)
    tok = _login(client, c.email, PW).json()["token"]
    assert client.get("/api/clinic-auth/verify", headers={"x-clinic-token": tok}).status_code == 200
    assert client.post("/api/clinic-auth/logout", headers={"x-clinic-token": tok}).status_code == 200
    assert client.get("/api/clinic-auth/verify", headers={"x-clinic-token": tok}).status_code == 401


def test_expired_session_token_rejected(client, db):
    c = _clinic(db)
    c.session_token = "expired-tok-123"
    c.token_expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get("/api/clinic-auth/verify",
                      headers={"x-clinic-token": "expired-tok-123"}).status_code == 401


# ── Username-enumeration parity (unknown user vs wrong password) ───────────────

def test_login_no_user_enumeration(client, db):
    c = _clinic(db)
    unknown = _login(client, "does-not-exist@x.com", "whatever")
    wrong = _login(client, c.email, "wrong")
    assert unknown.status_code == 401 and wrong.status_code == 401
    # Both should say "Invalid credentials" (no "user not found" distinction)
    assert "invalid credentials" in unknown.json()["error"].lower()
    assert "invalid credentials" in wrong.json()["error"].lower()
