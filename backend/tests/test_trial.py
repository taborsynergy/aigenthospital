"""Trial system tests — signup, expiry, conversion to paid."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_trial.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.db import crud
from backend.plans import is_clinic_active, get_access_status


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


class TestTrialSignup:
    """Test trial signup flow."""

    def test_signup_creates_trial_clinic(self, client):
        """POST /api/clinic-auth/signup creates trial clinic."""
        r = client.post(
            "/api/clinic-auth/signup",
            json={
                "email": "test1@example.com",
                "slug": "test-clinic-1",
                "name": "Test Clinic 1",
                "specialty": "Family Medicine",
                "password": "SecurePass123!",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["subscription_status"] == "trial"
        assert data["slug"] == "test-clinic-1"
        assert "token" in data
        assert "trial_ends_at" in data

    def test_signup_invalid_email(self, client):
        """Signup rejects invalid email."""
        r = client.post(
            "/api/clinic-auth/signup",
            json={
                "email": "notanemail",
                "slug": "test-clinic-2",
                "name": "Test Clinic",
                "specialty": "Pediatrics",
                "password": "SecurePass123!",
            },
        )
        assert r.status_code == 400
        assert "email" in r.json()["error"].lower()

    def test_signup_weak_password(self, client):
        """Signup rejects weak password."""
        r = client.post(
            "/api/clinic-auth/signup",
            json={
                "email": "test@example.com",
                "slug": "test-clinic-3",
                "name": "Test Clinic",
                "specialty": "Pediatrics",
                "password": "weak",
            },
        )
        assert r.status_code == 400
        assert "password" in r.json()["error"].lower()

    def test_signup_duplicate_email(self, client):
        """Signup rejects duplicate email."""
        email = "duplicate@example.com"
        # First signup
        client.post(
            "/api/clinic-auth/signup",
            json={
                "email": email,
                "slug": "first-clinic",
                "name": "First Clinic",
                "specialty": "Family Medicine",
                "password": "SecurePass123!",
            },
        )
        # Second signup with same email
        r = client.post(
            "/api/clinic-auth/signup",
            json={
                "email": email,
                "slug": "second-clinic",
                "name": "Second Clinic",
                "specialty": "Pediatrics",
                "password": "SecurePass123!",
            },
        )
        assert r.status_code == 400
        assert "already registered" in r.json()["error"].lower()

    def test_signup_duplicate_slug(self, client):
        """Signup rejects duplicate slug."""
        slug = "duplicate-slug"
        # First signup
        client.post(
            "/api/clinic-auth/signup",
            json={
                "email": "first@example.com",
                "slug": slug,
                "name": "First Clinic",
                "specialty": "Family Medicine",
                "password": "SecurePass123!",
            },
        )
        # Second signup with same slug
        r = client.post(
            "/api/clinic-auth/signup",
            json={
                "email": "second@example.com",
                "slug": slug,
                "name": "Second Clinic",
                "specialty": "Pediatrics",
                "password": "SecurePass123!",
            },
        )
        assert r.status_code == 400
        assert "already taken" in r.json()["error"].lower()


class TestTrialStatus:
    """Test trial status checking."""

    def test_trial_clinic_is_active(self, db):
        """New trial clinic is active."""
        clinic = crud.create_trial_clinic(
            db,
            email="active@example.com",
            slug="active-trial",
            name="Active Trial",
            specialty="Family Medicine",
            password_hash="hashed"
        )
        assert clinic is not None
        assert is_clinic_active(clinic)
        assert clinic.subscription_status == "trial"

    def test_trial_clinic_in_14_days(self, db):
        """Trial clinic with 14 days remaining is active."""
        clinic = crud.create_trial_clinic(
            db,
            email="14days@example.com",
            slug="14days-trial",
            name="14 Days Trial",
            specialty="Family Medicine",
            password_hash="hashed"
        )
        assert clinic.trial_ends_at is not None
        # Allow 13-14 days due to timing/rounding
        days_remaining = (clinic.trial_ends_at - datetime.utcnow()).days
        assert 13 <= days_remaining <= 14
        assert is_clinic_active(clinic)

    def test_trial_clinic_expired(self, db):
        """Expired trial clinic is not active."""
        clinic = crud.create_trial_clinic(
            db,
            email="expired@example.com",
            slug="expired-trial",
            name="Expired Trial",
            specialty="Family Medicine",
            password_hash="hashed"
        )
        # Manually expire the clinic
        clinic.trial_ends_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
        db.refresh(clinic)
        assert not is_clinic_active(clinic)

    def test_get_access_status(self, db):
        """Get detailed access status for clinic."""
        clinic = crud.create_trial_clinic(
            db,
            email="status@example.com",
            slug="status-trial",
            name="Status Trial",
            specialty="Family Medicine",
            password_hash="hashed"
        )
        status = get_access_status(clinic)
        assert status["active"] is True
        assert status["status"] == "trial"
        assert "days_remaining" in status


class TestTrialConversion:
    """Test trial-to-paid conversion."""

    def test_convert_trial_to_paid(self, db):
        """Convert trial to paid subscription."""
        clinic = crud.create_trial_clinic(
            db,
            email="convert@example.com",
            slug="convert-trial",
            name="Convert Trial",
            specialty="Family Medicine",
            password_hash="hashed"
        )
        assert clinic.subscription_status == "trial"
        assert clinic.trial_ends_at is not None

        # Convert to paid
        converted = crud.convert_trial_to_paid(
            db,
            clinic.id,
            plan="starter",
            stripe_subscription_id="sub_123",
            stripe_customer_id="cus_123"
        )

        assert converted.subscription_status == "active"
        assert converted.plan == "starter"
        assert converted.trial_ends_at is None
        assert converted.subscription_ends_at is not None
        assert converted.stripe_subscription_id == "sub_123"

    def test_convert_trial_to_professional(self, db):
        """Convert trial to Professional plan."""
        clinic = crud.create_trial_clinic(
            db,
            email="pro-convert@example.com",
            slug="pro-convert-trial",
            name="Pro Convert Trial",
            specialty="Family Medicine",
            password_hash="hashed"
        )

        converted = crud.convert_trial_to_paid(
            db,
            clinic.id,
            plan="professional"
        )

        assert converted.plan == "professional"
        assert converted.subscription_status == "active"


class TestTrialExpiry:
    """Test trial expiry checking."""

    def test_get_expired_trials(self, db):
        """Get all expired trial clinics."""
        # Create expired trial
        clinic = crud.create_trial_clinic(
            db,
            email="exp1@example.com",
            slug="exp1",
            name="Expired 1",
            specialty="Family Medicine",
            password_hash="hashed"
        )
        clinic.trial_ends_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()

        # Create active trial
        active = crud.create_trial_clinic(
            db,
            email="active1@example.com",
            slug="active1",
            name="Active 1",
            specialty="Pediatrics",
            password_hash="hashed"
        )

        # Get expired
        expired = crud.get_expired_trials(db)
        assert any(c.id == clinic.id for c in expired)
        assert not any(c.id == active.id for c in expired)

    def test_get_trials_expiring_soon(self, db):
        """Get trials expiring within 5 days."""
        # Create trial expiring in 3 days
        soon = crud.create_trial_clinic(
            db,
            email="soon@example.com",
            slug="soon-trial",
            name="Soon Trial",
            specialty="Family Medicine",
            password_hash="hashed"
        )
        soon.trial_ends_at = datetime.utcnow() + timedelta(days=3)
        db.commit()

        # Create trial expiring in 10 days (outside window)
        later = crud.create_trial_clinic(
            db,
            email="later@example.com",
            slug="later-trial",
            name="Later Trial",
            specialty="Pediatrics",
            password_hash="hashed"
        )
        later.trial_ends_at = datetime.utcnow() + timedelta(days=10)
        db.commit()

        # Get expiring soon
        expiring = crud.get_trials_expiring_soon(db, days_until=5)
        assert any(c.id == soon.id for c in expiring)
        assert not any(c.id == later.id for c in expiring)

    def test_expire_trial(self, db):
        """Expire a trial clinic."""
        clinic = crud.create_trial_clinic(
            db,
            email="expire-test@example.com",
            slug="expire-test",
            name="Expire Test",
            specialty="Family Medicine",
            password_hash="hashed"
        )
        assert clinic.subscription_status == "trial"

        # Expire it
        expired = crud.expire_trial(db, clinic.id)
        assert expired.subscription_status == "trial_expired"
        assert not is_clinic_active(expired)


class TestTrialLogin:
    """Test trial clinic login after signup."""

    def test_login_after_signup(self, client):
        """Can login immediately after signup."""
        # Signup
        signup_r = client.post(
            "/api/clinic-auth/signup",
            json={
                "email": "login-test@example.com",
                "slug": "login-test",
                "name": "Login Test",
                "specialty": "Family Medicine",
                "password": "SecurePass123!",
            },
        )
        assert signup_r.status_code == 200
        token = signup_r.json()["token"]

        # Login
        login_r = client.post(
            "/api/clinic-auth/login",
            json={
                "email": "login-test@example.com",
                "password": "SecurePass123!",
            },
        )
        assert login_r.status_code == 200
        assert login_r.json()["slug"] == "login-test"

    def test_login_with_invalid_password(self, client):
        """Login fails with invalid password."""
        # Signup
        client.post(
            "/api/clinic-auth/signup",
            json={
                "email": "invalidpass@example.com",
                "slug": "invalidpass",
                "name": "Invalid Pass",
                "specialty": "Family Medicine",
                "password": "SecurePass123!",
            },
        )

        # Try login with wrong password
        login_r = client.post(
            "/api/clinic-auth/login",
            json={
                "email": "invalidpass@example.com",
                "password": "WrongPassword!",
            },
        )
        assert login_r.status_code == 401

    def test_verify_token_after_signup(self, client):
        """Token verification works after signup."""
        signup_r = client.post(
            "/api/clinic-auth/signup",
            json={
                "email": "verify@example.com",
                "slug": "verify-clinic",
                "name": "Verify Clinic",
                "specialty": "Family Medicine",
                "password": "SecurePass123!",
            },
        )
        token = signup_r.json()["token"]

        # Verify token
        verify_r = client.get(
            "/api/clinic-auth/verify",
            headers={"X-Clinic-Token": token},
        )
        assert verify_r.status_code == 200
        assert verify_r.json()["status"] == "trial"
        assert verify_r.json()["slug"] == "verify-clinic"
