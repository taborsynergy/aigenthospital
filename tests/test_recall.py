"""
Patient Recall Campaign tests.
Covers: campaign CRUD, preview logic, send deduplication, opt-out,
BOOK/OPTOUT SMS reply handling, and API endpoints.
"""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_recall.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, RecallCampaign, RecallLog
from backend.routers.clinic_auth import hash_password


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


def _make_clinic(db, slug, plan="professional"):
    existing = db.query(Clinic).filter(Clinic.slug == slug).first()
    if existing:
        return existing
    c = Clinic(
        slug=slug, name=f"Clinic {slug}", specialty="Family Medicine",
        email=f"{slug}@test.com", phone="5550001111",
        twilio_phone="+15559998888",
        subscription_status="active", plan=plan,
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        trial_ends_at=datetime.utcnow() + timedelta(days=30),
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_appt(db, clinic, months_ago: float, phone="+15551234567",
               status="completed") -> Appointment:
    import uuid
    ts = datetime.utcnow() - timedelta(days=months_ago * 30)
    appt = Appointment(
        clinic_id=clinic.id,
        confirmation_number=f"RCLL-{uuid.uuid4().hex[:6].upper()}",
        patient_name="Recall Patient",
        patient_phone=phone,
        appointment_type="Annual Physical",
        appointment_datetime="January 1 at 9:00 AM",
        appointment_ts=ts,
        status=status,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


def _make_campaign(db, clinic, interval_months=6) -> RecallCampaign:
    from backend.db.crud import create_recall_campaign
    return create_recall_campaign(db, {
        "clinic_id":       clinic.id,
        "name":            "Annual Recall",
        "visit_type":      "annual physical",
        "interval_months": interval_months,
        "is_active":       True,
    })


@pytest.fixture
def pro_clinic(db):
    c = _make_clinic(db, "recall-pro-clinic")
    yield c
    db.query(RecallLog).filter(RecallLog.clinic_id == c.id).delete()
    db.query(RecallCampaign).filter(RecallCampaign.clinic_id == c.id).delete()
    db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
    db.delete(c)
    db.commit()


@pytest.fixture
def starter_clinic(db):
    c = _make_clinic(db, "recall-starter-clinic", plan="starter")
    yield c
    db.query(RecallLog).filter(RecallLog.clinic_id == c.id).delete()
    db.query(RecallCampaign).filter(RecallCampaign.clinic_id == c.id).delete()
    db.query(Appointment).filter(Appointment.clinic_id == c.id).delete()
    db.delete(c)
    db.commit()


@pytest.fixture
def auth_token(client, pro_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": pro_clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


# ── Campaign CRUD ─────────────────────────────────────────────────────────────

class TestCampaignCRUD:
    def test_create_campaign(self, client, pro_clinic, auth_token):
        r = client.post(f"/api/{pro_clinic.slug}/recall-campaigns",
                        json={"name": "Annual Checkup", "visit_type": "annual physical",
                              "interval_months": 12},
                        headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Annual Checkup"
        assert data["interval_months"] == 12

    def test_list_campaigns(self, client, pro_clinic, auth_token, db):
        _make_campaign(db, pro_clinic)
        r = client.get(f"/api/{pro_clinic.slug}/recall-campaigns",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_update_campaign(self, client, pro_clinic, auth_token, db):
        campaign = _make_campaign(db, pro_clinic)
        r = client.patch(f"/api/{pro_clinic.slug}/recall-campaigns/{campaign.id}",
                         json={"interval_months": 6},
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert r.json()["interval_months"] == 6

    def test_delete_campaign(self, client, pro_clinic, auth_token, db):
        campaign = _make_campaign(db, pro_clinic)
        r = client.delete(f"/api/{pro_clinic.slug}/recall-campaigns/{campaign.id}",
                          headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_create_requires_auth(self, client, pro_clinic):
        r = client.post(f"/api/{pro_clinic.slug}/recall-campaigns",
                        json={"name": "Test", "visit_type": "checkup"})
        assert r.status_code == 403

    def test_invalid_interval_rejected(self, client, pro_clinic, auth_token):
        r = client.post(f"/api/{pro_clinic.slug}/recall-campaigns",
                        json={"name": "Bad", "visit_type": "checkup", "interval_months": 99},
                        headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 400


# ── Recall logic ──────────────────────────────────────────────────────────────

class TestRecallLogic:
    def test_overdue_patient_found(self, db, pro_clinic):
        from backend.db.crud import find_patients_due_for_recall
        _make_appt(db, pro_clinic, months_ago=14, phone="+15550010001")
        due = find_patients_due_for_recall(db, pro_clinic.id, interval_months=12)
        phones = [p["patient_phone"] for p in due]
        assert "+15550010001" in phones

    def test_recent_patient_not_due(self, db, pro_clinic):
        from backend.db.crud import find_patients_due_for_recall
        _make_appt(db, pro_clinic, months_ago=3, phone="+15550010002")
        due = find_patients_due_for_recall(db, pro_clinic.id, interval_months=12)
        phones = [p["patient_phone"] for p in due]
        assert "+15550010002" not in phones

    def test_no_phone_excluded(self, db, pro_clinic):
        from backend.db.crud import find_patients_due_for_recall
        _make_appt(db, pro_clinic, months_ago=14, phone="")
        due = find_patients_due_for_recall(db, pro_clinic.id, interval_months=12)
        assert all(p["patient_phone"] for p in due)

    def test_opted_out_excluded_from_preview(self, db, pro_clinic):
        from backend.services.recall_svc import preview_campaign
        from backend.db.crud import mark_recall_opted_out
        phone = "+15550020001"
        _make_appt(db, pro_clinic, months_ago=14, phone=phone)
        campaign = _make_campaign(db, pro_clinic, interval_months=12)
        mark_recall_opted_out(db, pro_clinic.id, phone)
        patients = preview_campaign(db, pro_clinic.id, campaign)
        phones = [p["patient_phone"] for p in patients]
        assert phone not in phones

    def test_already_recalled_excluded(self, db, pro_clinic):
        from backend.services.recall_svc import preview_campaign
        from backend.db.crud import log_recall_sent
        phone = "+15550020002"
        _make_appt(db, pro_clinic, months_ago=14, phone=phone)
        campaign = _make_campaign(db, pro_clinic, interval_months=12)
        log_recall_sent(db, campaign.id, pro_clinic.id, "Recall Patient", phone, "sent")
        patients = preview_campaign(db, pro_clinic.id, campaign)
        phones = [p["patient_phone"] for p in patients]
        assert phone not in phones


# ── Message template rendering ────────────────────────────────────────────────

class TestMessageTemplate:
    def test_default_template(self):
        from backend.services.recall_svc import _render_message, DEFAULT_TEMPLATE
        msg = _render_message(DEFAULT_TEMPLATE, "Jane Smith", "Sunshine Clinic",
                              "annual physical", "555-1234")
        assert "Jane" in msg
        assert "Sunshine Clinic" in msg
        assert "annual physical" in msg
        assert "BOOK" in msg

    def test_custom_template(self):
        from backend.services.recall_svc import _render_message
        msg = _render_message(
            "Hi {first_name}, time for your {visit_type} at {clinic_name}!",
            "Robert Johnson", "City Derm", "skin check",
        )
        assert msg == "Hi Robert, time for your skin check at City Derm!"

    def test_first_name_extraction(self):
        from backend.services.recall_svc import _render_message, DEFAULT_TEMPLATE
        msg = _render_message(DEFAULT_TEMPLATE, "Mary Jane Watson", "Clinic", "checkup")
        assert "Mary" in msg
        assert "Watson" not in msg


# ── SMS reply handling ────────────────────────────────────────────────────────

class TestSmsReplyHandling:
    def test_book_reply_returns_chat_link(self, db, pro_clinic):
        from backend.services.recall_svc import handle_book_reply
        from backend.db.crud import log_recall_sent
        campaign = _make_campaign(db, pro_clinic)
        log_recall_sent(db, campaign.id, pro_clinic.id,
                        "Test Patient", "+15550030001", "sent")
        reply = handle_book_reply(db, pro_clinic, "+15550030001")
        assert reply is not None
        assert "book" in reply.lower() or "/chat/" in reply or pro_clinic.slug in reply

    def test_optout_marks_patient(self, db, pro_clinic):
        from backend.services.recall_svc import handle_optout
        from backend.db.crud import is_opted_out
        handle_optout(db, pro_clinic.id, "+15550040001")
        assert is_opted_out(db, pro_clinic.id, "+15550040001") is True

    def test_optout_reply_message(self, db, pro_clinic):
        from backend.services.recall_svc import handle_optout
        reply = handle_optout(db, pro_clinic.id, "+15550040002")
        assert "unsubscribed" in reply.lower()


# ── API: trigger + plan gating ────────────────────────────────────────────────

class TestRecallApiEndpoints:
    def test_trigger_requires_admin(self, client):
        r = client.post("/api/recall/trigger")
        assert r.status_code == 401

    def test_trigger_runs_ok(self, client):
        r = client.post("/api/recall/trigger",
                        headers={"X-Admin-Password": "test-admin-secret"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_manual_run_blocked_on_starter(self, client, starter_clinic, db):
        login = client.post("/api/clinic-auth/login", json={
            "email": starter_clinic.email, "password": "testpass123"
        })
        token = login.json()["token"]
        campaign = _make_campaign(db, starter_clinic)
        r = client.post(f"/api/{starter_clinic.slug}/recall-campaigns/{campaign.id}/run",
                        headers={"X-Clinic-Token": token})
        assert r.status_code == 403

    def test_preview_endpoint(self, client, pro_clinic, auth_token, db):
        _make_appt(db, pro_clinic, months_ago=14, phone="+15550050001")
        campaign = _make_campaign(db, pro_clinic, interval_months=12)
        r = client.get(
            f"/api/{pro_clinic.slug}/recall-campaigns/{campaign.id}/preview",
            headers={"X-Clinic-Token": auth_token},
        )
        assert r.status_code == 200
        data = r.json()
        assert "patient_count" in data
        assert "patients" in data
        # Phone should be masked
        for p in data["patients"]:
            assert "****" in p["patient_phone"]
