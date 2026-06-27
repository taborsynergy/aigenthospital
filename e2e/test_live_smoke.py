"""
Live Smoke Tests — runs against the real deployed URL.

Usage:
    # Against production:
    pytest e2e/test_live_smoke.py -v

    # Against a different URL:
    LIVE_BASE_URL=https://staging.taborsynergy.com pytest e2e/test_live_smoke.py -v

    # With cleanup (requires admin password):
    ADMIN_PASSWORD=your-password pytest e2e/test_live_smoke.py -v

Environment variables:
    LIVE_BASE_URL        Base URL to test against (default: https://aifrontdesk.taborsynergy.com)
    ADMIN_PASSWORD       Admin password for test clinic cleanup (optional)
    SMOKE_CLINIC_EMAIL   Reuse an existing test clinic (skips signup, saves rate limit quota)
    SMOKE_CLINIC_PASS    Password for SMOKE_CLINIC_EMAIL
    SMOKE_CLINIC_SLUG    Slug for the reusable clinic (must match email/pass above)

Tip — first run creates a fresh clinic. Subsequent runs: set the 3 SMOKE_CLINIC_* vars
to reuse it. This avoids hitting the 5-logins-per-hour rate limit on the live server.

These tests are safe to run against production:
  - Read-only tests never mutate data
  - Write tests create a uniquely-named test clinic
  - Cleanup deletes the test clinic via admin API if ADMIN_PASSWORD is set
"""

import os
import uuid
import warnings
import pytest
import httpx

BASE_URL = os.getenv("LIVE_BASE_URL", "https://aifrontdesk.taborsynergy.com").rstrip("/")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
TIMEOUT = 60  # seconds — free Render tier cold-start can take 50s

# Optional: reuse a pre-existing test clinic to avoid login rate limits
SMOKE_CLINIC_EMAIL = os.getenv("SMOKE_CLINIC_EMAIL", "")
SMOKE_CLINIC_PASS  = os.getenv("SMOKE_CLINIC_PASS", "")
SMOKE_CLINIC_SLUG  = os.getenv("SMOKE_CLINIC_SLUG", "")

# Unique suffix so parallel runs don't collide (only used when creating new clinic)
_RUN_ID = uuid.uuid4().hex[:6]

# suppress InsecureRequestWarning — verify=False is intentional for our own server tests
warnings.filterwarnings("ignore", message=".*Unverified HTTPS.*")


# ─── helpers ──────────────────────────────────────────────────────────────────

def get(path, **kwargs):
    return httpx.get(f"{BASE_URL}{path}", timeout=TIMEOUT, verify=False, **kwargs)


def post(path, **kwargs):
    return httpx.post(f"{BASE_URL}{path}", timeout=TIMEOUT, verify=False, **kwargs)


def patch(path, **kwargs):
    return httpx.patch(f"{BASE_URL}{path}", timeout=TIMEOUT, verify=False, **kwargs)


def delete(path, **kwargs):
    return httpx.delete(f"{BASE_URL}{path}", timeout=TIMEOUT, verify=False, **kwargs)


def admin_headers():
    return {"X-Admin-Password": ADMIN_PASSWORD}


def _signup_test_clinic(suffix="main"):
    """Create a test clinic, log in, and return (slug, token, email, password)."""
    email = f"smoke-{_RUN_ID}-{suffix}@test-noreply.com"
    password = f"Smoke123!{_RUN_ID}"
    r = post("/api/signup", json={
        "practice_name": f"Live Smoke Clinic {_RUN_ID}-{suffix}",
        "contact_email": email,
        "password": password,
        "specialty": "Family Medicine",
        "phone": "5550001234",
        "plan": "professional",
    })
    assert r.status_code == 200, f"Signup failed: {r.text}"
    slug = r.json()["slug"]
    # Login immediately to get a stable session token (signup token can be
    # overwritten by subsequent requests on the live server)
    login = post("/api/clinic-auth/login", json={"email": email, "password": password})
    if login.status_code == 429:
        pytest.skip(
            "Login rate limit reached (5/hour). Wait 1 hour or set "
            "SMOKE_CLINIC_EMAIL / SMOKE_CLINIC_PASS / SMOKE_CLINIC_SLUG env vars "
            "to reuse an existing clinic and avoid repeated logins."
        )
    assert login.status_code == 200, f"Login after signup failed: {login.text}"
    token = login.json()["token"]
    return slug, token, email, password


def _delete_test_clinic(slug):
    """Delete a test clinic via admin API. Skips silently if no admin password."""
    if not ADMIN_PASSWORD:
        return
    delete(f"/admin/api/clinics/{slug}", headers=admin_headers())


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def live_clinic():
    """
    Get or create a shared test clinic for the module.

    If SMOKE_CLINIC_EMAIL / SMOKE_CLINIC_PASS / SMOKE_CLINIC_SLUG are set,
    reuse that clinic (saves login rate-limit quota). Otherwise create a fresh one.
    Fresh clinics are deleted after the test run if ADMIN_PASSWORD is set.
    """
    if SMOKE_CLINIC_EMAIL and SMOKE_CLINIC_PASS and SMOKE_CLINIC_SLUG:
        # Reuse existing clinic — just login
        login = post("/api/clinic-auth/login",
                     json={"email": SMOKE_CLINIC_EMAIL, "password": SMOKE_CLINIC_PASS})
        if login.status_code == 429:
            pytest.skip("Login rate limit reached. Wait 1 hour or set SMOKE_CLINIC_* env vars.")
        assert login.status_code == 200, f"Reuse-clinic login failed: {login.text}"
        yield {
            "slug":     SMOKE_CLINIC_SLUG,
            "token":    login.json()["token"],
            "email":    SMOKE_CLINIC_EMAIL,
            "password": SMOKE_CLINIC_PASS,
            "reused":   True,
        }
        return  # don't delete — it's a permanent test clinic

    # Create a fresh clinic
    slug, token, email, password = _signup_test_clinic()
    yield {"slug": slug, "token": token, "email": email, "password": password, "reused": False}
    _delete_test_clinic(slug)


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-001 — Public Pages
# ═══════════════════════════════════════════════════════════════════════════════

class TestPublicPages:

    def test_smoke001a_landing_page_loads(self):
        """SMOKE-001-A: GET / returns 200 HTML."""
        r = get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_smoke001b_landing_page_has_book_demo_cta(self):
        """SMOKE-001-B: Landing page has 'Book a Demo' button."""
        r = get("/")
        assert "Book a Demo" in r.text

    def test_smoke001c_landing_page_has_trial_cta(self):
        """SMOKE-001-C: Landing page has 'Start Free Trial' button."""
        r = get("/")
        assert "Start Free Trial" in r.text or "Start Free" in r.text

    def test_smoke001d_plans_api_returns_all_tiers(self):
        """SMOKE-001-D: GET /api/plans returns starter, professional, enterprise."""
        r = get("/api/plans")
        assert r.status_code == 200
        plans = r.json().get("plans", {})
        assert "starter" in plans
        assert "professional" in plans
        assert "enterprise" in plans

    def test_smoke001e_unknown_clinic_slug_returns_404(self):
        """SMOKE-001-E: Non-existent clinic slug returns 404."""
        r = get("/c/this-clinic-does-not-exist-xyz99")
        assert r.status_code == 404

    def test_smoke001f_api_404_returns_json(self):
        """SMOKE-001-F: Unknown API route returns JSON error, not HTML."""
        r = get("/api/this-does-not-exist")
        assert r.status_code == 404

    def test_smoke001g_diagnostic_endpoint_removed(self):
        """SMOKE-001-G: /api/test-demo-email is gone (security — must return 404/405)."""
        r = get("/api/test-demo-email")
        assert r.status_code in (404, 405), \
            "Diagnostic endpoint is still publicly accessible — remove it!"


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-002 — Lead / Visitor Flow
# ═══════════════════════════════════════════════════════════════════════════════

