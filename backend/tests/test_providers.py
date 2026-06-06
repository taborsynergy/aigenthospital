"""Provider/Doctor management tests — multi-doctor practice (Growth+ plan)."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_providers.db")
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
from backend.plans import can_add_provider, max_providers


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


_test_counter = 0


@pytest.fixture
def starter_clinic(db, request):
    """Starter plan clinic (max 1 provider)."""
    global _test_counter
    _test_counter += 1
    slug = f"starter-prov-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Starter Provider Test {_test_counter}",
        specialty="Family Medicine",
        email=f"{slug}@test.com",
        subscription_status="active",
        plan="starter",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    # Clean up: delete providers then clinic
    from backend.db.models import Provider
    db.query(Provider).filter(Provider.clinic_id == c.id).delete()
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def growth_clinic(db, request):
    """Growth plan clinic (max 5 providers)."""
    global _test_counter
    _test_counter += 1
    slug = f"growth-prov-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Growth Provider Test {_test_counter}",
        specialty="Pediatrics",
        email=f"{slug}@test.com",
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
    # Clean up: delete providers then clinic
    from backend.db.models import Provider
    db.query(Provider).filter(Provider.clinic_id == c.id).delete()
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def enterprise_clinic(db, request):
    """Enterprise plan clinic (unlimited providers)."""
    global _test_counter
    _test_counter += 1
    slug = f"ent-prov-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Enterprise Provider Test {_test_counter}",
        specialty="Oncology",
        email=f"{slug}@test.com",
        subscription_status="active",
        plan="enterprise",
        customer_password_hash=hash_password("testpass123"),
        is_active=True,
        subscription_ends_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c
    # Clean up: delete providers then clinic
    from backend.db.models import Provider
    db.query(Provider).filter(Provider.clinic_id == c.id).delete()
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def starter_token(client, starter_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": starter_clinic.email,
        "password": "testpass123"
    })
    return r.json()["token"]


@pytest.fixture
def growth_token(client, growth_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": growth_clinic.email,
        "password": "testpass123"
    })
    return r.json()["token"]


@pytest.fixture
def enterprise_token(client, enterprise_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": enterprise_clinic.email,
        "password": "testpass123"
    })
    return r.json()["token"]


@pytest.fixture
def db():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = S()
    try:
        yield s
    finally:
        s.close()


class TestProviderCRUD:
    """Test provider CRUD operations."""

    def test_create_provider(self, client, growth_clinic, growth_token):
        """POST /api/{clinic}/providers creates a provider."""
        r = client.post(
            f"/api/{growth_clinic.slug}/providers",
            json={
                "name": "Dr. Jane Smith",
                "email": "jane@clinic.com",
                "phone": "(555) 555-5555",
                "specialty": "Pediatrics",
                "license_number": "123456",
                "npi_number": "9876543210",
            },
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Dr. Jane Smith"
        assert data["email"] == "jane@clinic.com"
        assert data["specialty"] == "Pediatrics"

    def test_list_providers(self, client, growth_clinic, growth_token):
        """GET /api/{clinic}/providers lists all providers."""
        # Create 2 providers
        for i in range(2):
            client.post(
                f"/api/{growth_clinic.slug}/providers",
                json={
                    "name": f"Dr. Provider {i}",
                    "email": f"provider{i}@clinic.com",
                    "specialty": "General",
                },
                headers={"X-Clinic-Token": growth_token}
            )

        r = client.get(
            f"/api/{growth_clinic.slug}/providers",
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 2
        assert any(p["name"] == "Dr. Provider 0" for p in data["providers"])

    def test_get_provider(self, client, growth_clinic, growth_token):
        """GET /api/{clinic}/providers/{id} gets a single provider."""
        # Create provider
        create_r = client.post(
            f"/api/{growth_clinic.slug}/providers",
            json={
                "name": "Dr. John Doe",
                "email": "john@clinic.com",
                "specialty": "Cardiology",
            },
            headers={"X-Clinic-Token": growth_token}
        )
        provider_id = create_r.json()["id"]

        # Get provider
        r = client.get(
            f"/api/{growth_clinic.slug}/providers/{provider_id}",
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Dr. John Doe"

    def test_update_provider(self, client, growth_clinic, growth_token):
        """PATCH /api/{clinic}/providers/{id} updates provider."""
        # Create provider
        create_r = client.post(
            f"/api/{growth_clinic.slug}/providers",
            json={
                "name": "Dr. Original Name",
                "email": "original@clinic.com",
                "specialty": "General",
            },
            headers={"X-Clinic-Token": growth_token}
        )
        provider_id = create_r.json()["id"]

        # Update provider
        r = client.patch(
            f"/api/{growth_clinic.slug}/providers/{provider_id}",
            json={
                "name": "Dr. Updated Name",
                "specialty": "Pediatrics",
            },
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Dr. Updated Name"
        assert data["specialty"] == "Pediatrics"

    def test_delete_provider(self, client, growth_clinic, growth_token):
        """DELETE /api/{clinic}/providers/{id} deactivates provider."""
        # Create provider
        create_r = client.post(
            f"/api/{growth_clinic.slug}/providers",
            json={
                "name": "Dr. To Delete",
                "email": "delete@clinic.com",
            },
            headers={"X-Clinic-Token": growth_token}
        )
        provider_id = create_r.json()["id"]

        # Delete provider
        r = client.delete(
            f"/api/{growth_clinic.slug}/providers/{provider_id}",
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 200
        assert r.json()["deleted"] is True

        # Verify deleted (not in list)
        list_r = client.get(
            f"/api/{growth_clinic.slug}/providers",
            headers={"X-Clinic-Token": growth_token}
        )
        provider_ids = [p["id"] for p in list_r.json()["providers"]]
        assert provider_id not in provider_ids


class TestProviderLimit:
    """Test plan-based provider limits."""

    def test_starter_max_one_provider(self, client, starter_clinic, starter_token):
        """Starter plan limited to 1 provider."""
        # Create first provider
        r1 = client.post(
            f"/api/{starter_clinic.slug}/providers",
            json={"name": "Dr. First", "email": "first@clinic.com"},
            headers={"X-Clinic-Token": starter_token}
        )
        assert r1.status_code == 200

        # Try to create second provider
        r2 = client.post(
            f"/api/{starter_clinic.slug}/providers",
            json={"name": "Dr. Second", "email": "second@clinic.com"},
            headers={"X-Clinic-Token": starter_token}
        )
        assert r2.status_code == 400
        assert "limit" in r2.json()["error"].lower()

    def test_growth_max_five_providers(self, client, growth_clinic, growth_token):
        """Growth plan limited to 5 providers."""
        # Create 5 providers
        for i in range(5):
            r = client.post(
                f"/api/{growth_clinic.slug}/providers",
                json={
                    "name": f"Dr. Provider {i}",
                    "email": f"provider{i}@clinic.com",
                },
                headers={"X-Clinic-Token": growth_token}
            )
            assert r.status_code == 200

        # Try to create 6th provider
        r = client.post(
            f"/api/{growth_clinic.slug}/providers",
            json={"name": "Dr. Sixth", "email": "sixth@clinic.com"},
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 400
        assert "5" in r.json()["error"] or "limit" in r.json()["error"].lower()

    def test_enterprise_unlimited_providers(self, client, enterprise_clinic, enterprise_token):
        """Enterprise plan unlimited providers."""
        # Create 10 providers
        for i in range(10):
            r = client.post(
                f"/api/{enterprise_clinic.slug}/providers",
                json={
                    "name": f"Dr. Enterprise {i}",
                    "email": f"ent{i}@clinic.com",
                },
                headers={"X-Clinic-Token": enterprise_token}
            )
            assert r.status_code == 200

        # Verify all created
        list_r = client.get(
            f"/api/{enterprise_clinic.slug}/providers",
            headers={"X-Clinic-Token": enterprise_token}
        )
        assert list_r.json()["count"] == 10


class TestProviderValidation:
    """Test provider input validation."""

    def test_create_without_name(self, client, growth_clinic, growth_token):
        """Creating provider without name rejected."""
        r = client.post(
            f"/api/{growth_clinic.slug}/providers",
            json={"email": "noprov@clinic.com"},
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 400

    def test_get_nonexistent_provider(self, client, growth_clinic, growth_token):
        """Get nonexistent provider returns 404."""
        r = client.get(
            f"/api/{growth_clinic.slug}/providers/9999",
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 404

    def test_delete_nonexistent_provider(self, client, growth_clinic, growth_token):
        """Delete nonexistent provider returns 404."""
        r = client.delete(
            f"/api/{growth_clinic.slug}/providers/9999",
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 404


class TestProviderClinicIsolation:
    """Test clinic isolation for providers."""

    def test_cannot_access_other_clinic_providers(self, client, growth_clinic, starter_clinic, growth_token):
        """Cannot access providers from other clinic."""
        # Create provider in growth clinic
        r = client.post(
            f"/api/{growth_clinic.slug}/providers",
            json={"name": "Dr. Growth", "email": "growth@clinic.com"},
            headers={"X-Clinic-Token": growth_token}
        )
        provider_id = r.json()["id"]

        # Try to access with starter clinic token
        starter_token = client.post("/api/clinic-auth/login", json={
            "email": starter_clinic.email,
            "password": "testpass123"
        }).json()["token"]

        r = client.get(
            f"/api/{starter_clinic.slug}/providers/{provider_id}",
            headers={"X-Clinic-Token": starter_token}
        )
        assert r.status_code == 404


class TestPlanHelper:
    """Test plan-based provider limit helpers."""

    def test_max_providers_starter(self, starter_clinic):
        """Starter plan max_providers = 1."""
        assert max_providers(starter_clinic) == 1

    def test_max_providers_growth(self, growth_clinic):
        """Growth plan max_providers = 5."""
        assert max_providers(growth_clinic) == 5

    def test_max_providers_enterprise(self, enterprise_clinic):
        """Enterprise plan max_providers = unlimited."""
        assert max_providers(enterprise_clinic) is None

    def test_can_add_provider_under_limit(self, growth_clinic):
        """can_add_provider returns True when under limit."""
        assert can_add_provider(growth_clinic, 0) is True
        assert can_add_provider(growth_clinic, 4) is True

    def test_can_add_provider_at_limit(self, growth_clinic):
        """can_add_provider returns False when at limit."""
        assert can_add_provider(growth_clinic, 5) is False

    def test_can_add_provider_enterprise(self, enterprise_clinic):
        """Enterprise can always add providers."""
        assert can_add_provider(enterprise_clinic, 0) is True
        assert can_add_provider(enterprise_clinic, 100) is True
