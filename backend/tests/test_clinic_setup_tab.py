"""
REG-008 — Clinic Setup Tab: PATCH /api/{slug}/profile (portal self-edit).

The "Clinic Setup" tab in the portal lets clinics update all practice info:
phone, address, specialty, providers, insurance, hours, cancellation policy,
escalation contact, agent name, etc. Whatever is set here MUST be what Aria
uses when answering patient questions.

Root cause of the original bug (REG-008a): PATCH /api/{slug}/profile did NOT
call invalidate_prompt(clinic.id), so Aria kept using the stale system prompt
(with the old phone number) until the server restarted.

Positive tests:
  - Each editable field saves and is visible on GET /profile
  - After phone update, system prompt contains the new number
  - After each field update, prompt cache is invalidated (Aria sees new value)
  - All fields can be updated in a single PATCH
  - Partial PATCH preserves untouched fields
  - Notification preferences (booleans) can be toggled

Negative tests:
  - No token → 403
  - Wrong token (garbage) → 403
  - Cross-clinic token → 403 (tenant isolation)
  - Empty body → 400
  - agent_name on Starter plan → 403
  - SQL injection in field values → sanitized, not executed
  - Extremely long field values → rejected or truncated safely
"""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_clinic_setup.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.routers.clinic_auth import hash_password

_ctr = 0


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


def _signup(client) -> dict:
    """Create a clinic via /api/signup and return {slug, token}."""
    global _ctr
    _ctr += 1
    r = client.post("/api/signup", json={
        "practice_name": f"Setup Test Clinic {_ctr}",
        "contact_email": f"setup{_ctr}@test.com",
        "password":      "SetupTest123!",
        "specialty":     "Family Medicine",
        "plan":          "professional",
    })
    assert r.status_code == 200, f"Signup failed: {r.text}"
    return r.json()


def _headers(token: str) -> dict:
    return {"X-Clinic-Token": token}


# ── POSITIVE: Individual field updates ───────────────────────────────────────

class TestSetupTabFieldsSave:
    """Every field in the Clinic Setup tab must persist and be returned on GET /profile."""

    def test_phone_number_saves(self, client):
        """REG-008: updating phone in Setup tab must persist to DB and be returned by GET /profile."""
        d = _signup(client)
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={"phone": "800-555-0100"},
                         headers=_headers(d["token"]))
        assert r.status_code == 200
        assert "phone" in r.json()["updated_fields"]

        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["phone"] == "800-555-0100", \
            "Phone update not persisted — patient will hear wrong number"

    def test_address_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"address": "123 Office Park Dr", "city_state": "Atlanta, GA"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["address"] == "123 Office Park Dr"
        assert profile["city_state"] == "Atlanta, GA"

    def test_specialty_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"specialty": "Pediatrics"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["specialty"] == "Pediatrics"

    def test_office_hours_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"office_hours": "Mon-Fri 8am-5pm, Sat 9am-1pm"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["office_hours"] == "Mon-Fri 8am-5pm, Sat 9am-1pm"

    def test_providers_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"providers": "Dr. Smith MD, Dr. Jones DO"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["providers"] == "Dr. Smith MD, Dr. Jones DO"

    def test_insurance_accepted_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"insurance_accepted": "Aetna, BCBS, Tricare, Medicare"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["insurance_accepted"] == "Aetna, BCBS, Tricare, Medicare"

    def test_services_offered_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"services_offered": "Flu shots, Annual physicals, Lab work"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["services_offered"] == "Flu shots, Annual physicals, Lab work"

    def test_after_hours_protocol_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"after_hours_protocol": "Call 800-555-0911 for urgent issues"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert "800-555-0911" in profile["after_hours_protocol"]

    def test_cancellation_policy_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"cancellation_policy": "24-hour notice required, $50 late-cancel fee"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert "$50" in profile["cancellation_policy"]

    def test_escalation_contact_saves(self, client):
        """Escalation contact is used when Aria hands off to a human."""
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"escalation_contact": "Office Manager: 800-555-0199"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert "800-555-0199" in profile["escalation_contact"]

    def test_hipaa_verify_method_saves(self, client):
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"hipaa_verify_method": "Full name + DOB + last 4 SSN"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert "DOB" in profile["hipaa_verify_method"]

    def test_notification_prefs_toggle(self, client):
        """72h/24h reminders can be toggled via PATCH."""
        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"reminder_72h_enabled": False, "reminder_24h_enabled": True},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["reminder_72h_enabled"] is False
        assert profile["reminder_24h_enabled"] is True

    def test_all_fields_in_single_patch(self, client):
        """All Setup tab fields can be sent in one PATCH and all are saved."""
        d = _signup(client)
        payload = {
            "phone":               "800-TEST-001",
            "address":             "99 Clinic Blvd",
            "city_state":          "Houston, TX",
            "specialty":           "Cardiology",
            "office_hours":        "Mon-Sat 7am-7pm",
            "providers":           "Dr. Heart MD",
            "services_offered":    "EKG, Echo, Stress Test",
            "insurance_accepted":  "Medicare, Medicaid, Aetna",
            "cancellation_policy": "48h notice required",
            "after_hours_protocol":"Call 800-TEST-911 for chest pain",
            "escalation_contact":  "Charge Nurse: 800-TEST-ICU",
            "hipaa_verify_method": "Name + DOB + last 4 SSN",
            "timezone":            "US/Central",
        }
        r = client.patch(f"/api/{d['slug']}/profile",
                         json=payload, headers=_headers(d["token"]))
        assert r.status_code == 200
        updated = set(r.json()["updated_fields"])
        for k in payload:
            assert k in updated, f"Field '{k}' missing from updated_fields"

        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["phone"] == "800-TEST-001"
        assert profile["specialty"] == "Cardiology"
        assert profile["city_state"] == "Houston, TX"
        assert profile["timezone"] == "US/Central"

    def test_partial_patch_preserves_untouched_fields(self, client):
        """Updating one field must not clear other fields."""
        d = _signup(client)
        # Set baseline values
        client.patch(f"/api/{d['slug']}/profile",
                     json={"phone": "111-111-1111", "address": "1 Keep St"},
                     headers=_headers(d["token"]))
        # Now update only phone
        client.patch(f"/api/{d['slug']}/profile",
                     json={"phone": "222-222-2222"},
                     headers=_headers(d["token"]))
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["phone"] == "222-222-2222"     # updated
        assert profile["address"] == "1 Keep St"       # preserved


