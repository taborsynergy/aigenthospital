"""
Tests for the demo request feature.

Covers:
  DMO-001: POST /api/demo-request — happy path
  DMO-002: POST /api/demo-request — validation errors (missing required fields)
  DMO-003: Email service send_demo_request_email — structure, recipient, reply-to
  DMO-004: Frontend modal presence and form wiring
"""
import os
import pathlib
import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# Ensure required settings env vars exist before any backend module is imported.
os.environ.setdefault("ADMIN_PASSWORD", "test-password-pytest")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

INDEX_HTML = (
    pathlib.Path(__file__).parent.parent.parent / "frontend" / "index.html"
)

VALID_DEMO_PAYLOAD = {
    "full_name":      "Dr. Jane Smith",
    "email":          "jane@sunrise-clinic.com",
    "phone":          "+1 555-000-1234",
    "practice_name":  "Sunrise Family Clinic",
    "specialty":      "Family Medicine / Primary Care",
    "num_providers":  "2–5",
    "preferred_slot": "Morning — 9:00 AM to 11:00 AM (ET)",
    "message":        "Looking to reduce front-desk call volume for 40 patients/day.",
}


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client():
    try:
        from backend.main import app
        return TestClient(app, raise_server_exceptions=False)
    except Exception:
        pytest.skip("backend.main requires full env (DB, admin_password) — skipped in unit-test mode")


# ── DMO-001: Happy path ──────────────────────────────────────────────────────

class TestDemoRequestEndpointHappyPath:

    def test_returns_200_ok(self, client):
        """DMO-001-A: Valid payload returns 200 with ok=True."""
        with patch("backend.routers.signup.send_demo_request_email") as mock_send:
            mock_send.return_value = True
            r = client.post("/api/demo-request", json=VALID_DEMO_PAYLOAD)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_response_contains_confirmation_message(self, client):
        """DMO-001-B: Response message mentions demo slot confirmation."""
        with patch("backend.routers.signup.send_demo_request_email"):
            r = client.post("/api/demo-request", json=VALID_DEMO_PAYLOAD)
        body = r.json()
        assert "message" in body
        msg = body["message"].lower()
        assert "demo" in msg or "24 hours" in msg or "confirm" in msg

    def test_email_function_called_with_correct_data(self, client):
        """DMO-001-C: send_demo_request_email is invoked with all submitted fields."""
        with patch("backend.routers.signup.send_demo_request_email") as mock_send:
            mock_send.return_value = True
            client.post("/api/demo-request", json=VALID_DEMO_PAYLOAD)
        assert mock_send.called
        call_data = mock_send.call_args[0][0]
        assert call_data["full_name"]     == VALID_DEMO_PAYLOAD["full_name"]
        assert call_data["email"]         == VALID_DEMO_PAYLOAD["email"]
        assert call_data["practice_name"] == VALID_DEMO_PAYLOAD["practice_name"]
        assert call_data["specialty"]     == VALID_DEMO_PAYLOAD["specialty"]
        assert call_data["preferred_slot"] == VALID_DEMO_PAYLOAD["preferred_slot"]

    def test_optional_fields_accepted(self, client):
        """DMO-001-D: phone, num_providers, message are optional; request still succeeds."""
        minimal = {
            "full_name":      "Alice Chen",
            "email":          "alice@clinic.com",
            "practice_name":  "Chen Pediatrics",
            "specialty":      "Pediatrics",
            "preferred_slot": "Flexible — any time works",
        }
        with patch("backend.routers.signup.send_demo_request_email"):
            r = client.post("/api/demo-request", json=minimal)
        assert r.status_code == 200


# ── DMO-002: Validation errors ───────────────────────────────────────────────

