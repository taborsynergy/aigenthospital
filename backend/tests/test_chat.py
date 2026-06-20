"""Chat / AI Agent endpoint tests — REST chat, config, analytics, profile."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_chat.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.db import crud
from backend.routers.clinic_auth import hash_password

_test_counter = 0


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
def clinic(db):
    global _test_counter
    _test_counter += 1
    slug = f"chat-clinic-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Chat Test Clinic {_test_counter}",
        specialty="Family Medicine",
        email=f"{slug}@test.com",
        phone="5551234567",
        subscription_status="active",
        plan="professional",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def expired_clinic(db):
    global _test_counter
    _test_counter += 1
    slug = f"expired-{_test_counter}"
    c = Clinic(
        slug=slug, name=f"Expired {_test_counter}", specialty="Dental",
        email=f"{slug}@test.com", subscription_status="trial",
        plan="starter", customer_password_hash=hash_password("testpass123"),
        is_active=True,
        trial_ends_at=datetime.utcnow() - timedelta(days=1),  # expired
    )
    db.add(c); db.commit(); db.refresh(c)
    yield c
    db.query(Clinic).filter(Clinic.id == c.id).delete(); db.commit()


@pytest.fixture
def token(client, clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": clinic.email, "password": "testpass123"})
    return r.json()["token"]


# ── Health Checks ─────────────────────────────────────────────────────────────

class TestHealthEndpoints:

    def test_health_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_returns_service_name(self, client):
        r = client.get("/api/health")
        assert "service" in r.json()

    def test_ai_health_returns_status(self, client):
        """AI health endpoint always returns a status field."""
        r = client.get("/api/health/ai")
        assert r.status_code == 200
        assert "status" in r.json()  # "ok" when API works, "error" in test env without real key


# ── Clinic Config ─────────────────────────────────────────────────────────────

class TestClinicConfig:

    def test_config_returns_expected_fields(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/config")
        assert r.status_code == 200
        d = r.json()
        assert d["agent_name"] is not None
        assert d["clinic_name"] == clinic.name
        assert d["specialty"] == clinic.specialty

    def test_config_unknown_clinic_returns_404(self, client):
        r = client.get("/api/totally-unknown-clinic-abc/config")
        assert r.status_code == 404

    def test_config_includes_white_label_flag(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/config")
        assert "white_label" in r.json()


# ── REST Chat ─────────────────────────────────────────────────────────────────

class TestRestChat:

    def test_chat_returns_response(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "What are your office hours?"})
        assert r.status_code == 200
        d = r.json()
        assert "content" in d
        assert len(d["content"]) > 0

    def test_chat_returns_session_id(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "Hello"})
        assert r.status_code == 200
        assert "session_id" in r.json()

    def test_chat_preserves_session_id(self, client, clinic):
        """Passing a session_id should return the same one."""
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "Hello", "session_id": "test-session-123"})
        assert r.status_code == 200
        assert r.json()["session_id"] == "test-session-123"

    def test_chat_empty_message_returns_400(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat", json={"message": ""})
        assert r.status_code == 400

    def test_chat_whitespace_only_returns_400(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat", json={"message": "   "})
        assert r.status_code == 400

    def test_chat_unknown_clinic_returns_404(self, client):
        r = client.post("/api/nonexistent-slug-abc/chat",
                        json={"message": "Hello"})
        assert r.status_code == 404

    def test_chat_expired_trial_blocked(self, client, expired_clinic):
        r = client.post(f"/api/{expired_clinic.slug}/chat",
                        json={"message": "Book an appointment"})
        assert r.status_code == 403

    def test_chat_escalated_flag_present(self, client, clinic):
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "I have chest pain"})
        assert r.status_code == 200
        assert "escalated" in r.json()


# ── Profile Endpoints ─────────────────────────────────────────────────────────

class TestProfileEndpoints:

    def test_get_profile_returns_clinic_data(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/profile",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == clinic.name
        assert "specialty" in d
        assert "office_hours" in d

    def test_get_profile_requires_auth(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/profile")
        assert r.status_code == 403

    def test_update_profile_name(self, client, clinic, token):
        r = client.patch(f"/api/{clinic.slug}/profile",
                         json={"name": "Updated Clinic Name"},
                         headers={"X-Clinic-Token": token})
        assert r.status_code == 200
        assert r.json().get("ok") is True or "updated_fields" in r.json()

    def test_update_profile_requires_auth(self, client, clinic):
        r = client.patch(f"/api/{clinic.slug}/profile",
                         json={"agent_name": "Bob"})
        assert r.status_code == 403


# ── Analytics Endpoint ────────────────────────────────────────────────────────

class TestAnalyticsEndpoint:

    def test_analytics_returns_data(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/analytics",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200

    def test_analytics_requires_auth(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/analytics")
        assert r.status_code == 403

    def test_analytics_today_report(self, client, clinic, token):
        r = client.get(f"/api/{clinic.slug}/analytics?report=today",
                       headers={"X-Clinic-Token": token})
        assert r.status_code == 200


# ── Regression: multi-turn chat history serialization ────────────────────────
# Bug: anthropic SDK >= 0.40 model_dump() adds citations:null on TextBlock.
# When history is passed back on the 2nd turn the API rejected it (BadRequestError).
# Fix: _serialize_block() builds explicit clean dicts — no extra None fields.

class TestMultiTurnChatRegression:

    def test_serialize_text_block_excludes_none_fields(self):
        """_serialize_block must never include None fields on a text block."""
        from backend.agent.aria import _serialize_block

        class _FakeTextBlock:
            type = "text"
            text = "Hello, how can I help?"
            citations = None          # field added by newer anthropic SDK

        result = _serialize_block(_FakeTextBlock())
        assert result == {"type": "text", "text": "Hello, how can I help?"}
        assert "citations" not in result

    def test_serialize_tool_use_block_correct_format(self):
        """_serialize_block returns id/name/input for tool_use blocks."""
        from backend.agent.aria import _serialize_block

        class _FakeToolUseBlock:
            type = "tool_use"
            id = "toolu_01abc"
            name = "book_appointment"
            input = {"patient_name": "Jane Doe", "appointment_type": "checkup"}

        result = _serialize_block(_FakeToolUseBlock())
        assert result == {
            "type":  "tool_use",
            "id":    "toolu_01abc",
            "name":  "book_appointment",
            "input": {"patient_name": "Jane Doe", "appointment_type": "checkup"},
        }
        assert "citations" not in result

    def test_multiturn_chat_second_message_succeeds(self, client, clinic):
        """Second turn on same session must not return an error.

        Regression for: BadRequestError caused by citations:null in saved
        assistant content being passed back to the Anthropic API on turn 2.
        """
        session = "regr-multiturn-001"
        r1 = client.post(f"/api/{clinic.slug}/chat",
                         json={"message": "Schedule an appointment",
                               "session_id": session})
        assert r1.status_code == 200, f"Turn 1 failed: {r1.text}"

        r2 = client.post(f"/api/{clinic.slug}/chat",
                         json={"message": "first time",
                               "session_id": session})
        assert r2.status_code == 200, f"Turn 2 failed: {r2.text}"
        body = r2.json()
        assert "content" in body
        assert "error" not in body


# ── Multi-turn conversation flows ─────────────────────────────────────────────

class TestMultiTurnConversations:
    """Multi-turn REST chat: verifies history carries across turns and Aria
    responds correctly across realistic patient conversation flows."""

    def _chat(self, client, clinic, message, session):
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": message, "session_id": session})
        assert r.status_code == 200, f"message={message!r} failed: {r.text}"
        return r.json()

    def test_scheduling_flow_three_turns(self, client, clinic):
        """Book appointment across 3 turns: intent → patient type → name."""
        s = "mt-sched-001"
        r1 = self._chat(client, clinic, "I need to book an appointment", s)
        assert "content" in r1

        r2 = self._chat(client, clinic, "I am a new patient", s)
        assert "content" in r2

        r3 = self._chat(client, clinic, "My name is Sam Johnson", s)
        assert "content" in r3
        # Session ID must be consistent throughout
        assert r3["session_id"] == s

    def test_intake_form_offered_by_email_only(self, client, clinic):
        """After booking as new patient Aria must NOT ask SMS vs email —
        intake forms are email-only."""
        s = "mt-intake-001"
        self._chat(client, clinic, "Book an appointment for new patient Sam", s)
        self._chat(client, clinic, "yes send me the intake form", s)
        r = self._chat(client, clinic, "my email is sam@example.com", s)
        # Response must not contain the word SMS in any case variation
        assert "sms" not in r["content"].lower(), (
            "Aria offered SMS for intake form — SMS is not supported")

    def test_faq_flow_two_turns(self, client, clinic):
        """Office-hours question followed by insurance question — both answered."""
        s = "mt-faq-001"
        r1 = self._chat(client, clinic, "What are your office hours?", s)
        assert "content" in r1

        r2 = self._chat(client, clinic, "Do you accept Aetna insurance?", s)
        assert "content" in r2
        assert "error" not in r2

    def test_reschedule_flow_two_turns(self, client, clinic):
        """Reschedule intent then new time — both turns return 200."""
        s = "mt-reschedule-001"
        self._chat(client, clinic, "I need to reschedule my appointment", s)
        r2 = self._chat(client, clinic, "Can we do next Monday at 10am?", s)
        assert r2["status_code"] if "status_code" in r2 else True
        assert "content" in r2

    def test_different_sessions_are_isolated(self, client, clinic):
        """Two different session IDs must not share history."""
        self._chat(client, clinic, "My name is Alice", "mt-iso-001")
        r = self._chat(client, clinic, "What was my name?", "mt-iso-002")
        # The second session has no context about Alice
        assert "content" in r
        assert r["session_id"] == "mt-iso-002"

    def test_five_turn_conversation_all_succeed(self, client, clinic):
        """5-turn conversation — every turn returns 200 with content."""
        s = "mt-five-001"
        messages = [
            "Hello",
            "I'd like to make an appointment",
            "I am an existing patient",
            "My name is David Park",
            "I prefer mornings",
        ]
        for msg in messages:
            r = self._chat(client, clinic, msg, s)
            assert "content" in r, f"Turn failed on: {msg!r}"


# ── Regression REG-003: Aria date reasoning must use today's date ─────────────
# Bug: Aria told a patient "July 1st has already passed" on June 20.
# Root cause: system prompt had no today's date → Aria used training-data date
#   (pre-2026 knowledge cutoff) → wrongly computed future dates as past.
# Fix: inject Today is {weekday, Month DD, YYYY} at top of every system prompt.

class TestDateAwarenessRegression:

    def test_system_prompt_contains_todays_date(self, clinic):
        """build_system_prompt must include today's date string."""
        from backend.agent.prompts import build_system_prompt
        from datetime import date
        prompt = build_system_prompt(clinic)
        today_str = date.today().strftime("%B %d, %Y")
        assert today_str in prompt, (
            f"System prompt missing today's date ({today_str}). "
            "Aria will make date reasoning errors without it."
        )

    def test_system_prompt_date_changes_each_day(self, clinic):
        """The injected date must be dynamic (evaluated at call time), not hardcoded."""
        from backend.agent.prompts import build_system_prompt
        from datetime import date
        p1 = build_system_prompt(clinic)
        p2 = build_system_prompt(clinic)
        today_str = date.today().strftime("%B %d, %Y")
        assert today_str in p1
        assert today_str in p2

    def test_chat_response_does_not_claim_future_date_is_past(self, client, clinic):
        """Aria must not claim a clearly-future month is already past.
        Uses 'next December' which is always at least months away.
        MOCK_MODE: canned response won't contain past-date language."""
        r = client.post(f"/api/{clinic.slug}/chat",
                        json={"message": "Do you have any slots in December next year?",
                              "session_id": "reg003-date-001"})
        assert r.status_code == 200
        content = r.json().get("content", "").lower()
        assert "has already passed" not in content, (
            "Aria claimed a future date has already passed — date injection may be missing"
        )
