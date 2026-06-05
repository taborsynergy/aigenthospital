"""Multi-location routing tests."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_routing.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Location
from backend.db.crud import create_location
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
def enterprise_clinic(db):
    slug = "enterprise-test"
    c = Clinic(
        slug=slug, name="Enterprise Clinic", specialty="Family Medicine",
        email=f"{slug}@test.com",
        subscription_status="active", plan="enterprise",
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
def ent_token(client, enterprise_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": enterprise_clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


@pytest.fixture
def multi_location_clinic(db, enterprise_clinic):
    """Create a clinic with multiple locations for routing tests."""
    # Main office
    loc1 = create_location(db, {
        "clinic_id": enterprise_clinic.id,
        "name": "Main Office",
        "address": "123 Main St",
        "city_state": "San Francisco, CA",
        "phone": "415-555-0100",
        "zip_code_coverage": "94102,94103,94104",
        "service_categories": "General, Pediatrics",
        "is_primary": True,
    })
    # Downtown office
    loc2 = create_location(db, {
        "clinic_id": enterprise_clinic.id,
        "name": "Downtown Office",
        "address": "456 Market St",
        "city_state": "San Francisco, CA",
        "phone": "415-555-0200",
        "zip_code_coverage": "94105,94106,94107",
        "service_categories": "Urgent Care, General",
        "is_primary": False,
    })
    return [loc1, loc2]


class TestMultiLocationRouting:
    def test_routing_requires_pro_plan(self, client, enterprise_clinic, ent_token):
        """Verify routing is available on Pro/Enterprise plans."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/routing/test",
            params={"patient_zip": "94102"},
            headers={"X-Clinic-Token": ent_token}
        )
        # Should not be blocked (plan check passes)
        assert r.status_code in [200, 404]

    def test_route_by_zip_code(self, client, enterprise_clinic, ent_token, multi_location_clinic):
        """Route to location based on patient zip code."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/routing/test",
            params={"patient_zip": "94102"},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Main Office"  # Matches zip 94102

    def test_route_to_alternate_location(self, client, enterprise_clinic, ent_token, multi_location_clinic):
        """Route to different location based on zip code."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/routing/test",
            params={"patient_zip": "94105"},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Downtown Office"  # Matches zip 94105

    def test_route_by_service_type(self, client, enterprise_clinic, ent_token, multi_location_clinic):
        """Route based on appointment type/service category."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/routing/test",
            params={"appointment_type": "Urgent Care"},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Downtown Office"  # Has Urgent Care

    def test_route_combined_criteria(self, client, enterprise_clinic, ent_token, multi_location_clinic):
        """Route based on both zip code and service type."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/routing/test",
            params={"patient_zip": "94105", "appointment_type": "Urgent Care"},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Downtown Office"

    def test_update_routing_rules(self, client, enterprise_clinic, ent_token, multi_location_clinic):
        """Update zip code coverage and service categories."""
        loc_id = multi_location_clinic[0].id
        r = client.patch(
            f"/api/{enterprise_clinic.slug}/locations/{loc_id}/routing",
            json={
                "zip_code_coverage": "94102,94103,94104,94105",
                "service_categories": "General, Pediatrics, Urgent Care",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert "94105" in data["zip_code_coverage"]

    def test_set_primary_location(self, client, enterprise_clinic, ent_token, multi_location_clinic):
        """Set a location as primary/default."""
        loc_id = multi_location_clinic[1].id  # Downtown office
        r = client.post(
            f"/api/{enterprise_clinic.slug}/locations/{loc_id}/set-primary",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["primary_location"] == "Downtown Office"

    def test_fallback_to_primary(self, client, enterprise_clinic, ent_token, multi_location_clinic, db):
        """When no zip/service match, fall back to primary location."""
        from backend.db.crud import set_primary_location
        # Ensure Main Office is primary
        set_primary_location(db, enterprise_clinic.id, multi_location_clinic[0].id)

        r = client.post(
            f"/api/{enterprise_clinic.slug}/routing/test",
            params={"patient_zip": "00000"},  # No coverage match
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Main Office"  # Primary location