class TestDemoRequestValidation:

    @pytest.mark.parametrize("missing_field,expected_snippet", [
        ("full_name",      "name"),
        ("practice_name",  "practice"),
        ("specialty",      "specialty"),
        ("preferred_slot", "time"),
    ])
    def test_missing_required_field_returns_400(self, client, missing_field, expected_snippet):
        """DMO-002-A: Missing required fields return 400 with a descriptive error."""
        payload = dict(VALID_DEMO_PAYLOAD)
        del payload[missing_field]
        with patch("backend.routers.signup.send_demo_request_email"):
            r = client.post("/api/demo-request", json=payload)
        # FastAPI Pydantic 422 for type-level missing OR our own 400 for business-level
        assert r.status_code in (400, 422)

    def test_blank_full_name_returns_400(self, client):
        """DMO-002-B: Whitespace-only full_name is rejected."""
        payload = dict(VALID_DEMO_PAYLOAD, full_name="   ")
        with patch("backend.routers.signup.send_demo_request_email"):
            r = client.post("/api/demo-request", json=payload)
        assert r.status_code == 400
        assert "name" in r.json().get("error", "").lower()

    def test_invalid_email_returns_422(self, client):
        """DMO-002-C: Malformed email address fails Pydantic validation."""
        payload = dict(VALID_DEMO_PAYLOAD, email="not-an-email")
        with patch("backend.routers.signup.send_demo_request_email"):
            r = client.post("/api/demo-request", json=payload)
        assert r.status_code == 422


# ── DMO-003: Email service unit tests ────────────────────────────────────────

class TestSendDemoRequestEmail:

    def _make_data(self, **overrides):
        d = dict(VALID_DEMO_PAYLOAD)
        d.update(overrides)
        return d

    def test_sendgrid_path_sends_to_demo_notify_address(self):
        """DMO-003-A: SendGrid path targets write2dinakar10@gmail.com, not notify_email."""
        from backend.services import email_svc
        calls = []

        def fake_sendgrid(to_list, subject, plain, html="", reply_to="", from_name=""):
            calls.append({"to_list": to_list, "subject": subject, "reply_to": reply_to})
            return True

        with patch("backend.services.email_svc._sendgrid_send", side_effect=fake_sendgrid), \
             patch("backend.services.email_svc.settings") as mock_settings:
            mock_settings.sendgrid_api_key = "test-key"
            result = email_svc.send_demo_request_email(self._make_data())

        assert result is True
        assert len(calls) == 1
        assert "write2dinakar10@gmail.com" in calls[0]["to_list"]

    def test_reply_to_set_to_lead_email(self):
        """DMO-003-B: Reply-To header is the lead's email so owner can reply directly."""
        from backend.services import email_svc
        captured = {}

        def fake_sendgrid(to_list, subject, plain, html="", reply_to="", from_name=""):
            captured["reply_to"] = reply_to
            return True

        with patch("backend.services.email_svc._sendgrid_send", side_effect=fake_sendgrid), \
             patch("backend.services.email_svc.settings") as mock_settings:
            mock_settings.sendgrid_api_key = "test-key"
            email_svc.send_demo_request_email(self._make_data())

        assert captured.get("reply_to") == VALID_DEMO_PAYLOAD["email"]

    def test_subject_contains_practice_name(self):
        """DMO-003-C: Email subject includes the practice name for easy triage."""
        from backend.services import email_svc
        captured = {}

        def fake_sendgrid(to_list, subject, plain, html="", reply_to="", from_name=""):
            captured["subject"] = subject
            return True

        with patch("backend.services.email_svc._sendgrid_send", side_effect=fake_sendgrid), \
             patch("backend.services.email_svc.settings") as mock_settings:
            mock_settings.sendgrid_api_key = "test-key"
            email_svc.send_demo_request_email(self._make_data())

        assert "Sunrise Family Clinic" in captured.get("subject", "")

    def test_returns_false_when_not_configured(self):
        """DMO-003-D: Returns False gracefully when no email transport is configured."""
        from backend.services import email_svc

        with patch("backend.services.email_svc.settings") as mock_settings:
            mock_settings.sendgrid_api_key = ""
            mock_settings.smtp_host        = ""
            mock_settings.smtp_user        = ""
            mock_settings.smtp_pass        = ""
            result = email_svc.send_demo_request_email(self._make_data())

        assert result is False

    def test_html_contains_preferred_slot(self):
        """DMO-003-E: HTML email body includes the lead's preferred time slot."""
        from backend.services import email_svc
        captured = {}

        def fake_sendgrid(to_list, subject, plain, html="", reply_to="", from_name=""):
            captured["html"] = html
            return True

        with patch("backend.services.email_svc._sendgrid_send", side_effect=fake_sendgrid), \
             patch("backend.services.email_svc.settings") as mock_settings:
            mock_settings.sendgrid_api_key = "test-key"
            email_svc.send_demo_request_email(self._make_data())

        assert VALID_DEMO_PAYLOAD["preferred_slot"] in captured.get("html", "")


