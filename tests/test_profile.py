"""
Clinic profile self-edit tests.
Covers: field validation, GET/PATCH endpoints, audit logging, permission checks.
"""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_profile.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, AuditLog
from backend.routers.clinic_auth import hash_password
from backend.schemas import ClinicProfileUpdate


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
def profile_clinic(db):
    """Test clinic for profile editing."""
    slug = "profile-test-clinic"
    existing = db.query(Clinic).filter(Clinic.slug == slug).first()
    if existing:
        yield existing
        return
    c = Clinic(
        slug=slug,
        name="Original Clinic Name",
        specialty="Family Medicine",
        email=f"{slug}@test.com",
        phone="555-0001",
        address="100 Main St",
        city_state="Springfield, IL",
        website="https://example.com",
        office_hours="Mon-Fri 8am-5pm",
        subscription_status="active",
        plan="professional",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        trial_ends_at=datetime.utcnow() + timedelta(days=30),
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.query(AuditLog).filter(AuditLog.target == slug).delete()
    db.delete(c)
    db.commit()


@pytest.fixture
def auth_token(client, profile_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": profile_clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


# ── Pydantic validation ───────────────────────────────────────────────────────

class TestProfileValidation:
    def test_name_too_short(self):
        with pytest.raises(ValueError):
            ClinicProfileUpdate(name="A")

    def test_name_too_long(self):
        with pytest.raises(ValueError):
            ClinicProfileUpdate(name="X" * 101)

    def test_name_valid(self):
        p = ClinicProfileUpdate(name="Valid Clinic")
        assert p.name == "Valid Clinic"

    def test_phone_format(self):
        # Valid formats
        ClinicProfileUpdate(phone="555-1234567")  # 10 digits
        ClinicProfileUpdate(phone="(555) 123-4567")
        ClinicProfileUpdate(phone="+1-555-123-4567")

    def test_phone_too_short(self):
        with pytest.raises(ValueError):
            ClinicProfileUpdate(phone="123")

    def test_website_must_have_protocol(self):
        with pytest.raises(ValueError):
            ClinicProfileUpdate(website="example.com")

    def test_website_valid(self):
        ClinicProfileUpdate(website="https://example.com")
        ClinicProfileUpdate(website="http://example.com")

    def test_office_hours_format(self):
        ClinicProfileUpdate(office_hours="Mon-Fri 8am-5pm")
        ClinicProfileUpdate(office_hours="9:00am - 5:00pm")

    def test_office_hours_invalid(self):
        with pytest.raises(ValueError):
            ClinicProfileUpdate(office_hours="xyz")

    def test_timezone_valid(self):
        ClinicProfileUpdate(timezone="US/Eastern")
        ClinicProfileUpdate(timezone="UTC")

    def test_timezone_invalid(self):
        with pytest.raises(ValueError):
            ClinicProfileUpdate(timezone="Invalid/Zone")

    def test_text_field_too_long(self):
        with pytest.raises(ValueError):
            ClinicProfileUpdate(cancellation_policy="X" * 501)

    def test_multiple_fields(self):
        p = ClinicProfileUpdate(
            name="New Name",
            phone="555-1234567",
            office_hours="Mon-Fri 9am-6pm",
        )
        assert p.name == "New Name"
        assert p.phone == "555-1234567"
        assert p.office_hours == "Mon-Fri 9am-6pm"


# ── GET /api/{slug}/profile ───────────────────────────────────────────────────

class TestGetProfile:
    def test_requires_auth(self, client, profile_clinic):
        r = client.get(f"/api/{profile_clinic.slug}/profile")
        assert r.status_code == 403

    def test_returns_current_profile(self, client, profile_clinic, auth_token):
        r = client.get(f"/api/{profile_clinic.slug}/profile",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Original Clinic Name"
        assert data["phone"] == "555-0001"
        assert data["specialty"] == "Family Medicine"

    def test_wrong_clinic_slug_forbidden(self, client, profile_clinic, auth_token):
        r = client.get("/api/other-clinic/profile",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 403


# ── PATCH /api/{slug}/profile ────────────────────────────────────────────────

class TestUpdateProfile:
    def test_requires_auth(self, client, profile_clinic):
        r = client.patch(f"/api/{profile_clinic.slug}/profile",
                         json={"name": "New Name"})
        assert r.status_code == 403

    def test_update_single_field(self, client, profile_clinic, auth_token, db):
        r = client.patch(f"/api/{profile_clinic.slug}/profile",
                         json={"name": "Updated Clinic Name"},
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verify in DB
        db.refresh(profile_clinic)
        assert profile_clinic.name == "Updated Clinic Name"
        assert profile_clinic.phone == "555-0001"  # unchanged

    def test_update_two_fields(self, client, profile_clinic, auth_token, db):
        r = client.patch(f"/api/{profile_clinic.slug}/profile",
                         json={
                             "name": "New Name",
                             "address": "999 Oak St",
                         },
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert len(r.json()["updated_fields"]) == 2

        db.refresh(profile_clinic)
        assert profile_clinic.name == "New Name"
        assert profile_clinic.address == "999 Oak St"

    def test_empty_update_rejected(self, client, profile_clinic, auth_token):
        r = client.patch(f"/api/{profile_clinic.slug}/profile",
                         json={},
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 400

    def test_validation_on_update(self, client, profile_clinic, auth_token):
        r = client.patch(f"/api/{profile_clinic.slug}/profile",
                         json={"phone": "123"},  # too short
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 422  # validation error

    def test_null_values_ignored(self, client, profile_clinic, auth_token, db):
        original_phone = profile_clinic.phone
        r = client.patch(f"/api/{profile_clinic.slug}/profile",
                         json={"name": "New Name", "phone": None},
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert "phone" not in r.json()["updated_fields"]  # null not applied

        db.refresh(profile_clinic)
        assert profile_clinic.phone == original_phone

    def test_wrong_clinic_forbidden(self, client, profile_clinic, auth_token):
        r = client.patch("/api/other-clinic/profile",
                         json={"name": "Hacked"},
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 403


# ── Audit logging ─────────────────────────────────────────────────────────────

class TestProfileAuditLog:
    def test_profile_change_logged(self, client, profile_clinic, auth_token, db):
        client.patch(f"/api/{profile_clinic.slug}/profile",
                     json={"name": "Audited Name"},
                     headers={"X-Clinic-Token": auth_token})

        # Check audit log
        logs = db.query(AuditLog).filter(
            AuditLog.target == profile_clinic.slug,
            AuditLog.action == "clinic.profile_updated",
        ).all()
        assert len(logs) >= 1
        latest = logs[-1]
        assert latest.actor == f"clinic:{profile_clinic.slug}"
        assert "name" in latest.detail  # diff should contain field name

    def test_multiple_changes_single_log(self, client, profile_clinic, auth_token, db):
        import json as json_lib

        r = client.patch(f"/api/{profile_clinic.slug}/profile",
                         json={"name": "N1"},
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200

        logs = db.query(AuditLog).filter(
            AuditLog.target == profile_clinic.slug,
            AuditLog.action == "clinic.profile_updated",
        ).order_by(AuditLog.created_at.desc()).limit(1).all()

        assert len(logs) == 1
        diff = json_lib.loads(logs[0].detail)
        assert "name" in diff


# ── Field-specific tests ──────────────────────────────────────────────────────

class TestProfileFields:
    def test_update_specialty(self, client, profile_clinic, auth_token, db):
        client.patch(f"/api/{profile_clinic.slug}/profile",
                     json={"specialty": "Dermatology"},
                     headers={"X-Clinic-Token": auth_token})
        db.refresh(profile_clinic)
        assert profile_clinic.specialty == "Dermatology"

    def test_update_address(self, client, profile_clinic, auth_token, db):
        client.patch(f"/api/{profile_clinic.slug}/profile",
                     json={"address": "456 Oak Ave"},
                     headers={"X-Clinic-Token": auth_token})
        db.refresh(profile_clinic)
        assert profile_clinic.address == "456 Oak Ave"

    def test_update_timezone(self, client, profile_clinic, auth_token, db):
        client.patch(f"/api/{profile_clinic.slug}/profile",
                     json={"timezone": "US/Pacific"},
                     headers={"X-Clinic-Token": auth_token})
        db.refresh(profile_clinic)
        assert profile_clinic.timezone == "US/Pacific"

    def test_update_providers(self, client, profile_clinic, auth_token, db):
        client.patch(f"/api/{profile_clinic.slug}/profile",
                     json={"providers": "Dr. Smith, Dr. Jones, Nurse Practitioner Lee"},
                     headers={"X-Clinic-Token": auth_token})
        db.refresh(profile_clinic)
        assert "Dr. Smith" in profile_clinic.providers