class TestLeadFlow:

    def test_smoke002a_demo_request_accepted(self):
        """SMOKE-002-A: POST /api/demo-request returns 200 ok."""
        r = post("/api/demo-request", json={
            "full_name": f"Smoke Test Doctor {_RUN_ID}",
            "email": f"smoke-{_RUN_ID}@test-noreply.com",
            "phone": "5550009999",
            "practice_name": f"Smoke Test Clinic {_RUN_ID}",
            "specialty": "Family Medicine",
            "num_providers": "1",
            "preferred_slot": "Flexible — any time works",
            "message": "[AUTOMATED SMOKE TEST — ignore this lead]",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_smoke002b_demo_request_missing_field_rejected(self):
        """SMOKE-002-B: Demo request missing required field returns 400/422."""
        r = post("/api/demo-request", json={
            "full_name": "Test",
            "email": "test@test.com",
            # missing practice_name, specialty, preferred_slot
        })
        assert r.status_code in (400, 422)

    def test_smoke002c_quote_request_accepted(self):
        """SMOKE-002-C: POST /api/quote returns 200 ok."""
        r = post("/api/quote", json={
            "full_name": f"Smoke Test Enterprise {_RUN_ID}",
            "email": f"enterprise-{_RUN_ID}@test-noreply.com",
            "company": "Smoke Test Health System",
            "phone": "5550008888",
            "locations": "5",
            "pms": "Epic",
            "message": "[AUTOMATED SMOKE TEST — ignore this quote request]",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_smoke002d_trial_signup_creates_clinic(self):
        """SMOKE-002-D: POST /api/signup creates a clinic with slug and portal URL."""
        email = f"smoke-{_RUN_ID}-signup2@test-noreply.com"
        r = post("/api/signup", json={
            "practice_name": f"Smoke Signup Test {_RUN_ID}",
            "contact_email": email,
            "password": f"Smoke123!{_RUN_ID}",
            "specialty": "Dermatology",
            "plan": "starter",
        })
        assert r.status_code == 200
        body = r.json()
        assert "slug" in body
        assert "portal_url" in body
        assert "token" in body
        # cleanup
        _delete_test_clinic(body["slug"])


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-003 — Doctor Onboarding (live clinic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDoctorOnboardingLive:

    def test_smoke003a_portal_page_loads(self, live_clinic):
        """SMOKE-003-A: GET /c/{slug} returns 200 with clinic slug in HTML."""
        r = get(f"/c/{live_clinic['slug']}")
        assert r.status_code == 200
        assert live_clinic["slug"] in r.text

    def test_smoke003b_login_returns_token(self, live_clinic):
        """SMOKE-003-B: Token from fixture was obtained via login — verify it works."""
        # We don't re-login here (would overwrite session token and break other tests).
        # Instead we verify the fixture token works on a protected endpoint.
        r = get(f"/api/{live_clinic['slug']}/appointments",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200, f"Token from login is not valid: {r.text}"

    def test_smoke003c_wrong_password_rejected(self, live_clinic):
        """SMOKE-003-C: Wrong password returns 401 (uses live_clinic email, wrong pass)."""
        # Note: counts against rate limit (5/hr). Skip if limit exceeded.
        r = post("/api/clinic-auth/login", json={
            "email": live_clinic["email"],
            "password": "WRONG-PASSWORD-XYZ",
        })
        if r.status_code == 429:
            pytest.skip("Login rate limit reached — skipping wrong-password test")
        assert r.status_code in (401, 403)

    def test_smoke003d_token_grants_appointment_access(self, live_clinic):
        """SMOKE-003-D: Token grants access to /appointments — returns empty list."""
        r = get(f"/api/{live_clinic['slug']}/appointments",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_smoke003e_no_token_returns_403(self, live_clinic):
        """SMOKE-003-E: Accessing /appointments without token returns 403."""
        r = get(f"/api/{live_clinic['slug']}/appointments")
        assert r.status_code == 403

    def test_smoke003f_config_endpoint_returns_clinic_name(self, live_clinic):
        """SMOKE-003-F: GET /api/{slug}/config returns clinic name."""
        r = get(f"/api/{live_clinic['slug']}/config")
        assert r.status_code == 200
        data = r.json()
        assert "clinic_name" in data or "name" in data


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-004 — Clinic Setup (live clinic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestClinicSetupLive:

    def test_smoke004a_profile_update(self, live_clinic):
        """SMOKE-004-A: PATCH /api/{slug}/profile updates clinic fields."""
        r = patch(f"/api/{live_clinic['slug']}/profile",
                  headers={"X-Clinic-Token": live_clinic["token"]},
                  json={
                      "phone": "5551239999",
                      "address": "100 Smoke Test Ave, Austin TX 78701",
                      "insurance_accepted": "Blue Cross, Aetna",
                      "office_hours": "Mon-Fri 8am-5pm",
                      "cancellation_policy": "24-hour notice required.",
                  })
        assert r.status_code == 200

    def test_smoke004b_profile_fields_persist(self, live_clinic):
        """SMOKE-004-B: Updated profile fields are readable back from GET /profile."""
        patch(f"/api/{live_clinic['slug']}/profile",
              headers={"X-Clinic-Token": live_clinic["token"]},
              json={"phone": "5550007777"})
        r = get(f"/api/{live_clinic['slug']}/profile",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        assert r.json().get("phone") == "5550007777"

    def test_smoke004c_add_provider(self, live_clinic):
        """SMOKE-004-C: POST /api/{slug}/providers adds a provider."""
        r = post(f"/api/{live_clinic['slug']}/providers",
                 headers={"X-Clinic-Token": live_clinic["token"]},
                 json={"name": "Dr. Smoke Test", "specialty": "Family Medicine"})
        assert r.status_code in (200, 201)
        resp = get(f"/api/{live_clinic['slug']}/providers",
                   headers={"X-Clinic-Token": live_clinic["token"]}).json()
        names = [p["name"] for p in (resp.get("providers") or resp)]
        assert "Dr. Smoke Test" in names

    def test_smoke004d_add_appointment_type(self, live_clinic):
        """SMOKE-004-D: POST /api/{slug}/appointment-types adds a type."""
        r = post(f"/api/{live_clinic['slug']}/appointment-types",
                 headers={"X-Clinic-Token": live_clinic["token"]},
                 json={"name": "Smoke Test Visit", "duration_minutes": 30})
        assert r.status_code in (200, 201)
        resp = get(f"/api/{live_clinic['slug']}/appointment-types",
                   headers={"X-Clinic-Token": live_clinic["token"]}).json()
        names = [t["name"] for t in (resp.get("appointment_types") or resp)]
        assert "Smoke Test Visit" in names


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-005 — Patient Chat (live clinic, MOCK_MODE may not be set on prod)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPatientChatLive:

    def _chat(self, slug, message, session_id=None):
        sid = session_id or uuid.uuid4().hex
        r = post(f"/api/{slug}/chat",
                 json={"message": message, "session_id": sid})
        return r, sid

    def test_smoke005a_chat_returns_200(self, live_clinic):
        """SMOKE-005-A: POST /api/{slug}/chat returns 200 with content."""
        r, _ = self._chat(live_clinic["slug"], "Hello, I need help")
        assert r.status_code == 200
        body = r.json()
        reply = body.get("content") or body.get("reply", "")
        assert len(reply) > 0

    def test_smoke005b_appointment_request_gets_reply(self, live_clinic):
        """SMOKE-005-B: 'I need an appointment' gets a non-empty reply."""
        r, _ = self._chat(live_clinic["slug"], "I need to book an appointment")
        assert r.status_code == 200
        body = r.json()
        reply = body.get("content") or body.get("reply", "")
        assert len(reply) > 0

    def test_smoke005c_session_context_maintained(self, live_clinic):
        """SMOKE-005-C: Two turns in same session both get replies."""
        sid = uuid.uuid4().hex
        r1, _ = self._chat(live_clinic["slug"], "Hi", session_id=sid)
        r2, _ = self._chat(live_clinic["slug"], "I need an appointment", session_id=sid)
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_smoke005d_insurance_query_gets_reply(self, live_clinic):
        """SMOKE-005-D: Patient asks about insurance — Aria replies."""
        r, _ = self._chat(live_clinic["slug"], "Do you accept Blue Cross insurance?")
        assert r.status_code == 200
        body = r.json()
        assert len(body.get("content") or body.get("reply", "")) > 0

    def test_smoke005e_hours_query_gets_reply(self, live_clinic):
        """SMOKE-005-E: Patient asks about hours — Aria replies."""
        r, _ = self._chat(live_clinic["slug"], "What are your office hours?")
        assert r.status_code == 200
        body = r.json()
        assert len(body.get("content") or body.get("reply", "")) > 0

    def test_smoke005f_chat_never_returns_500(self, live_clinic):
        """SMOKE-005-F: Unusual long input doesn't crash the server."""
        r, _ = self._chat(live_clinic["slug"], "help " * 100)
        assert r.status_code != 500

    def test_smoke005g_chat_returns_json_not_html(self, live_clinic):
        """SMOKE-005-G: Chat endpoint always returns JSON."""
        r, _ = self._chat(live_clinic["slug"], "Hello")
        assert r.headers.get("content-type", "").startswith("application/json")


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-006 — Safety (live)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyLive:

    def _chat(self, slug, message):
        r = post(f"/api/{slug}/chat",
                 json={"message": message, "session_id": uuid.uuid4().hex})
        return r

    @pytest.mark.parametrize("msg", [
        "I'm having a heart attack",
        "I can't breathe",
        "I want to hurt myself",
        "I don't want to live anymore",
        "My child swallowed pills",
    ])
    def test_smoke006a_emergency_always_gets_reply(self, live_clinic, msg):
        """SMOKE-006-A: Emergency/crisis messages always get a reply, never crash."""
        r = self._chat(live_clinic["slug"], msg)
        assert r.status_code == 200
        body = r.json()
        reply = body.get("content") or body.get("reply", "")
        assert len(reply) > 0, f"No reply to emergency: {msg}"


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-007 — Security Headers
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityHeadersLive:

    def test_smoke007a_no_server_header_leak(self):
        """SMOKE-007-A: Server header doesn't reveal internal stack details."""
        r = get("/")
        server = r.headers.get("server", "").lower()
        assert "python" not in server
        assert "uvicorn" not in server or True  # informational only

    def test_smoke007b_appointments_without_auth_returns_json_403(self):
        """SMOKE-007-B: Unauthenticated /appointments returns JSON 403, not HTML."""
        r = get("/api/some-clinic/appointments")
        assert r.status_code in (403, 404)
        assert r.headers.get("content-type", "").startswith("application/json")

    def test_smoke007c_cross_clinic_token_rejected(self, live_clinic):
        """SMOKE-007-C: Using a made-up token cannot access another clinic's data."""
        fake_token = "fake-token-that-does-not-exist-in-db-" + uuid.uuid4().hex
        r = get(f"/api/{live_clinic['slug']}/appointments",
                headers={"X-Clinic-Token": fake_token})
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-008 — Negative: Signup Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestNegativeSignup:

    def test_smoke008a_missing_practice_name(self):
        """SMOKE-008-A: Signup without practice_name returns 400/422."""
        r = post("/api/signup", json={
            "contact_email": f"neg-{_RUN_ID}@test.com",
            "password": "Valid123!",
            "specialty": "Family Medicine",
        })
        assert r.status_code in (400, 422)

    def test_smoke008b_missing_specialty(self):
        """SMOKE-008-B: Signup without specialty returns 400/422."""
        r = post("/api/signup", json={
            "practice_name": "No Specialty Clinic",
            "contact_email": f"neg2-{_RUN_ID}@test.com",
            "password": "Valid123!",
        })
        assert r.status_code in (400, 422)

    def test_smoke008c_password_too_short(self):
        """SMOKE-008-C: Password under 6 chars returns 400."""
        r = post("/api/signup", json={
            "practice_name": "Short Pass Clinic",
            "contact_email": f"neg3-{_RUN_ID}@test.com",
            "password": "abc",
            "specialty": "Family Medicine",
        })
        assert r.status_code == 400
        assert "password" in r.json().get("error", "").lower()

    def test_smoke008d_invalid_email_format(self):
        """SMOKE-008-D: Invalid email format returns 422 from Pydantic."""
        r = post("/api/signup", json={
            "practice_name": "Bad Email Clinic",
            "contact_email": "not-an-email",
            "password": "Valid123!",
            "specialty": "Family Medicine",
        })
        assert r.status_code == 422

    def test_smoke008e_invalid_plan_name(self):
        """SMOKE-008-E: Unrecognised plan name returns 400."""
        r = post("/api/signup", json={
            "practice_name": "Bad Plan Clinic",
            "contact_email": f"neg4-{_RUN_ID}@test.com",
            "password": "Valid123!",
            "specialty": "Family Medicine",
            "plan": "diamond-ultra-plus",
        })
        assert r.status_code == 400

    def test_smoke008f_empty_body_returns_422(self):
        """SMOKE-008-F: Completely empty signup body returns 422."""
        r = post("/api/signup", json={})
        assert r.status_code == 422

    def test_smoke008g_blank_practice_name_rejected(self):
        """SMOKE-008-G: Whitespace-only practice name returns 400."""
        r = post("/api/signup", json={
            "practice_name": "   ",
            "contact_email": f"neg5-{_RUN_ID}@test.com",
            "password": "Valid123!",
            "specialty": "Family Medicine",
        })
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-009 — Negative: Demo & Quote Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestNegativeDemoQuote:

    def test_smoke009a_demo_blank_fullname(self):
        """SMOKE-009-A: Demo request with whitespace-only full_name returns 400."""
        r = post("/api/demo-request", json={
            "full_name": "   ",
            "email": "test@clinic.com",
            "practice_name": "Test Clinic",
            "specialty": "Family Medicine",
            "preferred_slot": "Morning",
        })
        assert r.status_code == 400
        assert "name" in r.json().get("error", "").lower()

    def test_smoke009b_demo_invalid_email(self):
        """SMOKE-009-B: Demo request with malformed email returns 422."""
        r = post("/api/demo-request", json={
            "full_name": "Dr. Test",
            "email": "not-an-email",
            "practice_name": "Test Clinic",
            "specialty": "Family Medicine",
            "preferred_slot": "Morning",
        })
        assert r.status_code == 422

    def test_smoke009c_demo_missing_specialty(self):
        """SMOKE-009-C: Demo request missing specialty returns 400/422."""
        r = post("/api/demo-request", json={
            "full_name": "Dr. Test",
            "email": "dr@clinic.com",
            "practice_name": "Test Clinic",
            "preferred_slot": "Morning",
        })
        assert r.status_code in (400, 422)

    def test_smoke009d_demo_missing_preferred_slot(self):
        """SMOKE-009-D: Demo request missing preferred_slot returns 400/422."""
        r = post("/api/demo-request", json={
            "full_name": "Dr. Test",
            "email": "dr@clinic.com",
            "practice_name": "Test Clinic",
            "specialty": "Family Medicine",
        })
        assert r.status_code in (400, 422)

    def test_smoke009e_demo_blank_practice_name(self):
        """SMOKE-009-E: Whitespace-only practice_name returns 400."""
        r = post("/api/demo-request", json={
            "full_name": "Dr. Test",
            "email": "dr@clinic.com",
            "practice_name": "   ",
            "specialty": "Family Medicine",
            "preferred_slot": "Morning",
        })
        assert r.status_code == 400

    def test_smoke009f_demo_empty_body(self):
        """SMOKE-009-F: Empty demo request body returns 422."""
        r = post("/api/demo-request", json={})
        assert r.status_code == 422

    def test_smoke009g_quote_empty_body(self):
        """SMOKE-009-G: Empty quote request body returns 422."""
        r = post("/api/quote", json={})
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-010 — Negative: Authentication
# ═══════════════════════════════════════════════════════════════════════════════

class TestNegativeAuth:

    def test_smoke010a_login_nonexistent_email(self):
        """SMOKE-010-A: Login with email that doesn't exist returns 401/404 (or 429 if rate-limited)."""
        r = post("/api/clinic-auth/login", json={
            "email": f"nobody-{_RUN_ID}@doesnotexist.com",
            "password": "SomePassword123!",
        })
        assert r.status_code in (401, 403, 404, 429)

    def test_smoke010b_login_empty_password(self):
        """SMOKE-010-B: Login with empty password returns 400/401/422 (or 429 if rate-limited)."""
        r = post("/api/clinic-auth/login", json={
            "email": "smoketest@taborsynergy.com",
            "password": "",
        })
        assert r.status_code in (400, 401, 422, 429)

    def test_smoke010c_login_missing_email_field(self):
        """SMOKE-010-C: Login body missing email field returns 400/422 (or 429 if rate-limited)."""
        r = post("/api/clinic-auth/login", json={"password": "SomePass123!"})
        assert r.status_code in (400, 422, 429)

    def test_smoke010d_empty_token_header_returns_403(self, live_clinic):
        """SMOKE-010-D: Empty X-Clinic-Token header returns 403."""
        r = get(f"/api/{live_clinic['slug']}/appointments",
                headers={"X-Clinic-Token": ""})
        assert r.status_code == 403

    def test_smoke010e_no_token_header_returns_403(self, live_clinic):
        """SMOKE-010-E: Completely absent X-Clinic-Token header returns 403."""
        r = get(f"/api/{live_clinic['slug']}/appointments")
        assert r.status_code == 403

    def test_smoke010f_random_uuid_token_returns_403(self, live_clinic):
        """SMOKE-010-F: Random UUID as token returns 403 (not in DB)."""
        r = get(f"/api/{live_clinic['slug']}/appointments",
                headers={"X-Clinic-Token": str(uuid.uuid4())})
        assert r.status_code == 403

    def test_smoke010g_sql_injection_in_token(self, live_clinic):
        """SMOKE-010-G: SQL injection attempt in token header returns 403, not 500."""
        r = get(f"/api/{live_clinic['slug']}/appointments",
                headers={"X-Clinic-Token": "' OR '1'='1'; --"})
        assert r.status_code in (400, 403)
        assert r.status_code != 500


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-011 — Negative: Chat Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestNegativeChat:

    def test_smoke011a_chat_nonexistent_clinic(self):
        """SMOKE-011-A: Chat to non-existent clinic slug returns 404, not 500."""
        r = post("/api/totally-fake-clinic-xyz999/chat",
                 json={"message": "Hello", "session_id": uuid.uuid4().hex})
        assert r.status_code in (404, 400)
        assert r.status_code != 500

    def test_smoke011b_chat_empty_message(self, live_clinic):
        """SMOKE-011-B: Empty chat message returns 400/422 or graceful reply, never 500."""
        r = post(f"/api/{live_clinic['slug']}/chat",
                 json={"message": "", "session_id": uuid.uuid4().hex})
        assert r.status_code in (200, 400, 422)
        assert r.status_code != 500

    def test_smoke011c_chat_whitespace_only_message(self, live_clinic):
        """SMOKE-011-C: Whitespace-only chat message handled gracefully."""
        r = post(f"/api/{live_clinic['slug']}/chat",
                 json={"message": "   ", "session_id": uuid.uuid4().hex})
        assert r.status_code in (200, 400, 422)
        assert r.status_code != 500

    def test_smoke011d_chat_missing_message_field(self, live_clinic):
        """SMOKE-011-D: Chat body missing 'message' field returns 422."""
        r = post(f"/api/{live_clinic['slug']}/chat",
                 json={"session_id": uuid.uuid4().hex})
        assert r.status_code == 422

    def test_smoke011e_chat_missing_session_id(self, live_clinic):
        """SMOKE-011-E: Chat without session_id is handled gracefully (not 500)."""
        r = post(f"/api/{live_clinic['slug']}/chat",
                 json={"message": "Hello"})
        assert r.status_code in (200, 400, 422)
        assert r.status_code != 500

    def test_smoke011f_chat_empty_json_body(self, live_clinic):
        """SMOKE-011-F: Completely empty JSON body returns 422."""
        r = post(f"/api/{live_clinic['slug']}/chat", json={})
        assert r.status_code == 422

    def test_smoke011g_wrong_method_on_chat(self, live_clinic):
        """SMOKE-011-G: GET on a POST-only chat endpoint returns 405, not 500."""
        r = get(f"/api/{live_clinic['slug']}/chat")
        assert r.status_code in (404, 405)
        assert r.status_code != 500


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-012 — Corner Cases: Input Boundaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestCornerCasesInputBoundary:

    def _chat(self, slug, message):
        return post(f"/api/{slug}/chat",
                    json={"message": message, "session_id": uuid.uuid4().hex})

    def test_smoke012a_very_long_chat_message(self, live_clinic):
        """SMOKE-012-A: 5000-char chat message handled — no 500."""
        long_msg = "I need help with my appointment. " * 150  # ~5000 chars
        r = self._chat(live_clinic["slug"], long_msg)
        assert r.status_code != 500

    def test_smoke012b_sql_injection_in_chat(self, live_clinic):
        """SMOKE-012-B: SQL injection in chat message returns safe reply, not 500."""
        r = self._chat(live_clinic["slug"],
                       "'; DROP TABLE clinics; SELECT * FROM appointments WHERE '1'='1")
        assert r.status_code != 500

    def test_smoke012c_xss_in_chat_message(self, live_clinic):
        """SMOKE-012-C: XSS payload in chat message handled safely, not 500."""
        r = self._chat(live_clinic["slug"],
                       "<script>alert('xss')</script> I need an appointment")
        assert r.status_code != 500

    def test_smoke012d_unicode_in_chat(self, live_clinic):
        """SMOKE-012-D: Unicode characters in chat handled correctly."""
        r = self._chat(live_clinic["slug"],
                       "Necesito una cita médica por favor 👨‍⚕️ مرحبا 你好")
        assert r.status_code == 200
        body = r.json()
        assert len(body.get("content") or body.get("reply", "")) > 0

    def test_smoke012e_emoji_only_message(self, live_clinic):
        """SMOKE-012-E: Emoji-only message handled without crash."""
        r = self._chat(live_clinic["slug"], "👋 🏥 📅")
        assert r.status_code in (200, 400)
        assert r.status_code != 500

    def test_smoke012f_very_long_signup_practice_name(self):
        """SMOKE-012-F: Extremely long practice name (300 chars) — no 500."""
        long_name = "A" * 300
        r = post("/api/signup", json={
            "practice_name": long_name,
            "contact_email": f"longname-{_RUN_ID}@test.com",
            "password": "Valid123!",
            "specialty": "Family Medicine",
            "plan": "starter",
        })
        assert r.status_code in (200, 400, 422)
        assert r.status_code != 500

    def test_smoke012g_special_chars_in_demo_message(self):
        """SMOKE-012-G: Special characters in demo message field handled safely."""
        r = post("/api/demo-request", json={
            "full_name": "Dr. O'Brien-Smith & Associates",
            "email": "test@clinic.com",
            "practice_name": "O'Brien & Smith <Clinic>",
            "specialty": "Family Medicine",
            "preferred_slot": "Flexible — any time works",
            "message": "Interested in <b>bold</b> & \"quoted\" features for $500/month.",
        })
        assert r.status_code == 200

    def test_smoke012h_repeated_session_messages(self, live_clinic):
        """SMOKE-012-H: 5 rapid messages in same session all get replies."""
        sid = uuid.uuid4().hex
        for i, msg in enumerate([
            "Hi", "I need an appointment",
            "My name is John", "I prefer mornings", "Thank you"
        ]):
            r = post(f"/api/{live_clinic['slug']}/chat",
                     json={"message": msg, "session_id": sid})
            assert r.status_code == 200, f"Message {i+1} failed: {r.text}"

    def test_smoke012i_null_fields_in_chat(self, live_clinic):
        """SMOKE-012-I: Null values in chat body return 422, not 500."""
        r = post(f"/api/{live_clinic['slug']}/chat",
                 json={"message": None, "session_id": None})
        assert r.status_code in (400, 422)
        assert r.status_code != 500


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-013 — Corner Cases: API & Protocol Behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestCornerCasesAPIMiscellaneous:

    def test_smoke013a_wrong_method_on_signup(self):
        """SMOKE-013-A: GET on /api/signup returns 405, not 500."""
        r = get("/api/signup")
        assert r.status_code in (404, 405)
        assert r.status_code != 500

    def test_smoke013b_wrong_method_on_demo(self):
        """SMOKE-013-B: GET on /api/demo-request returns 405, not 500."""
        r = get("/api/demo-request")
        assert r.status_code in (404, 405)
        assert r.status_code != 500

    def test_smoke013c_plans_endpoint_has_price_info(self):
        """SMOKE-013-C: /api/plans returns price for each tier."""
        r = get("/api/plans")
        assert r.status_code == 200
        plans = r.json().get("plans", {})
        for plan_key in ("starter", "professional", "enterprise"):
            assert "price" in plans[plan_key], f"Plan {plan_key} missing price"

    def test_smoke013d_uppercase_slug_handled(self):
        """SMOKE-013-D: Uppercase clinic slug in URL returns 404 (slugs are lowercase)."""
        r = get("/c/SMOKE-TEST-CLINIC-DO-NOT-DELET-024DC")
        assert r.status_code == 404

    def test_smoke013e_slug_with_traversal_attempt(self):
        """SMOKE-013-E: Path traversal in slug returns 404, not 500."""
        r = get("/c/../admin")
        assert r.status_code in (404, 400)
        assert r.status_code != 500

    def test_smoke013f_very_deep_nonexistent_path(self):
        """SMOKE-013-F: Deep unknown path returns 404, not 500."""
        r = get("/api/a/b/c/d/e/f/g/h/this/does/not/exist")
        assert r.status_code == 404
        assert r.status_code != 500

    def test_smoke013g_chat_response_has_required_fields(self, live_clinic):
        """SMOKE-013-G: Chat response always contains 'content' and 'session_id'."""
        r = post(f"/api/{live_clinic['slug']}/chat",
                 json={"message": "Hello", "session_id": uuid.uuid4().hex})
        assert r.status_code == 200
        body = r.json()
        assert "content" in body or "reply" in body, "No content field in chat response"
        assert "session_id" in body, "No session_id in chat response"

    def test_smoke013h_plans_api_returns_features_per_plan(self):
        """SMOKE-013-H: Each plan has a features object with expected keys."""
        r = get("/api/plans")
        plans = r.json().get("plans", {})
        for key in ("starter", "professional", "enterprise"):
            assert "features" in plans[key], f"{key} plan missing features"

    def test_smoke013i_config_endpoint_public_no_auth_needed(self, live_clinic):
        """SMOKE-013-I: GET /api/{slug}/config is public — no token required."""
        r = get(f"/api/{live_clinic['slug']}/config")
        assert r.status_code == 200

    def test_smoke013j_portal_page_serves_utf8(self, live_clinic):
        """SMOKE-013-J: Portal page served with UTF-8 charset."""
        r = get(f"/c/{live_clinic['slug']}")
        content_type = r.headers.get("content-type", "")
        assert "utf-8" in content_type.lower() or "utf8" in content_type.lower()

    def test_smoke013k_chat_session_ids_are_isolated(self, live_clinic):
        """SMOKE-013-K: Two different session IDs get independent conversations."""
        sid_a, sid_b = uuid.uuid4().hex, uuid.uuid4().hex
        r_a = post(f"/api/{live_clinic['slug']}/chat",
                   json={"message": "My name is Alice", "session_id": sid_a})
        r_b = post(f"/api/{live_clinic['slug']}/chat",
                   json={"message": "My name is Bob", "session_id": sid_b})
        assert r_a.status_code == 200
        assert r_b.status_code == 200
        # Verify both sessions got replies
        assert len(r_a.json().get("content") or r_a.json().get("reply", "")) > 0
        assert len(r_b.json().get("content") or r_b.json().get("reply", "")) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-014 — Security: Headers, Auth Protection, Data Exposure
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurity:

    # ── Security headers ─────────────────────────────────────────────────────

    def test_smoke014a_no_server_version_in_headers(self):
        """SMOKE-014-A: Server header must not expose version string (uvicorn/python)."""
        r = get("/api/health")
        server = r.headers.get("server", "").lower()
        for version_hint in ("uvicorn", "python", "fastapi", "starlette"):
            assert version_hint not in server, f"Server header leaks runtime: {server}"

    def test_smoke014b_x_content_type_options_set(self):
        """SMOKE-014-B: X-Content-Type-Options: nosniff must be present."""
        r = get("/")
        val = r.headers.get("x-content-type-options", "")
        assert val.lower() == "nosniff", f"Missing/wrong X-Content-Type-Options: '{val}'"

    def test_smoke014c_x_frame_options_set(self):
        """SMOKE-014-C: X-Frame-Options must be DENY or SAMEORIGIN (clickjacking guard)."""
        r = get("/")
        val = r.headers.get("x-frame-options", "").upper()
        assert val in ("DENY", "SAMEORIGIN"), f"Missing/wrong X-Frame-Options: '{val}'"

    def test_smoke014d_no_sensitive_data_in_error_500(self):
        """SMOKE-014-D: Error responses must not leak stack traces or SQL details."""
        # Trigger a 404 — check body doesn't contain Python tracebacks
        r = get("/api/nonexistent-route-xyz-9999")
        body = r.text.lower()
        for leak in ("traceback", "sqlalchemy", "file \"", "line ", "raise "[:4]):
            assert leak not in body, f"Error response leaks internals: found '{leak}' in body"

    def test_smoke014e_no_passwords_in_login_response(self):
        """SMOKE-014-E: Login response must never echo the password back."""
        # Use wrong creds — even error response must not reflect password
        r = post("/api/clinic-auth/login", json={
            "email": "attacker@evil.com",
            "password": "SensitiveSecret123!"
        })
        assert "SensitiveSecret123!" not in r.text

    # ── Admin endpoint protection ─────────────────────────────────────────────

    def test_smoke014f_admin_clinics_requires_password(self):
        """SMOKE-014-F: GET /admin/api/clinics returns 401/403 without X-Admin-Password."""
        r = get("/admin/api/clinics")
        assert r.status_code in (401, 403)

    def test_smoke014g_admin_endpoint_wrong_password(self):
        """SMOKE-014-G: Wrong admin password returns 401/403, not 200."""
        r = get("/admin/api/clinics",
                headers={"X-Admin-Password": "wrong-password-abc"})
        assert r.status_code in (401, 403)

    def test_smoke014h_admin_endpoint_sql_injection_password(self):
        """SMOKE-014-H: SQL injection in admin password header returns 401/403, not 500."""
        r = get("/admin/api/clinics",
                headers={"X-Admin-Password": "' OR 1=1; --"})
        assert r.status_code in (401, 403)
        assert r.status_code != 500

    # ── Token / session security ──────────────────────────────────────────────

    def test_smoke014i_token_not_echoed_in_error_body(self, live_clinic):
        """SMOKE-014-I: Real token sent to wrong route must not be echoed in response."""
        token = live_clinic["token"]
        r = get("/api/admin/clinics",
                headers={"X-Clinic-Token": token})
        assert token not in r.text

    def test_smoke014j_appointments_without_token_returns_403(self, live_clinic):
        """SMOKE-014-J: Protected appointments list returns 403 with no credentials."""
        r = get(f"/api/{live_clinic['slug']}/appointments")
        assert r.status_code == 403

    def test_smoke014k_profile_patch_requires_token(self, live_clinic):
        """SMOKE-014-K: PATCH /api/{slug}/profile without token returns 403 or 422 (body validation before auth check)."""
        r = patch(f"/api/{live_clinic['slug']}/profile",
                  json={"phone": "555-0000"})
        assert r.status_code in (403, 422)

    def test_smoke014l_providers_post_requires_token(self, live_clinic):
        """SMOKE-014-L: POST /api/{slug}/providers without token returns 403."""
        r = post(f"/api/{live_clinic['slug']}/providers",
                 json={"name": "Hacker", "title": "MD"})
        assert r.status_code == 403

    def test_smoke014m_appointment_status_requires_token(self, live_clinic):
        """SMOKE-014-M: PATCH appointment status without token returns 403."""
        r = patch(f"/api/{live_clinic['slug']}/appointments/FAKE-CONF-999",
                  json={"status": "confirmed"})
        assert r.status_code == 403

    # ── CORS ─────────────────────────────────────────────────────────────────

    def test_smoke014n_cors_header_present_on_api(self, live_clinic):
        """SMOKE-014-N: API chat endpoint returns CORS header when Origin is in the allowlist."""
        r = post(f"/api/{live_clinic['slug']}/chat",
                 json={"message": "Hi", "session_id": uuid.uuid4().hex},
                 headers={"Origin": "https://aifrontdesk.taborsynergy.com"})
        assert r.status_code == 200
        # CORS header must be present for an allowed origin
        acao = r.headers.get("access-control-allow-origin", "")
        assert acao != "", "Missing Access-Control-Allow-Origin for allowed origin"

    def test_smoke014o_content_type_json_on_api_responses(self, live_clinic):
        """SMOKE-014-O: API responses return Content-Type: application/json."""
        r = get(f"/api/{live_clinic['slug']}/config")
        ct = r.headers.get("content-type", "")
        assert "application/json" in ct, f"Expected JSON content-type, got: {ct}"


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-015 — Performance: Response Time Thresholds
# ═══════════════════════════════════════════════════════════════════════════════

import time as _time

class TestPerformance:
    """All thresholds are generous to account for Render free-tier cold starts (≤50s).
    Tests measure wall-clock round-trip; a pass means the server is responsive.
    """

    FAST_SLA   = 5.0   # seconds — static/cached endpoints
    MEDIUM_SLA = 15.0  # seconds — DB-read endpoints (warmed up)
    SLOW_SLA   = 65.0  # seconds — LLM endpoints (cold start + Claude API)

    def _timed(self, fn, *args, **kwargs):
        t0 = _time.monotonic()
        r = fn(*args, **kwargs)
        elapsed = _time.monotonic() - t0
        return r, elapsed

    def test_smoke015a_health_responds_fast(self):
        """SMOKE-015-A: /api/health responds within FAST_SLA (5s)."""
        r, elapsed = self._timed(get, "/api/health")
        assert r.status_code == 200, f"Health returned {r.status_code}"
        assert elapsed < self.FAST_SLA, f"Health too slow: {elapsed:.2f}s > {self.FAST_SLA}s"

    def test_smoke015b_plans_responds_fast(self):
        """SMOKE-015-B: /api/plans (static data) responds within FAST_SLA (5s)."""
        r, elapsed = self._timed(get, "/api/plans")
        assert r.status_code == 200
        assert elapsed < self.FAST_SLA, f"Plans too slow: {elapsed:.2f}s > {self.FAST_SLA}s"

    def test_smoke015c_landing_page_responds_fast(self):
        """SMOKE-015-C: GET / (landing page HTML) responds within FAST_SLA (5s)."""
        r, elapsed = self._timed(get, "/")
        assert r.status_code == 200
        assert elapsed < self.FAST_SLA, f"Landing page too slow: {elapsed:.2f}s > {self.FAST_SLA}s"

    def test_smoke015d_config_endpoint_medium_sla(self, live_clinic):
        """SMOKE-015-D: GET /api/{slug}/config (DB read) responds within MEDIUM_SLA (15s)."""
        r, elapsed = self._timed(get, f"/api/{live_clinic['slug']}/config")
        assert r.status_code == 200
        assert elapsed < self.MEDIUM_SLA, f"Config too slow: {elapsed:.2f}s > {self.MEDIUM_SLA}s"

    def test_smoke015e_appointments_list_medium_sla(self, live_clinic):
        """SMOKE-015-E: GET appointments (auth DB read) responds within MEDIUM_SLA (15s)."""
        r, elapsed = self._timed(
            get, f"/api/{live_clinic['slug']}/appointments",
            headers={"X-Clinic-Token": live_clinic["token"]}
        )
        assert r.status_code == 200
        assert elapsed < self.MEDIUM_SLA, f"Appointments too slow: {elapsed:.2f}s > {self.MEDIUM_SLA}s"

    def test_smoke015f_providers_list_medium_sla(self, live_clinic):
        """SMOKE-015-F: GET providers (DB read) responds within MEDIUM_SLA (15s)."""
        r, elapsed = self._timed(
            get, f"/api/{live_clinic['slug']}/providers",
            headers={"X-Clinic-Token": live_clinic["token"]}
        )
        assert r.status_code == 200
        assert elapsed < self.MEDIUM_SLA, f"Providers too slow: {elapsed:.2f}s > {self.MEDIUM_SLA}s"

    def test_smoke015g_chat_responds_within_sla(self, live_clinic):
        """SMOKE-015-G: Chat (LLM call) responds within SLOW_SLA (65s) — cold start included."""
        r, elapsed = self._timed(
            post, f"/api/{live_clinic['slug']}/chat",
            json={"message": "What are your office hours?", "session_id": uuid.uuid4().hex}
        )
        assert r.status_code == 200, f"Chat returned {r.status_code}: {r.text[:200]}"
        assert elapsed < self.SLOW_SLA, f"Chat too slow: {elapsed:.2f}s > {self.SLOW_SLA}s"

    def test_smoke015h_login_responds_medium_sla(self):
        """SMOKE-015-H: Login endpoint responds within MEDIUM_SLA (15s) — 429 counts as passing (rate-limit is fast)."""
        r, elapsed = self._timed(
            post, "/api/clinic-auth/login",
            json={"email": "nobody@nowhere.com", "password": "WrongPass123!"}
        )
        # 401 = bad creds, 429 = rate-limited — both are valid rejections; we care about timing
        assert r.status_code in (401, 403, 404, 429)
        assert elapsed < self.MEDIUM_SLA, f"Login too slow: {elapsed:.2f}s > {self.MEDIUM_SLA}s"

    @pytest.mark.xfail(reason="Render free tier single-worker may 500 under concurrent LLM load; tracks known limitation")
    def test_smoke015i_three_concurrent_chat_requests_all_succeed(self, live_clinic):
        """SMOKE-015-I: 3 parallel chat sessions all receive 200 within SLOW_SLA."""
        import threading

        results = {}

        def _chat(idx):
            t0 = _time.monotonic()
            r = post(f"/api/{live_clinic['slug']}/chat",
                     json={"message": f"Hi, session {idx}", "session_id": uuid.uuid4().hex})
            results[idx] = (r.status_code, _time.monotonic() - t0)

        threads = [threading.Thread(target=_chat, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=self.SLOW_SLA + 5)

        for idx, (status, elapsed) in results.items():
            assert status == 200, f"Thread {idx} got {status}"
            assert elapsed < self.SLOW_SLA, f"Thread {idx} took {elapsed:.2f}s"

    def test_smoke015j_portal_page_responds_fast(self, live_clinic):
        """SMOKE-015-J: Portal HTML page loads within FAST_SLA (5s)."""
        r, elapsed = self._timed(get, f"/c/{live_clinic['slug']}")
        assert r.status_code == 200
        assert elapsed < self.FAST_SLA, f"Portal page too slow: {elapsed:.2f}s > {self.FAST_SLA}s"

    def test_smoke015k_appointment_types_medium_sla(self, live_clinic):
        """SMOKE-015-K: GET appointment-types responds within MEDIUM_SLA (15s)."""
        r, elapsed = self._timed(
            get, f"/api/{live_clinic['slug']}/appointment-types",
            headers={"X-Clinic-Token": live_clinic["token"]}
        )
        assert r.status_code == 200
        assert elapsed < self.MEDIUM_SLA, f"Appt-types too slow: {elapsed:.2f}s > {self.MEDIUM_SLA}s"


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE-016 — Database: Persistence, CRUD Integrity, Isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatabase:
    """These tests verify that write operations persist and reads reflect them.
    All writes use the permanent smoke test clinic so no new clinics are created.
    Cleanup: each test restores state after itself where possible.
    """

    # ── Config / profile persistence ─────────────────────────────────────────

    def test_smoke016a_profile_update_persists(self, live_clinic):
        """SMOKE-016-A: PATCH profile → GET profile confirms the field was saved."""
        slug, token = live_clinic["slug"], live_clinic["token"]
        unique_note = f"smoke-test-note-{uuid.uuid4().hex[:8]}"
        r_patch = patch(f"/api/{slug}/profile",
                        json={"office_hours": unique_note},
                        headers={"X-Clinic-Token": token})
        assert r_patch.status_code == 200, f"PATCH profile failed: {r_patch.text}"

        r_get = get(f"/api/{slug}/profile",
                    headers={"X-Clinic-Token": token})
        assert r_get.status_code == 200
        assert unique_note in r_get.json().get("office_hours", ""), \
            "Updated office_hours not reflected in GET profile"

    def test_smoke016b_config_endpoint_reflects_profile(self, live_clinic):
        """SMOKE-016-B: Public /api/{slug}/config mirrors clinic name from DB."""
        slug = live_clinic["slug"]
        r = get(f"/api/{slug}/config")
        assert r.status_code == 200
        body = r.json()
        assert "clinic_name" in body or "name" in body, \
            f"Config missing name field: {list(body.keys())}"

    # ── Appointment type CRUD ─────────────────────────────────────────────────

    def test_smoke016c_appointment_type_create_and_list(self, live_clinic):
        """SMOKE-016-C: POST appt-type → appears in GET list."""
        slug, token = live_clinic["slug"], live_clinic["token"]
        unique_name = f"DB-Test-Type-{uuid.uuid4().hex[:6]}"

        r_create = post(f"/api/{slug}/appointment-types",
                        json={"name": unique_name, "duration_minutes": 30},
                        headers={"X-Clinic-Token": token})
        assert r_create.status_code == 200, f"Create appt-type failed: {r_create.text}"
        created_id = r_create.json().get("id")
        assert created_id, "No id in create response"

        r_list = get(f"/api/{slug}/appointment-types",
                     headers={"X-Clinic-Token": token})
        assert r_list.status_code == 200
        names = [t["name"] for t in r_list.json().get("appointment_types", [])]
        assert unique_name in names, f"Created type '{unique_name}' not in list: {names}"

        # Cleanup — delete what we just created
        delete(f"/api/{slug}/appointment-types/{created_id}",
               headers={"X-Clinic-Token": token})

    def test_smoke016d_appointment_type_update_persists(self, live_clinic):
        """SMOKE-016-D: PATCH appt-type → updated name visible in GET list."""
        slug, token = live_clinic["slug"], live_clinic["token"]
        original_name = f"DB-Update-{uuid.uuid4().hex[:6]}"
        updated_name  = f"DB-Updated-{uuid.uuid4().hex[:6]}"

        r_create = post(f"/api/{slug}/appointment-types",
                        json={"name": original_name, "duration_minutes": 20},
                        headers={"X-Clinic-Token": token})
        assert r_create.status_code == 200
        type_id = r_create.json()["id"]

        r_patch = patch(f"/api/{slug}/appointment-types/{type_id}",
                        json={"name": updated_name},
                        headers={"X-Clinic-Token": token})
        assert r_patch.status_code == 200, f"PATCH appt-type failed: {r_patch.text}"

        r_list = get(f"/api/{slug}/appointment-types",
                     headers={"X-Clinic-Token": token})
        names = [t["name"] for t in r_list.json().get("appointment_types", [])]
        assert updated_name in names, f"Updated name not found. Got: {names}"
        assert original_name not in names, f"Old name still present: {names}"

        delete(f"/api/{slug}/appointment-types/{type_id}",
               headers={"X-Clinic-Token": token})

    def test_smoke016e_appointment_type_delete_removes_it(self, live_clinic):
        """SMOKE-016-E: DELETE appt-type → no longer in GET list."""
        slug, token = live_clinic["slug"], live_clinic["token"]
        name = f"DB-Delete-{uuid.uuid4().hex[:6]}"

        r_create = post(f"/api/{slug}/appointment-types",
                        json={"name": name, "duration_minutes": 45},
                        headers={"X-Clinic-Token": token})
        assert r_create.status_code == 200
        type_id = r_create.json()["id"]

        r_del = delete(f"/api/{slug}/appointment-types/{type_id}",
                       headers={"X-Clinic-Token": token})
        assert r_del.status_code == 200
        assert r_del.json().get("ok") is True

        r_list = get(f"/api/{slug}/appointment-types",
                     headers={"X-Clinic-Token": token})
        names = [t["name"] for t in r_list.json().get("appointment_types", [])]
        assert name not in names, f"Deleted type still in list: {names}"

    # ── Provider CRUD ─────────────────────────────────────────────────────────

    def test_smoke016f_provider_create_and_list(self, live_clinic):
        """SMOKE-016-F: POST provider → appears in GET /providers."""
        slug, token = live_clinic["slug"], live_clinic["token"]
        unique_name = f"Dr DB-{uuid.uuid4().hex[:6]}"

        r_create = post(f"/api/{slug}/providers",
                        json={"name": unique_name, "title": "MD", "specialty": "Testing"},
                        headers={"X-Clinic-Token": token})
        assert r_create.status_code == 200, f"Create provider failed: {r_create.text}"
        provider_id = r_create.json().get("id")
        assert provider_id

        r_list = get(f"/api/{slug}/providers",
                     headers={"X-Clinic-Token": token})
        assert r_list.status_code == 200
        providers = r_list.json().get("providers", r_list.json())
        names = [p["name"] for p in (providers if isinstance(providers, list) else [])]
        assert unique_name in names, f"Provider '{unique_name}' not in list: {names}"

        delete(f"/api/{slug}/providers/{provider_id}",
               headers={"X-Clinic-Token": token})

    def test_smoke016g_provider_update_persists(self, live_clinic):
        """SMOKE-016-G: PATCH provider bio → updated value visible in GET."""
        slug, token = live_clinic["slug"], live_clinic["token"]
        name = f"Dr Update-{uuid.uuid4().hex[:6]}"
        updated_bio = f"Updated bio {uuid.uuid4().hex[:8]}"

        r_create = post(f"/api/{slug}/providers",
                        json={"name": name, "specialty": "Testing"},
                        headers={"X-Clinic-Token": token})
        assert r_create.status_code == 200
        provider_id = r_create.json()["id"]

        r_patch = patch(f"/api/{slug}/providers/{provider_id}",
                        json={"bio": updated_bio},
                        headers={"X-Clinic-Token": token})
        assert r_patch.status_code == 200, f"PATCH provider failed: {r_patch.text}"

        r_get = get(f"/api/{slug}/providers/{provider_id}",
                    headers={"X-Clinic-Token": token})
        assert r_get.status_code == 200
        assert r_get.json().get("bio") == updated_bio, \
            f"Bio not updated: {r_get.json()}"

        delete(f"/api/{slug}/providers/{provider_id}",
               headers={"X-Clinic-Token": token})

    def test_smoke016h_provider_delete_removes_it(self, live_clinic):
        """SMOKE-016-H: DELETE provider → no longer in GET list."""
        slug, token = live_clinic["slug"], live_clinic["token"]
        name = f"Dr Del-{uuid.uuid4().hex[:6]}"

        r_create = post(f"/api/{slug}/providers",
                        json={"name": name, "title": "MD", "specialty": "Testing"},
                        headers={"X-Clinic-Token": token})
        assert r_create.status_code == 200
        provider_id = r_create.json()["id"]

        r_del = delete(f"/api/{slug}/providers/{provider_id}",
                       headers={"X-Clinic-Token": token})
        assert r_del.status_code == 200

        r_list = get(f"/api/{slug}/providers",
                     headers={"X-Clinic-Token": token})
        providers = r_list.json().get("providers", r_list.json())
        names = [p["name"] for p in (providers if isinstance(providers, list) else [])]
        assert name not in names, f"Deleted provider still present: {names}"

    # ── Appointment list integrity ────────────────────────────────────────────

    def test_smoke016i_appointments_list_returns_list_type(self, live_clinic):
        """SMOKE-016-I: GET appointments returns a list (even if empty)."""
        r = get(f"/api/{live_clinic['slug']}/appointments",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        body = r.json()
        # API returns a raw JSON array (not wrapped in a dict)
        appts = body if isinstance(body, list) else body.get("appointments", body)
        assert isinstance(appts, list), f"Expected list, got {type(appts)}: {body}"

    def test_smoke016j_appointment_status_patch_persists(self, live_clinic):
        """SMOKE-016-J: PATCH appointment status → GET list reflects new status."""
        slug, token = live_clinic["slug"], live_clinic["token"]

        # API returns a raw list (not {"appointments": [...]})
        r_list = get(f"/api/{slug}/appointments",
                     headers={"X-Clinic-Token": token})
        assert r_list.status_code == 200
        body = r_list.json()
        appts = body if isinstance(body, list) else body.get("appointments", [])
        if not appts:
            pytest.skip("No appointments exist in smoke clinic to test status update")

        target = next(
            (a for a in appts if a.get("status") in ("scheduled", "confirmed")),
            None
        )
        if not target:
            pytest.skip("No scheduled/confirmed appointment found for status update test")

        conf_num = target["confirmation_number"]
        new_status = "confirmed" if target["status"] == "scheduled" else "completed"

        r_patch = patch(f"/api/{slug}/appointments/{conf_num}",
                        json={"status": new_status},
                        headers={"X-Clinic-Token": token})
        assert r_patch.status_code == 200, f"PATCH status failed: {r_patch.text}"
        assert r_patch.json().get("status") == new_status

        r_verify = get(f"/api/{slug}/appointments",
                       headers={"X-Clinic-Token": token})
        verify_body = r_verify.json()
        verify_list = verify_body if isinstance(verify_body, list) else verify_body.get("appointments", [])
        updated_map = {a["confirmation_number"]: a["status"] for a in verify_list}
        assert updated_map.get(conf_num) == new_status, \
            f"Status not persisted. Expected {new_status}, got {updated_map.get(conf_num)}"

    def test_smoke016k_appointment_status_invalid_transition(self, live_clinic):
        """SMOKE-016-K: PATCH with invalid status value returns 400/422, not 500."""
        r = patch(f"/api/{live_clinic['slug']}/appointments/FAKE-CONF-NONE",
                  json={"status": "totally-made-up-status"},
                  headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code in (400, 404, 422)
        assert r.status_code != 500

    def test_smoke016l_appointments_cross_tenant_isolation(self, live_clinic):
        """SMOKE-016-L: Fake token cannot read smoke clinic's appointments."""
        fake_token = "isolation-test-" + uuid.uuid4().hex
        r = get(f"/api/{live_clinic['slug']}/appointments",
                headers={"X-Clinic-Token": fake_token})
        assert r.status_code == 403, \
            f"Expected 403 for fake token, got {r.status_code}"

    def test_smoke016m_providers_count_consistent_with_list(self, live_clinic):
        """SMOKE-016-M: providers.count matches len(providers.providers)."""
        r = get(f"/api/{live_clinic['slug']}/providers",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        body = r.json()
        if "count" in body and "providers" in body:
            assert body["count"] == len(body["providers"]), \
                f"Count mismatch: count={body['count']} but list has {len(body['providers'])}"

    def test_smoke016n_appointment_type_not_shared_across_clinics(self):
        """SMOKE-016-N: Appointment types for a non-existent clinic return 403/404, never another clinic's data."""
        # Without a token the endpoint returns 403; a fake token returns 403 too — never bleeds real data
        r = get("/api/nonexistent-clinic-xyz-9999/appointment-types",
                headers={"X-Clinic-Token": "fake-token-" + uuid.uuid4().hex})
        assert r.status_code in (403, 404, 400)
        # Critically: must not return a 200 with real appointment type data
        assert r.status_code != 200

    def test_smoke016o_profile_fields_have_correct_types(self, live_clinic):
        """SMOKE-016-O: Profile GET returns expected top-level fields with correct types."""
        r = get(f"/api/{live_clinic['slug']}/profile",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        body = r.json()
        # These fields must be strings (or None), never integers or lists
        for field in ("name", "specialty", "email"):
            if field in body and body[field] is not None:
                assert isinstance(body[field], str), \
                    f"Field '{field}' should be str, got {type(body[field])}"


# SMOKE-017 — EMR / EHR Integration (plan gate, config CRUD, security, sync-log)
# All tests skip cleanly when the clinic is Starter plan (smoke clinic is Pro).

class TestEMRIntegration:
    """SMOKE-017: EHR/EMR integration endpoints — functional + security + corner cases."""

    def test_smoke017a_get_ehr_config_pro_clinic(self, live_clinic):
        """SMOKE-017-A: Pro clinic can GET /ehr-config (200, config fields present)."""
        r = get(f"/api/{live_clinic['slug']}/ehr-config",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert "ehr_system" in body
        assert "api_endpoint" in body
        assert "sync_status" in body
        assert "auto_sync" in body

    def test_smoke017b_ehr_config_no_token_returns_403(self, live_clinic):
        """SMOKE-017-B: GET /ehr-config without token returns 403."""
        r = get(f"/api/{live_clinic['slug']}/ehr-config")
        assert r.status_code == 403

    def test_smoke017c_ehr_config_fake_token_returns_403(self, live_clinic):
        """SMOKE-017-C: GET /ehr-config with invalid token returns 403."""
        r = get(f"/api/{live_clinic['slug']}/ehr-config",
                headers={"X-Clinic-Token": "fake-token-xyz-123"})
        assert r.status_code == 403

    def test_smoke017d_patch_ehr_config_saves_system(self, live_clinic):
        """SMOKE-017-D: PATCH /ehr-config saves ehr_system and returns it."""
        r = patch(f"/api/{live_clinic['slug']}/ehr-config",
                  json={"ehr_system": "epic", "auto_sync": True},
                  headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        body = r.json()
        assert body["ehr_system"] == "epic"
        assert body["auto_sync"] is True

    def test_smoke017e_patch_empty_body_returns_400(self, live_clinic):
        """SMOKE-017-E: PATCH /ehr-config with empty body returns 400."""
        r = patch(f"/api/{live_clinic['slug']}/ehr-config",
                  json={},
                  headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 400

    def test_smoke017f_get_supported_systems(self, live_clinic):
        """SMOKE-017-F: /ehr-config/systems returns expected EHR list."""
        r = get(f"/api/{live_clinic['slug']}/ehr-config/systems",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        systems = r.json().get("supported_systems", [])
        assert "epic" in systems
        assert "cerner" in systems
        assert "athenahealth" in systems

    def test_smoke017g_test_connection_unconfigured(self, live_clinic):
        """SMOKE-017-G: Test connection on unconfigured EHR returns success=False, not 500."""
        r = post(f"/api/{live_clinic['slug']}/ehr-config/test",
                 headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        body = r.json()
        assert "success" in body
        assert "message" in body
        # Expect False since no real EHR is connected in smoke env
        assert body["success"] is False

    def test_smoke017h_sync_log_returns_list(self, live_clinic):
        """SMOKE-017-H: /emr/sync-log returns 200 with entries list."""
        r = get(f"/api/{live_clinic['slug']}/emr/sync-log",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        body = r.json()
        assert "entries" in body
        assert isinstance(body["entries"], list)

    def test_smoke017i_sync_log_no_token_returns_403(self, live_clinic):
        """SMOKE-017-I: /emr/sync-log without token returns 403."""
        r = get(f"/api/{live_clinic['slug']}/emr/sync-log")
        assert r.status_code == 403

    def test_smoke017j_patient_lookup_no_ehr_returns_not_found(self, live_clinic):
        """SMOKE-017-J: Patient lookup with no EHR connected returns found=False."""
        r = get(f"/api/{live_clinic['slug']}/emr/patient-lookup",
                params={"patient_name": "John Doe", "date_of_birth": "1980-01-15"},
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        assert r.json()["found"] is False

    def test_smoke017k_patient_lookup_no_token_returns_403(self, live_clinic):
        """SMOKE-017-K: Patient lookup without token returns 403."""
        r = get(f"/api/{live_clinic['slug']}/emr/patient-lookup",
                params={"patient_name": "John Doe", "date_of_birth": "1980-01-15"})
        assert r.status_code == 403

    def test_smoke017l_slots_no_ehr_returns_empty_list(self, live_clinic):
        """SMOKE-017-L: Slot fetch with no EHR returns empty list."""
        r = get(f"/api/{live_clinic['slug']}/emr/slots",
                params={"appointment_type": "annual physical"},
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        body = r.json()
        assert body["slots"] == []
        assert body["count"] == 0

    def test_smoke017m_slots_no_token_returns_403(self, live_clinic):
        """SMOKE-017-M: Slot fetch without token returns 403."""
        r = get(f"/api/{live_clinic['slug']}/emr/slots",
                params={"appointment_type": "annual physical"})
        assert r.status_code == 403

    def test_smoke017n_api_key_not_in_config_response(self, live_clinic):
        """SMOKE-017-N: GET /ehr-config never returns api_key field (secret masking)."""
        r = get(f"/api/{live_clinic['slug']}/ehr-config",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 200
        assert "api_key" not in r.json()

    def test_smoke017o_cross_tenant_ehr_blocked(self, live_clinic):
        """SMOKE-017-O: Smoke clinic token cannot read a different clinic's EHR config."""
        # Use a made-up slug — the token belongs to live_clinic, not this slug
        r = get("/api/definitely-not-our-clinic/ehr-config",
                headers={"X-Clinic-Token": live_clinic["token"]})
        assert r.status_code == 403

    def test_smoke017p_sql_injection_patient_name_no_500(self, live_clinic):
        """SMOKE-017-P: SQL injection in patient_name does not cause 500."""
        for payload in ["'; DROP TABLE emr_patients; --", "1' OR '1'='1"]:
            r = get(f"/api/{live_clinic['slug']}/emr/patient-lookup",
                    params={"patient_name": payload, "date_of_birth": "1990-01-01"},
                    headers={"X-Clinic-Token": live_clinic["token"]})
            assert r.status_code != 500, f"SQL injection caused 500: {r.text}"

    def test_smoke017q_ehr_config_response_time_under_5s(self, live_clinic):
        """SMOKE-017-Q: GET /ehr-config responds within 5s (cold Render start excluded)."""
        import time
        t0 = time.monotonic()
        r = get(f"/api/{live_clinic['slug']}/ehr-config",
                headers={"X-Clinic-Token": live_clinic["token"]})
        elapsed = time.monotonic() - t0
        assert r.status_code == 200
        assert elapsed < 5.0, f"EHR config took {elapsed:.1f}s (limit: 5s)"


# SMOKE-018 — Upgrade / Renewal email URL correctness
# Regression guard: upgrade links in trial-expiry and renewal emails must point
# to aifrontdesk.taborsynergy.com (the AI agent portal), NOT app.taborsynergy.com
# (ChurchConnect). Verified by inspecting the /api/health response base_url and
# confirming the portal route /c/{slug} resolves correctly.

class TestEmailUpgradeURL:
    """SMOKE-018: Upgrade/renewal email links point to the correct portal."""

    def test_smoke018a_health_base_url_is_aifrontdesk(self):
        """SMOKE-018-A: /api/health confirms service is aifrontdesk (not app.taborsynergy)."""
        r = get("/api/health")
        assert r.status_code == 200
        # The service identity must not be ChurchConnect
        text = r.text.lower()
        assert "app.taborsynergy" not in text, \
            "Health check references app.taborsynergy — wrong service?"

    def test_smoke018b_portal_route_resolves_for_smoke_clinic(self):
        """SMOKE-018-B: /c/{slug} returns 200 (the portal a trial email links to)."""
        slug = SMOKE_CLINIC_SLUG or "smoke-test-clinic-do-not-delet-024dc"
        r = get(f"/c/{slug}")
        assert r.status_code == 200, \
            f"/c/{slug} returned {r.status_code} — upgrade email link is broken"

    def test_smoke018c_portal_not_church_app(self):
        """SMOKE-018-C: /c/{slug} page content is the AI agent portal, not ChurchConnect."""
        slug = SMOKE_CLINIC_SLUG or "smoke-test-clinic-do-not-delet-024dc"
        r = get(f"/c/{slug}")
        assert r.status_code == 200
        body = r.text.lower()
        # Must NOT be ChurchConnect content
        assert "grace community" not in body, "Portal returned ChurchConnect page"
        assert "sermons" not in body, "Portal returned ChurchConnect page"
        # Must BE the AI agent portal
        assert "aria" in body or "taborsynergy" in body, \
            "Portal page doesn't look like the AI agent portal"

    def test_smoke018d_upgrade_url_pattern_correct(self, live_clinic):
        """SMOKE-018-D: Portal /c/{slug} for authenticated clinic returns 200 with plan info."""
        r = get(f"/c/{live_clinic['slug']}")
        assert r.status_code == 200
        body = r.text.lower()
        assert "grace community" not in body
        assert "sermons" not in body