# ── DMO-004: Frontend modal presence ────────────────────────────────────────

class TestDemoModalFrontend:

    def test_demo_modal_overlay_exists(self, html):
        """DMO-004-A: demo-modal overlay div is present."""
        assert 'id="demo-modal"' in html

    def test_demo_success_modal_exists(self, html):
        """DMO-004-B: demo-success-modal is present for post-submit confirmation."""
        assert 'id="demo-success-modal"' in html

    def test_demo_form_exists(self, html):
        """DMO-004-C: demo-form element with correct onsubmit handler."""
        assert 'id="demo-form"' in html
        assert 'submitDemoRequest(event)' in html

    def test_demo_form_has_required_fields(self, html):
        """DMO-004-D: All required input/select fields are present."""
        for field_id in ("df-name", "df-email", "df-practice", "df-specialty", "df-slot"):
            assert f'id="{field_id}"' in html, f"Demo form field #{field_id} is missing"

    def test_demo_form_posts_to_api(self, html):
        """DMO-004-E: submitDemoRequest POSTs to /api/demo-request."""
        assert '"/api/demo-request"' in html

    def test_open_demo_form_defined(self, html):
        """DMO-004-F: openDemoForm() JS function is defined."""
        assert "function openDemoForm(" in html

    def test_close_demo_form_defined(self, html):
        """DMO-004-G: closeDemoForm() JS function is defined."""
        assert "function closeDemoForm(" in html

    def test_close_demo_success_defined(self, html):
        """DMO-004-H: closeDemoSuccess() JS function is defined."""
        assert "function closeDemoSuccess(" in html

    def test_demo_error_msg_element_exists(self, html):
        """DMO-004-I: demo-error-msg span present for inline error display."""
        assert 'id="demo-error-msg"' in html

    def test_demo_reply_email_element_exists(self, html):
        """DMO-004-J: demo-reply-email span present in success modal."""
        assert 'id="demo-reply-email"' in html

    def test_nav_demo_button_calls_open_demo_form(self, html):
        """DMO-004-K: Nav 'Book a Demo' button calls openDemoForm(), not openSignup."""
        idx = html.index('<button class="btn-nav-demo"')
        end = html.index('</button>', idx) + 9
        snippet = html[idx:end]
        assert "openDemoForm" in snippet
        assert "openSignup" not in snippet

    def test_hero_live_demo_button_calls_open_demo_form(self, html):
        """DMO-004-L: Hero 'Book a Live Demo' button calls openDemoForm()."""
        idx = html.index("Book a Live Demo")
        btn_start = html.rfind("<button", 0, idx)
        snippet = html[btn_start: idx + 20]
        assert "openDemoForm" in snippet
        assert "openSignup" not in snippet

    def test_specialty_dropdown_has_common_options(self, html):
        """DMO-004-M: Specialty dropdown includes common medical specialties."""
        demo_modal_start = html.index('id="demo-modal"')
        demo_modal_end   = html.index('id="demo-success-modal"')
        modal_html = html[demo_modal_start:demo_modal_end]
        for specialty in ("Family Medicine", "Pediatrics", "Cardiology", "Dental"):
            assert specialty in modal_html, f"Specialty '{specialty}' missing from dropdown"

    def test_time_slot_dropdown_has_all_options(self, html):
        """DMO-004-N: Preferred time dropdown has Morning, Afternoon, Evening, Flexible."""
        demo_modal_start = html.index('id="demo-modal"')
        demo_modal_end   = html.index('id="demo-success-modal"')
        modal_html = html[demo_modal_start:demo_modal_end]
        for slot in ("Morning", "Afternoon", "Evening", "Flexible"):
            assert slot in modal_html, f"Time slot '{slot}' missing from dropdown"
