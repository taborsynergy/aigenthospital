"""White label configuration tests — Enterprise feature for custom branding and reselling."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_whitelabel.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
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


_test_counter = 0


@pytest.fixture
def enterprise_clinic(db, request):
    """Enterprise plan clinic (has white label)."""
    global _test_counter
    _test_counter += 1
    slug = f"ent-wl-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Enterprise WL Test {_test_counter}",
        specialty="Family Medicine",
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
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def growth_clinic(db, request):
    """Growth clinic (no white label)."""
    global _test_counter
    _test_counter += 1
    slug = f"growth-wl-{_test_counter}"
    c = Clinic(
        slug=slug,
        name=f"Growth WL Test {_test_counter}",
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
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def ent_token(client, enterprise_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": enterprise_clinic.email,
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
def db():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = S()
    try:
        yield s
    finally:
        s.close()


class TestWhitelabelBranding:
    """Test white label branding customization."""

    def test_get_whitelabel_config(self, client, enterprise_clinic, ent_token):
        """GET /api/{clinic}/whitelabel returns config."""
        r = client.get(
            f"/api/{enterprise_clinic.slug}/whitelabel",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["primary_color"] == "#007ACC"
        assert data["remove_tabor_branding"] is False

    def test_growth_cannot_access_whitelabel(self, client, growth_clinic, growth_token):
        """Growth plan cannot access white label (403)."""
        r = client.get(
            f"/api/{growth_clinic.slug}/whitelabel",
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 403

    def test_update_branding_colors(self, client, enterprise_clinic, ent_token):
        """PATCH /api/{clinic}/whitelabel updates colors."""
        r = client.patch(
            f"/api/{enterprise_clinic.slug}/whitelabel",
            json={
                "primary_color": "#FF6B6B",
                "secondary_color": "#4ECDC4",
                "accent_color": "#FFE66D",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["primary_color"] == "#FF6B6B"
        assert data["secondary_color"] == "#4ECDC4"

    def test_update_logo_and_company_name(self, client, enterprise_clinic, ent_token):
        """Update logo URL and company name."""
        r = client.patch(
            f"/api/{enterprise_clinic.slug}/whitelabel",
            json={
                "logo_url": "https://example.com/logo.png",
                "company_name": "My Custom Clinic",
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["company_name"] == "My Custom Clinic"

    def test_remove_tabor_branding(self, client, enterprise_clinic, ent_token):
        """Remove Tabor branding from UI."""
        r = client.patch(
            f"/api/{enterprise_clinic.slug}/whitelabel",
            json={
                "remove_tabor_branding": True,
                "remove_powered_by": True,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["remove_tabor_branding"] is True

    def test_invalid_color_format(self, client, enterprise_clinic, ent_token):
        """Invalid hex color rejected."""
        r = client.patch(
            f"/api/{enterprise_clinic.slug}/whitelabel",
            json={"primary_color": "not-a-color"},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 400

    def test_update_custom_footer(self, client, enterprise_clinic, ent_token):
        """Update custom footer text."""
        r = client.patch(
            f"/api/{enterprise_clinic.slug}/whitelabel",
            json={"custom_footer_text": "© 2026 My Clinic. All rights reserved."},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200


class TestWhitelabelDomain:
    """Test custom domain mapping."""

    def test_set_custom_domain(self, client, enterprise_clinic, ent_token):
        """POST /api/{clinic}/whitelabel/domain sets domain."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/whitelabel/domain",
            json={"custom_domain": "clinic.yourdomain.com"},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["custom_domain"] == "clinic.yourdomain.com"
        assert data["domain_verified"] is False  # Needs DNS verification
        assert "dns_instructions" in data
        assert "cname_target" in data["dns_instructions"]

    def test_invalid_domain_format(self, client, enterprise_clinic, ent_token):
        """Invalid domain rejected."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/whitelabel/domain",
            json={"custom_domain": "notadomain"},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 400

    def test_growth_cannot_set_domain(self, client, growth_clinic, growth_token):
        """Growth plan cannot set custom domain."""
        r = client.post(
            f"/api/{growth_clinic.slug}/whitelabel/domain",
            json={"custom_domain": "test.example.com"},
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 403


class TestWhitelabelReseller:
    """Test reseller capabilities."""

    def test_get_reseller_config(self, client, enterprise_clinic, ent_token):
        """GET /api/{clinic}/whitelabel/reseller returns config."""
        r = client.get(
            f"/api/{enterprise_clinic.slug}/whitelabel/reseller",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["is_reseller"] is False  # Not enabled by default

    def test_enable_reseller_mode(self, client, enterprise_clinic, ent_token):
        """POST /api/{clinic}/whitelabel/reseller/enable activates reselling."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/whitelabel/reseller/enable",
            json={
                "reseller_commission": 20.0,
                "max_sub_clinics": 50,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["is_reseller"] is True
        assert data["reseller_commission"] == 20.0
        assert data["max_sub_clinics"] == 50

    def test_reseller_unlimited_sub_clinics(self, client, enterprise_clinic, ent_token):
        """Enable reseller with unlimited sub-clinics (max_sub_clinics=0)."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/whitelabel/reseller/enable",
            json={
                "reseller_commission": 15.0,
                "max_sub_clinics": 0,  # Unlimited
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["max_sub_clinics"] == "unlimited"

    def test_invalid_commission_rate(self, client, enterprise_clinic, ent_token):
        """Commission rate must be 0-30%."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/whitelabel/reseller/enable",
            json={"reseller_commission": 50.0},  # Too high
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 400

    def test_growth_cannot_enable_reseller(self, client, growth_clinic, growth_token):
        """Growth plan cannot enable reseller mode."""
        r = client.post(
            f"/api/{growth_clinic.slug}/whitelabel/reseller/enable",
            json={"reseller_commission": 20.0},
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 403


class TestWhitelabelSourceCode:
    """Test source code access for self-hosting."""

    def test_grant_source_code_access(self, client, enterprise_clinic, ent_token):
        """POST /api/{clinic}/whitelabel/source-code grants access."""
        r = client.post(
            f"/api/{enterprise_clinic.slug}/whitelabel/source-code",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["can_access_source"] is True
        assert data["self_host_enabled"] is True
        assert "Docker" in data["setup_instructions"] or "docker-compose" in data["setup_instructions"]

    def test_source_access_already_granted(self, client, enterprise_clinic, ent_token):
        """Granting source access twice returns same result."""
        # First grant
        r1 = client.post(
            f"/api/{enterprise_clinic.slug}/whitelabel/source-code",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r1.status_code == 200

        # Second grant (should be idempotent)
        r2 = client.post(
            f"/api/{enterprise_clinic.slug}/whitelabel/source-code",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r2.status_code == 200
        assert r2.json()["can_access_source"] is True

    def test_growth_cannot_access_source_code(self, client, growth_clinic, growth_token):
        """Growth plan cannot access source code."""
        r = client.post(
            f"/api/{growth_clinic.slug}/whitelabel/source-code",
            headers={"X-Clinic-Token": growth_token}
        )
        assert r.status_code == 403


class TestWhitelabelAuth:
    """Test authentication and authorization."""

    def test_invalid_token_rejected(self, client, enterprise_clinic):
        """Invalid clinic token returns 403."""
        r = client.get(
            f"/api/{enterprise_clinic.slug}/whitelabel",
            headers={"X-Clinic-Token": "invalid-token"}
        )
        assert r.status_code == 403

    def test_clinic_slug_mismatch_rejected(self, client, enterprise_clinic, growth_clinic, ent_token):
        """Accessing different clinic's white label rejected."""
        r = client.get(
            f"/api/{growth_clinic.slug}/whitelabel",  # Wrong clinic
            headers={"X-Clinic-Token": ent_token}  # Token for enterprise_clinic
        )
        assert r.status_code == 403

    def test_missing_token_rejected(self, client, enterprise_clinic):
        """Missing token returns 403."""
        r = client.get(f"/api/{enterprise_clinic.slug}/whitelabel")
        assert r.status_code == 403
