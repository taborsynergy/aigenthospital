"""Widget customization tests."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_widget.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
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


@pytest.fixture
def clinic(db):
    slug = "widget-test"
    c = Clinic(
        slug=slug, name="Widget Test Clinic", specialty="Family Medicine",
        email=f"{slug}@test.com",
        subscription_status="active", plan="professional",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        trial_ends_at=datetime.utcnow() + timedelta(days=30),
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    db.delete(c)
    db.commit()


@pytest.fixture
def auth_token(client, clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


class TestWidget:
    def test_get_default_config(self, client, clinic, auth_token):
        r = client.get(f"/api/{clinic.slug}/widget/config",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        data = r.json()
        assert data["primary_color"] == "#007ACC"
        assert data["widget_title"] == "Book an Appointment"

    def test_update_config(self, client, clinic, auth_token):
        r = client.patch(f"/api/{clinic.slug}/widget/config",
                         json={"primary_color": "#FF0000"},
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert r.json()["primary_color"] == "#FF0000"

    def test_update_multiple_fields(self, client, clinic, auth_token):
        r = client.patch(f"/api/{clinic.slug}/widget/config",
                         json={
                             "logo_url": "https://example.com/logo.png",
                             "widget_title": "Schedule Visit",
                             "show_ratings": False,
                         },
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        data = r.json()
        assert data["logo_url"] == "https://example.com/logo.png"
        assert data["widget_title"] == "Schedule Visit"
        assert data["show_ratings"] is False

    def test_requires_auth(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/widget/config")
        assert r.status_code == 403

    def test_clinic_isolation(self, client, clinic, auth_token):
        r = client.get("/api/other-clinic/widget/config",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 403
