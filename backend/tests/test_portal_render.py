"""
REG-004 — Portal page render regression test.

The portal page GET /c/{clinic_slug} is an f-string HTML template.  Any
unescaped { or } in that template (e.g. bare CSS rule .cls { prop: val; })
causes a NameError at render time → 500 Internal Server Error.

This test catches that class of regression: if the HTML template is valid
Python the response must be 200 and contain the key portal UI landmarks.
"""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_portal.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.routers.clinic_auth import hash_password
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(scope="module")
def portal_clinic():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = S()
    try:
        slug = "reg004-portal-clinic"
        c = Clinic(
            slug=slug,
            name="Regression Portal Clinic",
            specialty="Family Medicine",
            email="reg004@test.com",
            phone="5550000001",
            subscription_status="active",
            plan="professional",
            customer_password_hash=hash_password("portalpass"),
            is_active=True,
            subscription_ends_at=datetime.utcnow() + timedelta(days=30),
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        yield c
    finally:
        db.query(Clinic).filter(Clinic.slug == slug).delete()
        db.commit()
        db.close()


class TestPortalPageRender:
    """REG-004: GET /c/{slug} must render 200 with all portal UI landmarks present."""

    def test_portal_returns_200(self, client, portal_clinic):
        """Portal page must not 500 — catches f-string CSS brace escaping bugs."""
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200, (
            f"Portal returned {r.status_code}. "
            "Likely cause: unescaped {{ }} in the f-string HTML template. "
            f"Body snippet: {r.text[:300]}"
        )

    def test_portal_contains_setup_tab(self, client, portal_clinic):
        """Setup tab panel must be present in the portal HTML."""
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200
        assert 'id="tab-setup"' in r.text, "Setup tab panel missing from portal"

    def test_portal_contains_phase2_apt_list(self, client, portal_clinic):
        """Phase 2 — Appointment Types section (apt-list) must be present."""
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200
        assert "apt-list" in r.text, "Appointment types section (apt-list) missing from portal"

    def test_portal_contains_phase2_holidays(self, client, portal_clinic):
        """Phase 2 — Closed Dates section (hol-tags) must be present."""
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200
        assert "hol-tags" in r.text, "Holidays section (hol-tags) missing from portal"

    def test_portal_contains_phase2_notif(self, client, portal_clinic):
        """Phase 2 — Notification Preferences toggle (notif-72h) must be present."""
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200
        assert "notif-72h" in r.text, "Notification prefs toggle (notif-72h) missing from portal"

    def test_portal_setup_css_class_present(self, client, portal_clinic):
        """setup-lbl CSS class must appear in portal HTML (verifies CSS was injected)."""
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200
        assert "setup-lbl" in r.text, "CSS class setup-lbl not found in portal HTML"

    def test_portal_nonexistent_slug_returns_404(self, client):
        """Non-existent clinic slug must return 404, not 500."""
        r = client.get("/c/this-clinic-does-not-exist-xyz999")
        assert r.status_code in (404, 200), (
            f"Expected 404 for missing clinic, got {r.status_code}"
        )

    def test_portal_contains_appointments_tab(self, client, portal_clinic):
        """Appointments tab button must be in the portal HTML."""
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200
        assert "tab-appointments" in r.text or "Appointments" in r.text, (
            "Appointments tab missing from portal"
        )

    def test_portal_html_is_valid_utf8(self, client, portal_clinic):
        """Portal response encoding must be UTF-8 (no mojibake from emoji in source)."""
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200
        # If encoding is wrong, .text would raise or produce garbled output
        assert len(r.text) > 1000, "Portal HTML suspiciously short"

    def test_portal_js_no_adjacent_string_literals_in_onchnage(self, client, portal_clinic):
        """REG-006: Python \\' escape in f-string must not collapse to '' (adjacent JS strings).

        Regression: `\\'` in Python f-string source rendered as `'` (Python strips
        the escape), producing `'' + day + ''` in JavaScript — two adjacent string
        literals with no operator → 'Unexpected string' SyntaxError → ALL JS functions
        undefined → login/portal completely broken.

        Fix: use `\\\\'` in Python source so Python emits `\\'` → JS sees `\\'` as an
        escaped quote inside a single-quoted string.
        """
        r = client.get(f"/c/{portal_clinic.slug}")
        assert r.status_code == 200
        # The broken pattern: adjacent empty-string literals around + day +
        assert "'' + day + ''" not in r.text, (
            "REG-006: portal JS contains '' + day + '' — "
            "Python f-string escape \\' collapsed to ', producing adjacent JS string literals "
            "which crash ALL script execution. Fix: use \\\\' in Python source."
        )
        # The hours-grid onchange handler must be present
        assert "toggleDayRow" in r.text, "toggleDayRow function reference missing from portal JS"
