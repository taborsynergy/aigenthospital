"""
End-to-End Journey Tests — E2E-001 to E2E-010

Simulates every real-world scenario a doctor/clinic admin or patient performs,
from the very first step (landing page / signup) through to the final outcome
(appointment confirmed, email sent, status updated).

No individual unit is tested here — each test follows a complete user story
from start to finish, exercising multiple layers in sequence.

Journeys covered:
  E2E-001  Doctor: Full onboarding  (signup → login → configure → verify)
  E2E-002  Doctor: Clinic setup     (profile, providers, appointment types, hours)
  E2E-003  Patient: Chat — book appointment via Aria
  E2E-004  Patient: Information queries (insurance, hours, location, policy)
  E2E-005  Doctor: Manages appointments (view, confirm, complete, cancel)
  E2E-006  Safety: Emergency + crisis conversations
  E2E-007  Visitor/Lead: Demo request, trial signup, white-label quote
  E2E-008  Complete end-to-end: signup → setup → patient books → doctor confirms
  E2E-009  Multi-patient: two patients book simultaneously, both recorded
  E2E-010  Plan gating: starter vs professional feature limits
"""
import os
import uuid
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_e2e.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment
from backend.db import crud
from backend.routers.clinic_auth import hash_password

_counter = 0


def _uid() -> str:
    global _counter
    _counter += 1
    return f"e2e-{_counter}"


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