# ── POSITIVE: System prompt reflects Setup tab ────────────────────────────────

class TestSetupTabReflectsInSystemPrompt:
    """Whatever is saved in the Setup tab MUST appear in Aria's system prompt.
    This is the key contract: patient questions get answered using clinic data.
    """

    def test_phone_update_invalidates_prompt_cache(self, client):
        """REG-008a: after updating phone, build_system_prompt returns the new number.

        Root cause of the bug: update_profile didn't call invalidate_prompt(),
        so the stale phone persisted in _prompts[clinic.id] until server restart.
        """
        from backend.agent.prompts import build_system_prompt
        from backend.agent.aria import invalidate_prompt, _prompts
        from backend.db.database import SessionLocal
        from backend.db.crud import get_clinic

        d = _signup(client)
        db = SessionLocal()
        try:
            clinic = get_clinic(db, d["slug"])
            clinic._db = db

            # Set initial phone and warm the cache
            client.patch(f"/api/{d['slug']}/profile",
                         json={"phone": "OLD-555-0000"},
                         headers=_headers(d["token"]))
            db.refresh(clinic)
            old_prompt = build_system_prompt(clinic, db=db)
            assert "OLD-555-0000" in old_prompt

            # Update phone via PATCH (this must call invalidate_prompt internally)
            r = client.patch(f"/api/{d['slug']}/profile",
                             json={"phone": "NEW-555-9999"},
                             headers=_headers(d["token"]))
            assert r.status_code == 200

            # Cache must be busted — building prompt again must use new value
            db.refresh(clinic)
            new_prompt = build_system_prompt(clinic, db=db)
            assert "NEW-555-9999" in new_prompt, \
                "Phone update not reflected in system prompt — Aria will tell patients the wrong number"
            assert "OLD-555-0000" not in new_prompt
        finally:
            db.close()

    def test_insurance_update_appears_in_system_prompt(self, client):
        """Insurance field from Setup tab must appear in system prompt so Aria answers correctly."""
        from backend.agent.prompts import build_system_prompt
        from backend.db.database import SessionLocal
        from backend.db.crud import get_clinic

        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"insurance_accepted": "Tricare, CHAMPVA"},
                     headers=_headers(d["token"]))

        db = SessionLocal()
        try:
            clinic = get_clinic(db, d["slug"])
            prompt = build_system_prompt(clinic, db=db)
            assert "Tricare" in prompt, \
                "Insurance not in system prompt — Aria can't tell patients Tricare is accepted"
        finally:
            db.close()

    def test_providers_update_appears_in_system_prompt(self, client):
        """Provider names from Setup tab must appear in system prompt."""
        from backend.agent.prompts import build_system_prompt
        from backend.db.database import SessionLocal
        from backend.db.crud import get_clinic

        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"providers": "Dr. Taylor MD, Dr. Nguyen DO"},
                     headers=_headers(d["token"]))

        db = SessionLocal()
        try:
            clinic = get_clinic(db, d["slug"])
            prompt = build_system_prompt(clinic, db=db)
            assert "Dr. Taylor" in prompt
        finally:
            db.close()

    def test_escalation_contact_in_prompt(self, client):
        """Escalation contact from Setup tab must be in prompt so Aria routes emergencies correctly."""
        from backend.agent.prompts import build_system_prompt
        from backend.db.database import SessionLocal
        from backend.db.crud import get_clinic

        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"escalation_contact": "Dr. Head: 800-HEAD-123"},
                     headers=_headers(d["token"]))

        db = SessionLocal()
        try:
            clinic = get_clinic(db, d["slug"])
            prompt = build_system_prompt(clinic, db=db)
            assert "800-HEAD-123" in prompt, \
                "Escalation contact missing from prompt — emergency hand-off won't have the number"
        finally:
            db.close()

    def test_after_hours_in_prompt(self, client):
        """After-hours protocol from Setup tab must appear in prompt."""
        from backend.agent.prompts import build_system_prompt
        from backend.db.database import SessionLocal
        from backend.db.crud import get_clinic

        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"after_hours_protocol": "Answering service 800-AFTER-HRS"},
                     headers=_headers(d["token"]))

        db = SessionLocal()
        try:
            clinic = get_clinic(db, d["slug"])
            prompt = build_system_prompt(clinic, db=db)
            assert "800-AFTER-HRS" in prompt
        finally:
            db.close()

    def test_office_hours_in_prompt(self, client):
        """Office hours from Setup tab must appear in prompt so Aria directs patients correctly."""
        from backend.agent.prompts import build_system_prompt
        from backend.db.database import SessionLocal
        from backend.db.crud import get_clinic

        d = _signup(client)
        client.patch(f"/api/{d['slug']}/profile",
                     json={"office_hours": "Mon-Thu 8am-6pm, Fri 8am-3pm"},
                     headers=_headers(d["token"]))

        db = SessionLocal()
        try:
            clinic = get_clinic(db, d["slug"])
            prompt = build_system_prompt(clinic, db=db)
            assert "Mon-Thu 8am-6pm" in prompt
        finally:
            db.close()


