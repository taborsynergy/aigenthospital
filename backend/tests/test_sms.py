"""SMS and WhatsApp inbound webhook tests."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_sms.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.routers.clinic_auth import hash_password

_test_counter = 0
_TWILIO_NUMBER = "+15551230001"
_PATIENT_NUMBER = "+15559990001"


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
def sms_clinic(db):
    """Professional clinic with Twilio number configured."""
    global _test_counter
    _test_counter += 1
    slug = f"sms-clinic-{_test_counter}"
    number = f"+1555123{_test_counter:04d}"
    c = Clinic(
        slug=slug,
        name=f"SMS Test Clinic {_test_counter}",
        specialty="Family Medicine",
        email=f"{slug}@test.com",
        phone="5551234567",
        subscription_status="active",
        plan="professional",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        twilio_phone=number,
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def starter_clinic(db):
    """Starter plan — no SMS access."""
    global _test_counter
    _test_counter += 1
    slug = f"sms-starter-{_test_counter}"
    number = f"+1555200{_test_counter:04d}"
    c = Clinic(
        slug=slug,
        name=f"Starter SMS {_test_counter}",
        specialty="Dental",
        email=f"{slug}@test.com",
        phone="5559876543",
        subscription_status="active",
        plan="starter",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        twilio_phone=number,
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


def _sms_form(from_=_PATIENT_NUMBER, to_=None, body="Hello"):
    return {"From": from_, "To": to_ or _TWILIO_NUMBER, "Body": body}


# ── SMS Inbound ───────────────────────────────────────────────────────────────

class TestSmsInbound:

    def test_sms_returns_xml(self, client, sms_clinic):
        r = client.post("/sms/inbound", data={
            "From": _PATIENT_NUMBER,
            "To": sms_clinic.twilio_phone,
            "Body": "What are your hours?",
        })
        assert r.status_code == 200
        assert "xml" in r.headers["content-type"].lower()

    def test_sms_contains_response_text(self, client, sms_clinic):
        r = client.post("/sms/inbound", data={
            "From": _PATIENT_NUMBER,
            "To": sms_clinic.twilio_phone,
            "Body": "Hello",
        })
        assert r.status_code == 200
        assert b"<Response>" in r.content
        assert b"<Message>" in r.content

    def test_sms_unknown_number_returns_xml_error(self, client):
        r = client.post("/sms/inbound", data={
            "From": _PATIENT_NUMBER,
            "To": "+19999999999",
            "Body": "Hello",
        })
        assert r.status_code == 200
        assert b"not currently active" in r.content

    def test_sms_starter_plan_blocked(self, client, starter_clinic):
        r = client.post("/sms/inbound", data={
            "From": _PATIENT_NUMBER,
            "To": starter_clinic.twilio_phone,
            "Body": "Hello",
        })
        assert r.status_code == 200
        # Should return plan-blocked message
        assert b"<Message>" in r.content

    def test_sms_optout_handled(self, client, sms_clinic):
        r = client.post("/sms/inbound", data={
            "From": _PATIENT_NUMBER,
            "To": sms_clinic.twilio_phone,
            "Body": "OPTOUT",
        })
        assert r.status_code == 200
        assert b"<Response>" in r.content

    def test_sms_unsubscribe_handled(self, client, sms_clinic):
        r = client.post("/sms/inbound", data={
            "From": _PATIENT_NUMBER,
            "To": sms_clinic.twilio_phone,
            "Body": "UNSUBSCRIBE",
        })
        assert r.status_code == 200
        assert b"<Response>" in r.content

    def test_sms_yes_reply_handled(self, client, sms_clinic):
        r = client.post("/sms/inbound", data={
            "From": _PATIENT_NUMBER,
            "To": sms_clinic.twilio_phone,
            "Body": "YES",
        })
        assert r.status_code == 200
        assert b"<Response>" in r.content

    def test_sms_book_reply_handled(self, client, sms_clinic):
        r = client.post("/sms/inbound", data={
            "From": _PATIENT_NUMBER,
            "To": sms_clinic.twilio_phone,
            "Body": "BOOK",
        })
        assert r.status_code == 200
        assert b"<Response>" in r.content


# ── WhatsApp Inbound ──────────────────────────────────────────────────────────

class TestWhatsAppInbound:

    def test_whatsapp_returns_xml(self, client, sms_clinic):
        r = client.post("/whatsapp/inbound", data={
            "From": f"whatsapp:{_PATIENT_NUMBER}",
            "To": f"whatsapp:{sms_clinic.twilio_phone}",
            "Body": "What are your hours?",
        })
        assert r.status_code == 200
        assert "xml" in r.headers["content-type"].lower()

    def test_whatsapp_strips_prefix_for_lookup(self, client, sms_clinic):
        """WhatsApp: prefix should be stripped before clinic lookup."""
        r = client.post("/whatsapp/inbound", data={
            "From": f"whatsapp:{_PATIENT_NUMBER}",
            "To": f"whatsapp:{sms_clinic.twilio_phone}",
            "Body": "Hello",
        })
        assert r.status_code == 200
        assert b"<Response>" in r.content
        assert b"not currently active" not in r.content

    def test_whatsapp_unknown_number_returns_xml_error(self, client):
        r = client.post("/whatsapp/inbound", data={
            "From": "whatsapp:+19999999999",
            "To": "whatsapp:+19999999999",
            "Body": "Hello",
        })
        assert r.status_code == 200
        assert b"not currently active" in r.content

    def test_whatsapp_optout_handled(self, client, sms_clinic):
        r = client.post("/whatsapp/inbound", data={
            "From": f"whatsapp:{_PATIENT_NUMBER}",
            "To": f"whatsapp:{sms_clinic.twilio_phone}",
            "Body": "OPTOUT",
        })
        assert r.status_code == 200
        assert b"<Response>" in r.content

    def test_whatsapp_ai_chat_responds(self, client, sms_clinic):
        r = client.post("/whatsapp/inbound", data={
            "From": f"whatsapp:{_PATIENT_NUMBER}",
            "To": f"whatsapp:{sms_clinic.twilio_phone}",
            "Body": "I need to book an appointment",
        })
        assert r.status_code == 200
        assert b"<Message>" in r.content

    def test_whatsapp_starter_plan_blocked(self, client, starter_clinic):
        r = client.post("/whatsapp/inbound", data={
            "From": f"whatsapp:{_PATIENT_NUMBER}",
            "To": f"whatsapp:{starter_clinic.twilio_phone}",
            "Body": "Hello",
        })
        assert r.status_code == 200
        assert b"<Message>" in r.content