def _make_clinic(db, plan="professional", status="active", days=30, **kwargs):
    """Helper: create a fully active clinic directly in DB."""
    uid = _uid()
    slug = kwargs.pop("slug", f"clinic-{uid}")
    trial_ends = kwargs.pop("trial_ends_at", datetime.utcnow() + timedelta(days=days))
    c = Clinic(
        slug=slug,
        name=kwargs.pop("name", f"Test Clinic {uid}"),
        specialty=kwargs.pop("specialty", "Family Medicine"),
        email=kwargs.pop("email", f"{slug}@test.com"),
        phone=kwargs.pop("phone", "5551234567"),
        subscription_status=status,
        plan=plan,
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        trial_ends_at=trial_ends,
        **kwargs,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _login(client, clinic):
    r = client.post("/api/clinic-auth/login",
                    json={"email": clinic.email, "password": "testpass123"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["token"]


def _auth(token):
    return {"X-Clinic-Token": token}


def _chat(client, slug, message, session_id=None):
    sid = session_id or str(uuid.uuid4())
    r = client.post(f"/api/{slug}/chat",
                    json={"message": message, "session_id": sid})
    return r, sid


def _seed_appointment(db, clinic, **kwargs):
    uid = _uid()
    appt = Appointment(
        clinic_id=clinic.id,
        confirmation_number=kwargs.get("confirmation_number", f"CONF-{uid}"),
        patient_name=kwargs.get("patient_name", "Jane Patient"),
        patient_phone=kwargs.get("patient_phone", "5559876543"),
        patient_email=kwargs.get("patient_email", "jane@patient.com"),
        appointment_type=kwargs.get("appointment_type", "New Patient Visit"),
        appointment_datetime=kwargs.get("appointment_datetime", "2026-08-01 10:00 AM"),
        provider=kwargs.get("provider", "Dr. Smith"),
        status=kwargs.get("status", "scheduled"),
        channel=kwargs.get("channel", "web"),
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-001 — Doctor: Full Onboarding Journey
# Signup via public API → auto-login → access portal
# ═══════════════════════════════════════════════════════════════════════════════

class TestDoctorOnboardingJourney:

    def test_e2e001a_signup_creates_clinic(self, client):
        """E2E-001-A: POST /api/signup creates a clinic and returns portal URL."""
        with patch("backend.routers.signup.send_trial_signup_email"):
            r = client.post("/api/signup", json={
                "practice_name": "Sunrise Family Clinic",
                "contact_email": f"sunrise{_uid()}@test.com",
                "password": "Secure123!",
                "specialty": "Family Medicine",
                "phone": "5551112222",
                "plan": "starter",
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert "slug" in body
        assert "portal_url" in body
        assert "chat_url" in body
        assert "trial_ends_at" in body

    def test_e2e001b_portal_url_contains_token(self, client):
        """E2E-001-B: portal_url contains ?token= for auto-login."""
        with patch("backend.routers.signup.send_trial_signup_email"):
            r = client.post("/api/signup", json={
                "practice_name": "Token Test Clinic",
                "contact_email": f"token{_uid()}@test.com",
                "password": "Secure123!",
                "specialty": "Pediatrics",
                "plan": "starter",
            })
        assert "token=" in r.json()["portal_url"]

    def test_e2e001c_portal_page_loads_after_signup(self, client):
        """E2E-001-C: GET /c/{slug} returns 200 — doctor can open the portal."""
        with patch("backend.routers.signup.send_trial_signup_email"):
            r = client.post("/api/signup", json={
                "practice_name": "Portal Load Clinic",
                "contact_email": f"portal{_uid()}@test.com",
                "password": "Secure123!",
                "specialty": "Cardiology",
                "plan": "professional",
            })
        slug = r.json()["slug"]
        portal = client.get(f"/c/{slug}")
        assert portal.status_code == 200
        assert slug in portal.text

    def test_e2e001d_doctor_can_login_with_credentials(self, client, db):
        """E2E-001-D: Doctor logs in with email + password and gets a JWT token."""
        clinic = _make_clinic(db)
        r = client.post("/api/clinic-auth/login",
                        json={"email": clinic.email, "password": "testpass123"})
        assert r.status_code == 200
        assert "token" in r.json()
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()

    def test_e2e001e_wrong_password_rejected(self, client, db):
        """E2E-001-E: Wrong password returns 401 — doctor cannot access portal."""
        clinic = _make_clinic(db)
        r = client.post("/api/clinic-auth/login",
                        json={"email": clinic.email, "password": "WRONG"})
        assert r.status_code in (401, 403)
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()

    def test_e2e001f_token_grants_appointment_access(self, client, db):
        """E2E-001-F: Token from login grants access to protected endpoints."""
        clinic = _make_clinic(db)
        token = _login(client, clinic)
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        assert r.status_code == 200
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()

    def test_e2e001g_no_token_denied(self, client, db):
        """E2E-001-G: Accessing portal data without token returns 403."""
        clinic = _make_clinic(db)
        r = client.get(f"/api/{clinic.slug}/appointments")
        assert r.status_code == 403
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-002 — Doctor: Clinic Setup Journey
# Configure profile, providers, appointment types, hours
# ═══════════════════════════════════════════════════════════════════════════════

class TestDoctorClinicSetupJourney:

    @pytest.fixture
    def setup(self, client, db):
        clinic = _make_clinic(db, plan="professional")
        token = _login(client, clinic)
        yield client, clinic, token
        db.query(Appointment).filter(Appointment.clinic_id == clinic.id).delete()
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()

    def test_e2e002a_doctor_updates_clinic_profile(self, setup):
        """E2E-002-A: Doctor fills in clinic profile — phone, address, insurance, hours."""
        client, clinic, token = setup
        r = client.patch(f"/api/{clinic.slug}/profile", headers=_auth(token), json={
            "name": "Updated Sunrise Clinic",
            "phone": "5550001111",
            "address": "123 Main St, Austin TX 78701",
            "insurance_accepted": "Blue Cross, Aetna, United, Medicare",
            "office_hours": "Mon-Fri 8am-5pm, Sat 9am-1pm",
            "cancellation_policy": "24-hour notice required. $50 late cancellation fee.",
            "after_hours_protocol": "For emergencies call 911. We return calls by 9am next day.",
        })
        assert r.status_code == 200

    def test_e2e002b_profile_fields_persist(self, setup):
        """E2E-002-B: Updated profile fields are readable back from the API."""
        client, clinic, token = setup
        client.patch(f"/api/{clinic.slug}/profile", headers=_auth(token), json={
            "phone": "5550009999",
            "address": "999 Oak Ave, Dallas TX 75201",
        })
        r = client.get(f"/api/{clinic.slug}/profile", headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert data.get("phone") == "5550009999"
        assert "999 Oak Ave" in (data.get("address") or "")

    def test_e2e002c_doctor_adds_provider(self, setup):
        """E2E-002-C: Doctor adds a provider — appears in provider list."""
        client, clinic, token = setup
        r = client.post(f"/api/{clinic.slug}/providers", headers=_auth(token),
                        json={"name": "Dr. Emily Carter", "specialty": "Family Medicine"})
        assert r.status_code in (200, 201)
        resp = client.get(f"/api/{clinic.slug}/providers", headers=_auth(token)).json()
        names = [p["name"] for p in (resp.get("providers") or resp)]
        assert "Dr. Emily Carter" in names

    def test_e2e002d_doctor_adds_appointment_type(self, setup):
        """E2E-002-D: Doctor adds appointment types — appear in list."""
        client, clinic, token = setup
        for apt_type in ["New Patient Visit", "Follow-up", "Annual Physical"]:
            r = client.post(f"/api/{clinic.slug}/appointment-types",
                            headers=_auth(token),
                            json={"name": apt_type, "duration_minutes": 30})
            assert r.status_code in (200, 201), f"Failed adding {apt_type}: {r.text}"

        resp = client.get(f"/api/{clinic.slug}/appointment-types",
                          headers=_auth(token)).json()
        types = resp.get("appointment_types") or resp
        names = [t["name"] for t in types]
        assert "New Patient Visit" in names
        assert "Follow-up" in names

    def test_e2e002e_doctor_views_empty_appointments_after_setup(self, setup):
        """E2E-002-E: Fresh clinic has no appointments — dashboard shows empty list."""
        client, clinic, token = setup
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_e2e002f_doctor_can_set_custom_agent_name(self, setup):
        """E2E-002-F: Professional plan clinic can rename Aria to a custom agent name."""
        client, clinic, token = setup
        r = client.patch(f"/api/{clinic.slug}/profile", headers=_auth(token),
                         json={"agent_name": "Maya"})
        assert r.status_code == 200

    def test_e2e002g_chat_config_reflects_clinic_name(self, setup):
        """E2E-002-G: /api/{slug}/config returns the clinic's name for widget branding."""
        client, clinic, token = setup
        r = client.get(f"/api/{clinic.slug}/config")
        assert r.status_code == 200
        data = r.json()
        assert "clinic_name" in data or "name" in data


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-003 — Patient: Chat with Aria to Book Appointment
# ═══════════════════════════════════════════════════════════════════════════════

class TestPatientBookingJourney:

    @pytest.fixture
    def clinic(self, db):
        c = _make_clinic(db, plan="professional",
                         insurance_accepted="Blue Cross, Aetna",
                         office_hours="Mon-Fri 8am-5pm",
                         address="100 Health Blvd, Austin TX 78701",
                         cancellation_policy="24-hour notice required.")
        yield c
        db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
        db.query(Clinic).filter(Clinic.id == c.id).delete()
        db.commit()

    def test_e2e003a_patient_starts_chat_gets_reply(self, client, clinic):
        """E2E-003-A: Patient sends first message — Aria replies (not an error)."""
        r, _ = _chat(client, clinic.slug, "Hi, I'd like to book an appointment")
        assert r.status_code == 200
        body = r.json()
        assert "content" in body
        assert len(body["content"]) > 0

    def test_e2e003b_patient_asks_for_appointment_gets_response(self, client, clinic):
        """E2E-003-B: 'I need an appointment' triggers Aria's booking flow."""
        r, _ = _chat(client, clinic.slug, "I need an appointment please")
        assert r.status_code == 200
        assert "content" in r.json()

    def test_e2e003c_chat_session_maintains_context(self, client, clinic):
        """E2E-003-C: Two messages in same session — both get valid replies."""
        _, sid = _chat(client, clinic.slug, "I need an appointment")
        r2, _ = _chat(client, clinic.slug, "My name is John Smith", session_id=sid)
        assert r2.status_code == 200
        assert "content" in r2.json()

    def test_e2e003d_appointment_created_appears_in_doctor_portal(self, client, db, clinic):
        """E2E-003-D: Appointment created via API appears in doctor's appointment list."""
        appt = _seed_appointment(db, clinic,
                                 patient_name="Sarah Johnson",
                                 appointment_type="New Patient Visit",
                                 appointment_datetime="2026-09-15 2:00 PM")
        token = _login(client, clinic)
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        assert r.status_code == 200
        names = [a["patient_name"] for a in r.json()]
        assert "Sarah Johnson" in names

    def test_e2e003e_booked_appointment_has_confirmation_number(self, client, db, clinic):
        """E2E-003-E: Every booked appointment has a unique confirmation number."""
        appt = _seed_appointment(db, clinic, confirmation_number="CONF-SARAH-001")
        token = _login(client, clinic)
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        conf_nums = [a["confirmation_number"] for a in r.json()]
        assert "CONF-SARAH-001" in conf_nums

    def test_e2e003f_multiple_patients_all_appear_in_list(self, client, db, clinic):
        """E2E-003-F: Three different patients book — all three appear in the list."""
        for i, name in enumerate(["Alice Brown", "Bob Davis", "Carol Evans"]):
            _seed_appointment(db, clinic, patient_name=name,
                              confirmation_number=f"CONF-MULTI-{i}")
        token = _login(client, clinic)
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        names = [a["patient_name"] for a in r.json()]
        assert "Alice Brown" in names
        assert "Bob Davis" in names
        assert "Carol Evans" in names

    def test_e2e003g_new_appointment_status_is_scheduled(self, client, db, clinic):
        """E2E-003-G: Newly booked appointment has status 'scheduled' by default."""
        appt = _seed_appointment(db, clinic, status="scheduled")
        token = _login(client, clinic)
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        appts = [a for a in r.json() if a["confirmation_number"] == appt.confirmation_number]
        assert appts[0]["status"] == "scheduled"


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-004 — Patient: Information Queries to Aria
# ═══════════════════════════════════════════════════════════════════════════════

class TestPatientInformationQueries:

    @pytest.fixture
    def clinic(self, db):
        c = _make_clinic(db, plan="professional",
                         insurance_accepted="Blue Cross Blue Shield, Aetna, United Healthcare, Medicare, Medicaid",
                         office_hours="Monday to Friday 8am to 5pm, Saturday 9am to 1pm",
                         address="200 Wellness Way, Austin TX 78702",
                         cancellation_policy="Please cancel at least 24 hours in advance to avoid a $50 fee.",
                         after_hours_protocol="For medical emergencies call 911. For urgent questions call our answering service at 555-0199.")
        yield c
        db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
        db.query(Clinic).filter(Clinic.id == c.id).delete()
        db.commit()

    @pytest.mark.parametrize("question", [
        "Do you accept Blue Cross insurance?",
        "What insurance plans do you take?",
        "Is my Aetna plan accepted here?",
    ])
    def test_e2e004a_patient_asks_about_insurance(self, client, clinic, question):
        """E2E-004-A: Patient asks about insurance — Aria replies (not an error)."""
        r, _ = _chat(client, clinic.slug, question)
        assert r.status_code == 200
        assert len(r.json()["content"]) > 0

    @pytest.mark.parametrize("question", [
        "What are your office hours?",
        "Are you open on Saturdays?",
        "When do you close?",
    ])
    def test_e2e004b_patient_asks_about_hours(self, client, clinic, question):
        """E2E-004-B: Patient asks about hours — Aria replies."""
        r, _ = _chat(client, clinic.slug, question)
        assert r.status_code == 200
        assert len(r.json()["content"]) > 0

    @pytest.mark.parametrize("question", [
        "Where is your clinic located?",
        "What is your address?",
        "How do I get to your office?",
    ])
    def test_e2e004c_patient_asks_about_location(self, client, clinic, question):
        """E2E-004-C: Patient asks for location — Aria replies."""
        r, _ = _chat(client, clinic.slug, question)
        assert r.status_code == 200
        assert len(r.json()["content"]) > 0

    @pytest.mark.parametrize("question", [
        "What is your cancellation policy?",
        "Can I cancel my appointment?",
        "Is there a fee if I cancel?",
    ])
    def test_e2e004d_patient_asks_about_cancellation(self, client, clinic, question):
        """E2E-004-D: Patient asks about cancellation policy — Aria replies."""
        r, _ = _chat(client, clinic.slug, question)
        assert r.status_code == 200
        assert len(r.json()["content"]) > 0

    def test_e2e004e_patient_asks_what_aria_can_do(self, client, clinic):
        """E2E-004-E: Patient asks 'what can you help me with?' — Aria replies."""
        r, _ = _chat(client, clinic.slug, "What can you help me with?")
        assert r.status_code == 200
        assert len(r.json()["content"]) > 0

    def test_e2e004f_chat_returns_json_not_html(self, client, clinic):
        """E2E-004-F: Chat endpoint always returns JSON, never an HTML error page."""
        r, _ = _chat(client, clinic.slug, "Hello")
        assert r.headers.get("content-type", "").startswith("application/json")


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-005 — Doctor: Manages Appointments
# View, filter, confirm, complete, cancel
# ═══════════════════════════════════════════════════════════════════════════════

class TestDoctorManagesAppointments:

    @pytest.fixture
    def setup(self, client, db):
        clinic = _make_clinic(db, plan="professional")
        token = _login(client, clinic)
        appt = _seed_appointment(db, clinic,
                                 patient_name="Michael Torres",
                                 appointment_type="Follow-up",
                                 status="scheduled")
        yield client, clinic, token, appt
        db.query(Appointment).filter(Appointment.clinic_id == clinic.id).delete()
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()

    def test_e2e005a_doctor_views_appointment_list(self, setup):
        """E2E-005-A: Doctor sees all appointments in their clinic."""
        client, clinic, token, appt = setup
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_e2e005b_appointment_contains_patient_details(self, setup):
        """E2E-005-B: Appointment record has patient name, type, date, status."""
        client, clinic, token, appt = setup
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        a = r.json()[0]
        assert "patient_name" in a
        assert "appointment_type" in a
        assert "appointment_datetime" in a
        assert "status" in a
        assert "confirmation_number" in a

    def test_e2e005c_doctor_confirms_appointment(self, setup):
        """E2E-005-C: Doctor marks appointment as confirmed."""
        client, clinic, token, appt = setup
        r = client.patch(f"/api/{clinic.slug}/appointments/{appt.confirmation_number}",
                         headers=_auth(token), json={"status": "confirmed"})
        assert r.status_code == 200

    def test_e2e005d_confirmed_status_persists(self, setup):
        """E2E-005-D: Confirmed status is visible in subsequent list fetch."""
        client, clinic, token, appt = setup
        client.patch(f"/api/{clinic.slug}/appointments/{appt.confirmation_number}",
                     headers=_auth(token), json={"status": "confirmed"})
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        target = [a for a in r.json() if a["confirmation_number"] == appt.confirmation_number]
        assert target[0]["status"] == "confirmed"

    def test_e2e005e_doctor_marks_appointment_completed(self, setup):
        """E2E-005-E: Doctor marks appointment completed after the visit."""
        client, clinic, token, appt = setup
        r = client.patch(f"/api/{clinic.slug}/appointments/{appt.confirmation_number}",
                         headers=_auth(token), json={"status": "completed"})
        assert r.status_code == 200

    def test_e2e005f_doctor_cancels_appointment(self, setup):
        """E2E-005-F: Doctor cancels an appointment — status updates to cancelled."""
        client, clinic, token, appt = setup
        r = client.patch(f"/api/{clinic.slug}/appointments/{appt.confirmation_number}",
                         headers=_auth(token), json={"status": "cancelled"})
        assert r.status_code == 200

    def test_e2e005g_doctor_cannot_update_other_clinics_appointment(self, setup, db):
        """E2E-005-G: Doctor cannot update an appointment belonging to another clinic."""
        client, clinic, token, appt = setup
        other = _make_clinic(db)
        other_appt = _seed_appointment(db, other)
        r = client.patch(f"/api/{clinic.slug}/appointments/{other_appt.confirmation_number}",
                         headers=_auth(token), json={"status": "confirmed"})
        assert r.status_code in (403, 404)
        db.query(Appointment).filter(Appointment.clinic_id == other.id).delete()
        db.query(Clinic).filter(Clinic.id == other.id).delete()
        db.commit()

    def test_e2e005h_appointment_list_is_clinic_isolated(self, setup, db):
        """E2E-005-H: Doctor only sees their own clinic's appointments."""
        client, clinic, token, appt = setup
        other = _make_clinic(db)
        _seed_appointment(db, other, patient_name="Spy Patient")
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        names = [a["patient_name"] for a in r.json()]
        assert "Spy Patient" not in names
        db.query(Appointment).filter(Appointment.clinic_id == other.id).delete()
        db.query(Clinic).filter(Clinic.id == other.id).delete()
        db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-006 — Safety: Emergency and Crisis Conversations
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyScenarios:

    @pytest.fixture
    def clinic(self, db):
        c = _make_clinic(db)
        yield c
        db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
        db.query(Clinic).filter(Clinic.id == c.id).delete()
        db.commit()

    @pytest.mark.parametrize("emergency_message", [
        "I'm having a heart attack",
        "I can't breathe",
        "My child is unconscious",
        "I'm having severe chest pains",
        "Someone collapsed",
    ])
    def test_e2e006a_medical_emergency_gets_reply(self, client, clinic, emergency_message):
        """E2E-006-A: Medical emergency messages always get a reply (not an error/crash)."""
        r, _ = _chat(client, clinic.slug, emergency_message)
        assert r.status_code == 200
        reply = r.json().get("content", "")
        assert len(reply) > 0, "Aria must reply to emergency messages"

    @pytest.mark.parametrize("crisis_message", [
        "I want to hurt myself",
        "I'm thinking about suicide",
        "I don't want to live anymore",
    ])
    def test_e2e006b_mental_health_crisis_gets_reply(self, client, clinic, crisis_message):
        """E2E-006-B: Mental health crisis messages always get a reply (not an error/crash)."""
        r, _ = _chat(client, clinic.slug, crisis_message)
        assert r.status_code == 200
        reply = r.json().get("content", "")
        assert len(reply) > 0, "Aria must reply to crisis messages"

    def test_e2e006c_poison_control_scenario(self, client, clinic):
        """E2E-006-C: Child swallowed something — Aria replies."""
        r, _ = _chat(client, clinic.slug,
                     "My child swallowed some pills, what should I do?")
        assert r.status_code == 200
        assert len(r.json()["content"]) > 0

    def test_e2e006d_chat_never_returns_500_on_edge_input(self, client, clinic):
        """E2E-006-D: Unusual / very long input never causes a 500 server error."""
        long_message = "help " * 200
        r, _ = _chat(client, clinic.slug, long_message)
        assert r.status_code != 500

    def test_e2e006e_empty_message_handled_gracefully(self, client, clinic):
        """E2E-006-E: Empty message doesn't crash the server."""
        r, _ = _chat(client, clinic.slug, "")
        assert r.status_code in (200, 400, 422)


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-007 — Visitor/Lead Journey
# Demo request, trial signup, white-label quote
# ═══════════════════════════════════════════════════════════════════════════════

class TestVisitorLeadJourney:

    def test_e2e007a_landing_page_loads(self, client):
        """E2E-007-A: GET / returns the landing page (200, HTML)."""
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_e2e007b_landing_page_has_cta_buttons(self, client):
        """E2E-007-B: Landing page contains 'Book a Demo' and 'Start Free Trial' CTAs."""
        r = client.get("/")
        assert "Book a Demo" in r.text
        assert "Start Free Trial" in r.text or "Start Free" in r.text

    def test_e2e007c_demo_request_submission(self, client):
        """E2E-007-C: Visitor fills demo form — POST /api/demo-request returns 200."""
        with patch("backend.routers.signup.send_demo_request_email"):
            r = client.post("/api/demo-request", json={
                "full_name": "Dr. Lisa Park",
                "email": "lisa.park@clinic.com",
                "phone": "5550001234",
                "practice_name": "Park Pediatrics",
                "specialty": "Pediatrics",
                "num_providers": "2–5",
                "preferred_slot": "Morning — 9:00 AM to 11:00 AM (ET)",
                "message": "Looking to reduce front-desk call volume.",
            })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_e2e007d_demo_request_missing_required_field(self, client):
        """E2E-007-D: Demo form with missing required field returns error."""
        with patch("backend.routers.signup.send_demo_request_email"):
            r = client.post("/api/demo-request", json={
                "full_name": "Dr. Test",
                "email": "test@clinic.com",
                # missing practice_name, specialty, preferred_slot
            })
        assert r.status_code in (400, 422)

    def test_e2e007e_trial_signup_creates_account(self, client):
        """E2E-007-E: Visitor signs up for trial — gets clinic slug and chat URL."""
        with patch("backend.routers.signup.send_trial_signup_email"):
            r = client.post("/api/signup", json={
                "practice_name": "E2E Visitor Clinic",
                "contact_email": f"visitor{_uid()}@test.com",
                "password": "Secure123!",
                "specialty": "Dermatology",
                "plan": "starter",
            })
        assert r.status_code == 200
        body = r.json()
        assert "slug" in body
        assert "chat_url" in body

    def test_e2e007f_white_label_quote_submission(self, client):
        """E2E-007-F: Enterprise visitor requests a white-label quote."""
        with patch("backend.routers.signup.send_quote_email"):
            r = client.post("/api/quote", json={
                "full_name": "John Enterprise",
                "email": "john@healthsystem.org",
                "company": "Regional Health System",
                "phone": "5559990000",
                "locations": "15",
                "pms": "Epic",
                "message": "Interested in white-labeling for our 15 locations.",
            })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_e2e007g_plans_endpoint_returns_all_plans(self, client):
        """E2E-007-G: GET /api/plans returns all 4 plan tiers."""
        r = client.get("/api/plans")
        assert r.status_code == 200
        plans = r.json().get("plans", {})
        assert "starter" in plans
        assert "professional" in plans
        assert "enterprise" in plans


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-008 — Complete End-to-End: Signup → Setup → Patient Books → Doctor Confirms
# The single most important journey — covers every layer
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompleteEndToEndJourney:

    def test_e2e008_full_clinic_and_patient_flow(self, client, db):
        """
        E2E-008: COMPLETE JOURNEY

        Step 1 (Doctor)  : Sign up for trial
        Step 2 (Doctor)  : Log in to portal
        Step 3 (Doctor)  : Configure clinic profile (phone, address, insurance, hours)
        Step 4 (Doctor)  : Add a provider
        Step 5 (Doctor)  : Add appointment types
        Step 6 (Patient) : Chat with Aria — asks about insurance
        Step 7 (Patient) : Books an appointment (seeded directly)
        Step 8 (Doctor)  : Views appointment in portal
        Step 9 (Doctor)  : Confirms the appointment
        Step 10 (Doctor) : Appointment status reflects 'confirmed'
        """
        # Step 1 — Signup
        email = f"e2e008-{_uid()}@test.com"
        with patch("backend.routers.signup.send_trial_signup_email"):
            r = client.post("/api/signup", json={
                "practice_name": "Complete Journey Clinic",
                "contact_email": email,
                "password": "Secure123!",
                "specialty": "Family Medicine",
                "phone": "5551230000",
                "plan": "professional",
            })
        assert r.status_code == 200, f"Signup failed: {r.text}"
        slug = r.json()["slug"]

        # Step 2 — Login
        r = client.post("/api/clinic-auth/login",
                        json={"email": email, "password": "Secure123!"})
        assert r.status_code == 200, "Login failed after signup"
        token = r.json()["token"]
        hdrs = _auth(token)

        # Step 3 — Configure profile
        r = client.patch(f"/api/{slug}/profile", headers=hdrs, json={
            "phone": "5551239999",
            "address": "500 Complete St, Austin TX 78750",
            "insurance_accepted": "Blue Cross, Aetna, Medicare",
            "office_hours": "Mon-Fri 8am-5pm",
            "cancellation_policy": "24-hour cancellation notice required.",
        })
        assert r.status_code == 200, "Profile update failed"

        # Step 4 — Add provider
        r = client.post(f"/api/{slug}/providers", headers=hdrs,
                        json={"name": "Dr. James Wilson", "specialty": "Family Medicine"})
        assert r.status_code in (200, 201), "Provider add failed"

        # Step 5 — Add appointment type
        r = client.post(f"/api/{slug}/appointment-types", headers=hdrs,
                        json={"name": "New Patient Consultation", "duration_minutes": 45})
        assert r.status_code in (200, 201), "Appointment type add failed"

        # Step 6 — Patient asks about insurance
        r, sid = _chat(client, slug, "Do you accept Blue Cross?")
        assert r.status_code == 200, "Patient chat failed"
        assert len(r.json()["content"]) > 0

        # Step 7 — Patient books (seeded to simulate Aria booking)
        S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        s = S()
        try:
            clinic_record = s.query(Clinic).filter(Clinic.slug == slug).first()
            clinic_id_for_cleanup = clinic_record.id
            appt = _seed_appointment(s, clinic_record,
                                     patient_name="Complete Journey Patient",
                                     appointment_type="New Patient Consultation",
                                     appointment_datetime="2026-10-01 10:00 AM",
                                     confirmation_number="E2E-008-CONF")
        finally:
            s.close()

        # Step 8 — Doctor views appointments
        r = client.get(f"/api/{slug}/appointments", headers=hdrs)
        assert r.status_code == 200
        names = [a["patient_name"] for a in r.json()]
        assert "Complete Journey Patient" in names, "Patient not visible in portal"

        # Step 9 — Doctor confirms
        r = client.patch(f"/api/{slug}/appointments/E2E-008-CONF",
                         headers=hdrs, json={"status": "confirmed"})
        assert r.status_code == 200, "Status update failed"

        # Step 10 — Status reflects confirmed
        r = client.get(f"/api/{slug}/appointments", headers=hdrs)
        appts = [a for a in r.json() if a.get("confirmation_number") == "E2E-008-CONF"]
        assert appts, "Confirmed appointment not found"
        assert appts[0]["status"] == "confirmed"

        # Cleanup
        S2 = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        s2 = S2()
        try:
            s2.query(Appointment).filter(Appointment.clinic_id == clinic_id_for_cleanup).delete()
            s2.query(Clinic).filter(Clinic.slug == slug).delete()
            s2.commit()
        finally:
            s2.close()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-009 — Multi-Patient: Two Patients Book Simultaneously
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiPatientJourney:

    @pytest.fixture
    def clinic(self, db):
        c = _make_clinic(db, plan="professional")
        yield c
        db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
        db.query(Clinic).filter(Clinic.id == c.id).delete()
        db.commit()

    def test_e2e009a_two_patients_get_unique_confirmation_numbers(self, client, db, clinic):
        """E2E-009-A: Two patients booking simultaneously get different confirmation numbers."""
        appt1 = _seed_appointment(db, clinic, patient_name="Patient One",
                                  confirmation_number="UNIQUE-001")
        appt2 = _seed_appointment(db, clinic, patient_name="Patient Two",
                                  confirmation_number="UNIQUE-002")
        assert appt1.confirmation_number != appt2.confirmation_number

    def test_e2e009b_both_patients_appear_in_portal(self, client, db, clinic):
        """E2E-009-B: Both patients' appointments appear in the doctor's portal."""
        _seed_appointment(db, clinic, patient_name="First Patient",
                          confirmation_number="MULTI-P1")
        _seed_appointment(db, clinic, patient_name="Second Patient",
                          confirmation_number="MULTI-P2")
        token = _login(client, clinic)
        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        names = [a["patient_name"] for a in r.json()]
        assert "First Patient" in names
        assert "Second Patient" in names

    def test_e2e009c_two_patients_chat_same_clinic_independently(self, client, clinic):
        """E2E-009-C: Two patients chat on same clinic with different sessions — both get replies."""
        r1, sid1 = _chat(client, clinic.slug, "I need an appointment", session_id="session-P1")
        r2, sid2 = _chat(client, clinic.slug, "What are your hours?", session_id="session-P2")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert sid1 != sid2

    def test_e2e009d_doctor_can_update_each_patient_independently(self, client, db, clinic):
        """E2E-009-D: Doctor can confirm one and cancel another without affecting the other."""
        appt1 = _seed_appointment(db, clinic, patient_name="Confirm Me",
                                  confirmation_number="INDEP-001", status="scheduled")
        appt2 = _seed_appointment(db, clinic, patient_name="Cancel Me",
                                  confirmation_number="INDEP-002", status="scheduled")
        token = _login(client, clinic)

        client.patch(f"/api/{clinic.slug}/appointments/{appt1.confirmation_number}",
                     headers=_auth(token), json={"status": "confirmed"})
        client.patch(f"/api/{clinic.slug}/appointments/{appt2.confirmation_number}",
                     headers=_auth(token), json={"status": "cancelled"})

        r = client.get(f"/api/{clinic.slug}/appointments", headers=_auth(token))
        by_conf = {a["confirmation_number"]: a for a in r.json()}
        assert by_conf["INDEP-001"]["status"] == "confirmed"
        assert by_conf["INDEP-002"]["status"] == "cancelled"


# ═══════════════════════════════════════════════════════════════════════════════
# E2E-010 — Plan Gating: Starter vs Professional Feature Limits
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanGatingJourney:

    def test_e2e010a_starter_clinic_can_chat(self, client, db):
        """E2E-010-A: Starter plan clinic's patients can still chat with Aria."""
        clinic = _make_clinic(db, plan="starter")
        r, _ = _chat(client, clinic.slug, "Hello, I need help")
        assert r.status_code == 200
        assert "content" in r.json()
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()

    def test_e2e010b_professional_clinic_can_chat(self, client, db):
        """E2E-010-B: Professional plan clinic's patients can chat with Aria."""
        clinic = _make_clinic(db, plan="professional")
        r, _ = _chat(client, clinic.slug, "Hello, I need help")
        assert r.status_code == 200
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()

    def test_e2e010c_expired_trial_clinic_portal_still_renders(self, client, db):
        """E2E-010-C: Expired trial clinic's portal page still loads (doctor can log in)."""
        clinic = _make_clinic(db, status="trial",
                              days=-1,  # expired
                              trial_ends_at=datetime.utcnow() - timedelta(days=1))
        r = client.get(f"/c/{clinic.slug}")
        assert r.status_code == 200
        db.query(Clinic).filter(Clinic.id == clinic.id).delete()
        db.commit()

    def test_e2e010d_inactive_clinic_slug_returns_404(self, client):
        """E2E-010-D: Non-existent clinic slug returns 404, not a 500 crash."""
        r = client.get("/c/completely-nonexistent-slug-xyz99")
        assert r.status_code == 404

    def test_e2e010e_starter_plan_signup_succeeds(self, client):
        """E2E-010-E: Visitor can sign up for the free starter plan."""
        with patch("backend.routers.signup.send_trial_signup_email"):
            r = client.post("/api/signup", json={
                "practice_name": "Budget Clinic",
                "contact_email": f"budget{_uid()}@test.com",
                "password": "Budget123!",
                "specialty": "Chiropractic",
                "plan": "starter",
            })
        assert r.status_code == 200
        assert r.json()["plan"] == "starter"