# ── NEGATIVE: Auth and authorization ─────────────────────────────────────────

class TestSetupTabAuthErrors:
    """Setup tab updates must be blocked for unauthenticated/unauthorized callers."""

    def test_no_token_returns_403(self, client):
        """No X-Clinic-Token header → 403."""
        d = _signup(client)
        r = client.patch(f"/api/{d['slug']}/profile", json={"phone": "800-555-1234"})
        assert r.status_code == 403

    def test_garbage_token_returns_403(self, client):
        """Invalid/random token → 403."""
        d = _signup(client)
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={"phone": "800-555-1234"},
                         headers={"X-Clinic-Token": "not-a-valid-token-xyz"})
        assert r.status_code == 403

    def test_expired_token_returns_403(self, client):
        """Using a token string that doesn't match any active clinic → 403."""
        d = _signup(client)
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={"phone": "800-555-1234"},
                         headers={"X-Clinic-Token": "00000000-0000-0000-0000-000000000000"})
        assert r.status_code == 403

    def test_cross_clinic_token_blocked(self, client):
        """Clinic A's token cannot update Clinic B's profile (tenant isolation)."""
        a = _signup(client)
        b = _signup(client)

        r = client.patch(f"/api/{b['slug']}/profile",
                         json={"phone": "800-000-9999"},
                         headers=_headers(a["token"]))
        assert r.status_code == 403, "Cross-clinic profile update must be blocked"

        # Confirm B's phone was NOT changed
        profile = client.get(f"/api/{b['slug']}/profile",
                             headers=_headers(b["token"])).json()
        assert profile.get("phone") != "800-000-9999"


# ── NEGATIVE: Input validation ────────────────────────────────────────────────

