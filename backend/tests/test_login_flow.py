"""
REG-005 — Full signup → portal → login regression tests.

These tests cover the gaps that allowed the "nothing is happening" login
regression to reach production:

1. POST /api/signup MUST return a token (for auto-login on redirect)
2. GET /c/{slug}?token=<value> MUST auto-verify and show dashboard (portal JS)
3. POST /api/clinic-auth/login with correct creds MUST return 200 + token
4. POST /api/clinic-auth/login with wrong creds MUST return 401 (JSON)
5. Rate-limit 429 MUST return JSON (not plain text), so the portal can show the error
6. Token verify MUST work after login
7. Profile API MUST work with the session token
"""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_login_flow.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic

_ctr = 0

@pytest.fixture(scope="module", autouse=True)
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


class TestSignupReturnsToken:
    """POST /api/signup MUST return a session token so landing page can auto-login."""

    def test_signup_returns_token(self, client):
        """REG-005-A: signup response includes 'token' field."""
        global _ctr; _ctr += 1
        r = client.post("/api/signup", json={
            "practice_name": f"Login Flow Clinic {_ctr}",
            "contact_email": f"lf{_ctr}@test.com",
            "password":      "LoginPass123!",
            "specialty":     "Family Medicine",
            "plan":          "professional",
        })
        assert r.status_code == 200, f"Signup failed: {r.text}"
        d = r.json()
        assert "token" in d, f"'token' missing from signup response: {list(d.keys())}"
        assert len(d["token"]) >= 16, "token too short"

    def test_signup_returns_portal_url_with_token(self, client):
        """REG-005-B: signup response includes portal_url with ?token= for redirect."""
        global _ctr; _ctr += 1
        r = client.post("/api/signup", json={
            "practice_name": f"Portal URL Clinic {_ctr}",
            "contact_email": f"pu{_ctr}@test.com",
            "password":      "PortalPass123!",
            "specialty":     "Pediatrics",
            "plan":          "starter",
        })
        assert r.status_code == 200
        d = r.json()
        assert "portal_url" in d, f"'portal_url' missing: {list(d.keys())}"
        assert "?token=" in d["portal_url"], f"portal_url has no token: {d['portal_url']}"

    def test_signup_token_is_valid_for_verify(self, client):
        """REG-005-C: token from signup response works with /verify endpoint."""
        global _ctr; _ctr += 1
        r = client.post("/api/signup", json={
            "practice_name": f"Verify Token Clinic {_ctr}",
            "contact_email": f"vt{_ctr}@test.com",
            "password":      "VerifyPass123!",
            "specialty":     "Dental",
            "plan":          "starter",
        })
        assert r.status_code == 200
        token = r.json()["token"]
        slug  = r.json()["slug"]

        verify_r = client.get("/api/clinic-auth/verify",
                              headers={"X-Clinic-Token": token})
        assert verify_r.status_code == 200, f"Token verify failed: {verify_r.json()}"
        assert verify_r.json()["slug"] == slug

    def test_signup_token_auto_login_bypasses_login_form(self, client):
        """REG-005-D: clinic can access profile API immediately after signup (no login needed)."""
        global _ctr; _ctr += 1
        r = client.post("/api/signup", json={
            "practice_name": f"Auto Login Clinic {_ctr}",
            "contact_email": f"al{_ctr}@test.com",
            "password":      "AutoLogin123!",
            "specialty":     "Orthopedics",
            "plan":          "professional",
        })
        assert r.status_code == 200
        token = r.json()["token"]
        slug  = r.json()["slug"]

        profile_r = client.get(f"/api/{slug}/profile",
                               headers={"X-Clinic-Token": token})
        assert profile_r.status_code == 200, f"Profile failed: {profile_r.json()}"


