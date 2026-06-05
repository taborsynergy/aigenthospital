"""
Multi-location management tests.
Covers: location CRUD, duplicate prevention, clinic isolation.
"""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_locations.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Location
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
    slug = "locations-test"
    c = Clinic(
        slug=slug, name="Multi-Location Clinic", specialty="Family Medicine",
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
    db.query(Location).filter(Location.clinic_id == c.id).delete()
    db.delete(c)
    db.commit()


@pytest.fixture
def auth_token(client, clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


class TestLocationCRUD:
    def test_create_location(self, client, clinic, auth_token):
        r = client.post(f"/api/{clinic.slug}/locations",
                        json={"name": "Main Office", "phone": "555-0001"},
                        headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Main Office"
        assert data["phone"] == "555-0001"

    def test_list_locations(self, client, clinic, auth_token, db):
        # Create 2 locations
        from backend.db.crud import create_location
        create_location(db, {"clinic_id": clinic.id, "name": "Loc1"})
        create_location(db, {"clinic_id": clinic.id, "name": "Loc2"})

        r = client.get(f"/api/{clinic.slug}/locations",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert len(r.json()) >= 2

    def test_get_location(self, client, clinic, auth_token, db):
        from backend.db.crud import create_location
        loc = create_location(db, {"clinic_id": clinic.id, "name": "Downtown"})

        r = client.get(f"/api/{clinic.slug}/locations/{loc.id}",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert r.json()["name"] == "Downtown"

    def test_update_location(self, client, clinic, auth_token, db):
        from backend.db.crud import create_location
        loc = create_location(db, {"clinic_id": clinic.id, "name": "Uptown"})

        r = client.patch(f"/api/{clinic.slug}/locations/{loc.id}",
                         json={"phone": "555-9999"},
                         headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200
        assert r.json()["phone"] == "555-9999"

    def test_delete_location(self, client, clinic, auth_token, db):
        from backend.db.crud import create_location
        loc = create_location(db, {"clinic_id": clinic.id, "name": "West End"})

        r = client.delete(f"/api/{clinic.slug}/locations/{loc.id}",
                          headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 200

        # Verify soft-delete (is_active = False)
        db.refresh(loc)
        assert loc.is_active is False

    def test_duplicate_name_rejected(self, client, clinic, auth_token):
        # Create first location
        r1 = client.post(f"/api/{clinic.slug}/locations",
                         json={"name": "Main"},
                         headers={"X-Clinic-Token": auth_token})
        assert r1.status_code == 200

        # Try to create duplicate
        r2 = client.post(f"/api/{clinic.slug}/locations",
                         json={"name": "Main"},
                         headers={"X-Clinic-Token": auth_token})
        assert r2.status_code == 400

    def test_requires_auth(self, client, clinic):
        r = client.get(f"/api/{clinic.slug}/locations")
        assert r.status_code == 403

    def test_clinic_isolation(self, client, clinic, auth_token, db):
        from backend.db.crud import create_location
        loc = create_location(db, {"clinic_id": clinic.id, "name": "Clinic1-Loc"})

        # Try to access with different clinic slug
        r = client.get(f"/api/other-clinic/locations/{loc.id}",
                       headers={"X-Clinic-Token": auth_token})
        assert r.status_code == 403