class TestSetupTabInputValidation:
    """Invalid or malicious inputs must be rejected safely."""

    def test_empty_body_returns_400(self, client):
        """PATCH with no fields → 400, not 500."""
        d = _signup(client)
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={},
                         headers=_headers(d["token"]))
        assert r.status_code == 400
        assert "error" in r.json()

    def test_agent_name_blocked_on_starter_plan(self, client):
        """agent_name update is a Growth+ feature — blocked on Starter plan."""
        global _ctr; _ctr += 1
        # Create a Starter clinic
        r = client.post("/api/signup", json={
            "practice_name": f"Starter Clinic {_ctr}",
            "contact_email": f"starter{_ctr}@test.com",
            "password":      "Starter123!",
            "specialty":     "Family Medicine",
            "plan":          "starter",
        })
        assert r.status_code == 200
        d = r.json()

        # Attempt to rename the AI agent — should be plan-gated
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={"agent_name": "Skynet"},
                         headers=_headers(d["token"]))
        assert r.status_code == 403, \
            "Starter plan should not be able to rename the AI agent"
        assert "upgrade" in r.json().get("error", "").lower() or \
               "Growth" in r.json().get("error", "")

    def test_agent_name_allowed_on_professional_plan(self, client):
        """agent_name can be customized on Professional plan."""
        d = _signup(client)  # professional plan
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={"agent_name": "MedBot"},
                         headers=_headers(d["token"]))
        assert r.status_code == 200
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        assert profile["agent_name"] == "MedBot"

    def test_sql_injection_in_services_field_is_sanitized(self, client):
        """SQL injection pattern in a text field must not crash or corrupt the DB."""
        d = _signup(client)
        evil_services = "Annual physicals'; DROP TABLE clinics; -- 12345"
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={"services_offered": evil_services},
                         headers=_headers(d["token"]))
        # Should succeed (stored as plain text via ORM) or be rejected — NOT 500
        assert r.status_code in (200, 400, 422), \
            f"SQL injection caused unexpected status {r.status_code}: {r.text}"
        # DB must still be alive — we can still read the profile
        profile_r = client.get(f"/api/{d['slug']}/profile",
                               headers=_headers(d["token"]))
        assert profile_r.status_code == 200, "DB appears broken after SQL injection attempt"

    def test_xss_in_name_field_stored_as_text(self, client):
        """XSS payload in name field must be stored as-is (server is not an HTML renderer)
        and must not cause 500."""
        d = _signup(client)
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={"name": "<script>alert(1)</script>"},
                         headers=_headers(d["token"]))
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            # If stored, verify it's retrievable (DB intact)
            profile_r = client.get(f"/api/{d['slug']}/profile",
                                   headers=_headers(d["token"]))
            assert profile_r.status_code == 200

    def test_oversized_phone_field(self, client):
        """Extremely long phone field must not cause 500 (SQLAlchemy column limit)."""
        d = _signup(client)
        r = client.patch(f"/api/{d['slug']}/profile",
                         json={"phone": "X" * 5000},
                         headers=_headers(d["token"]))
        # Should be rejected by schema validation OR stored truncated — not 500
        assert r.status_code != 500, f"Oversized input caused 500: {r.text[:200]}"

    def test_nonexistent_clinic_slug_returns_404_or_403(self, client):
        """PATCH to a slug that doesn't exist — cannot succeed."""
        d = _signup(client)
        r = client.patch("/api/this-clinic-does-not-exist-xyz/profile",
                         json={"phone": "800-555-1234"},
                         headers=_headers(d["token"]))
        # Token belongs to a different slug → 403; missing clinic can also be 404
        assert r.status_code in (403, 404), \
            f"Expected 403/404 for nonexistent slug, got {r.status_code}"


# ── POSITIVE: GET /profile returns all Setup tab fields ──────────────────────

class TestGetProfileReturnsAllSetupFields:
    """GET /api/{slug}/profile must return all the fields the Setup tab displays."""

    def test_get_profile_has_all_setup_tab_fields(self, client):
        """All fields shown in the Setup tab must be present in the profile API response."""
        d = _signup(client)
        profile = client.get(f"/api/{d['slug']}/profile",
                             headers=_headers(d["token"])).json()
        expected_fields = [
            "name", "specialty", "phone", "address", "city_state",
            "office_hours", "providers", "services_offered", "insurance_accepted",
            "cancellation_policy", "after_hours_protocol", "escalation_contact",
            "hipaa_verify_method", "timezone", "agent_name",
            "reminder_72h_enabled", "reminder_24h_enabled",
        ]
        missing = [f for f in expected_fields if f not in profile]
        assert not missing, f"GET /profile missing fields: {missing}"

    def test_get_profile_requires_auth(self, client):
        """GET /api/{slug}/profile without token → 403."""
        d = _signup(client)
        r = client.get(f"/api/{d['slug']}/profile")
        assert r.status_code in (401, 403)

    def test_get_profile_cross_clinic_blocked(self, client):
        """Clinic A cannot read Clinic B's profile."""
        a = _signup(client)
        b = _signup(client)
        r = client.get(f"/api/{b['slug']}/profile",
                       headers=_headers(a["token"]))
        assert r.status_code == 403