class TestPortalLoginForm:
    """POST /api/clinic-auth/login must work for clinics created via /api/signup."""

    def _signup_and_get_creds(self, client):
        global _ctr; _ctr += 1
        r = client.post("/api/signup", json={
            "practice_name": f"Login Test Clinic {_ctr}",
            "contact_email": f"lt{_ctr}@test.com",
            "password":      "LoginTest123!",
            "specialty":     "Cardiology",
            "plan":          "professional",
        })
        assert r.status_code == 200
        return r.json()["slug"], f"lt{_ctr}@test.com", "LoginTest123!"

    def test_login_with_correct_credentials(self, client):
        """REG-005-E: correct email/password returns 200 with token."""
        slug, email, password = self._signup_and_get_creds(client)
        r = client.post("/api/clinic-auth/login",
                        json={"email": email, "password": password})
        assert r.status_code == 200, f"Login failed: {r.json()}"
        assert "token" in r.json()
        assert r.json()["slug"] == slug

    def test_login_with_wrong_password_returns_json_401(self, client):
        """REG-005-F: wrong password returns JSON 401 (not plain text), so portal shows error."""
        slug, email, _ = self._signup_and_get_creds(client)
        r = client.post("/api/clinic-auth/login",
                        json={"email": email, "password": "wrong-password"})
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
        d = r.json()
        assert "error" in d, f"Response is not JSON with 'error': {r.text[:200]}"

    def test_login_with_wrong_email_returns_json_401(self, client):
        """REG-005-G: wrong email returns JSON 401 (not 404, prevents user enumeration)."""
        r = client.post("/api/clinic-auth/login",
                        json={"email": "nobody@nowhere.com", "password": "anypass"})
        assert r.status_code == 401
        assert "error" in r.json()

    def test_login_empty_email_returns_400(self, client):
        """REG-005-H: empty email/slug returns 400."""
        r = client.post("/api/clinic-auth/login",
                        json={"email": "", "slug": "", "password": "pass"})
        assert r.status_code == 400
        assert "error" in r.json()

    def test_login_then_profile_api(self, client):
        """REG-005-I: full flow — signup, login, profile API all succeed end-to-end."""
        global _ctr; _ctr += 1
        # Step 1: Signup
        sr = client.post("/api/signup", json={
            "practice_name": f"E2E Clinic {_ctr}",
            "contact_email": f"e2e{_ctr}@test.com",
            "password":      "E2EPass123!",
            "specialty":     "Urgent Care",
            "plan":          "professional",
        })
        assert sr.status_code == 200
        slug = sr.json()["slug"]

        # Step 2: Login (simulating the portal login form)
        lr = client.post("/api/clinic-auth/login",
                         json={"email": f"e2e{_ctr}@test.com", "password": "E2EPass123!"})
        assert lr.status_code == 200, f"Login failed: {lr.json()}"
        token = lr.json()["token"]

        # Step 3: Verify (what the portal JS does after login)
        vr = client.get("/api/clinic-auth/verify", headers={"X-Clinic-Token": token})
        assert vr.status_code == 200

        # Step 4: Profile API (first call after showDash())
        pr = client.get(f"/api/{slug}/profile", headers={"X-Clinic-Token": token})
        assert pr.status_code == 200, f"Profile failed: {pr.json()}"
        d = pr.json()
        assert "name" in d
        assert "reminder_72h_enabled" in d
        assert "agent_name" in d

    def test_portal_page_renders_for_trial_clinic(self, client, db):
        """REG-005-J: portal page renders 200 for a clinic created via /api/signup."""
        global _ctr; _ctr += 1
        sr = client.post("/api/signup", json={
            "practice_name": f"Portal Render {_ctr}",
            "contact_email": f"pr{_ctr}@test.com",
            "password":      "PortalRender123!",
            "specialty":     "ENT",
            "plan":          "starter",
        })
        assert sr.status_code == 200
        slug = sr.json()["slug"]

        r = client.get(f"/c/{slug}")
        assert r.status_code == 200, f"Portal returned {r.status_code}: {r.text[:200]}"
        assert "doLogin" in r.text
        assert "URLSearchParams" in r.text, "URL token auto-login code missing from portal"


class TestRateLimitReturnsJSON:
    """Rate-limit 429 response MUST be JSON so the portal login form can show the error."""

    def test_rate_limit_returns_json_on_login(self, client):
        """REG-005-K: 429 from login endpoint is JSON with 'error' key (not plain text)."""
        # Note: in TESTING=1 mode the rate limiter uses unique keys per request,
        # so it never actually triggers. We test the handler registration instead.
        # The handler is wired as _json_rate_limit_handler.
        from backend.main import app as the_app
        from slowapi.errors import RateLimitExceeded

        # Find the RateLimitExceeded exception handler
        handler = None
        for exc_class, exc_handler in the_app.exception_handlers.items():
            if exc_class is RateLimitExceeded:
                handler = exc_handler
                break

        assert handler is not None, "RateLimitExceeded handler not registered on app"
        # Verify it's our JSON handler, not the default plain-text one
        from slowapi import _rate_limit_exceeded_handler as default_handler
        assert handler != default_handler, (
            "Rate limit handler is still the default plain-text one — "
            "portal login form will fail to parse the 429 error"
        )
        handler_name = getattr(handler, '__name__', str(handler))
        assert 'json' in handler_name.lower() or 'rate' in handler_name.lower(), (
            f"Unexpected handler: {handler_name}"
        )
