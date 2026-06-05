"""Custom AI training tests."""
import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_training.db")
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


_test_counter = 0


@pytest.fixture
def enterprise_clinic(db, request):
    global _test_counter
    _test_counter += 1
    slug = f"ent-train-{_test_counter}"
    c = Clinic(
        slug=slug, name="Enterprise Training Clinic", specialty="Family Medicine",
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
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def professional_clinic(db, request):
    global _test_counter
    _test_counter += 1
    slug = f"prof-train-{_test_counter}"
    c = Clinic(
        slug=slug, name="Professional Training Clinic", specialty="Pediatrics",
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
    db.query(Clinic).filter(Clinic.id == c.id).delete()
    db.commit()


@pytest.fixture
def ent_token(client, enterprise_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": enterprise_clinic.email, "password": "testpass123"
    })
    return r.json()["token"]


@pytest.fixture
def prof_token(client, professional_clinic):
    r = client.post("/api/clinic-auth/login", json={
        "email": professional_clinic.email, "password": "testpass123"
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


class TestCustomAITraining:
    def test_requires_auth(self, client, enterprise_clinic):
        r = client.get(f"/api/{enterprise_clinic.slug}/custom-ai-training")
        assert r.status_code == 403

    def test_blocked_for_professional_plan(self, client, professional_clinic, prof_token):
        r = client.get(
            f"/api/{professional_clinic.slug}/custom-ai-training",
            headers={"X-Clinic-Token": prof_token}
        )
        assert r.status_code == 403

    def test_list_empty_training(self, client, enterprise_clinic, ent_token):
        r = client.get(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["summary"]["total_items"] == 0

    def test_create_training_item(self, client, enterprise_clinic, ent_token):
        r = client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={
                "training_type": "policy",
                "title": "Telehealth Policy",
                "content": "Telehealth appointments are available Mon-Fri 9am-5pm. Requires video camera and stable internet.",
                "is_active": True,
                "priority": 5,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Telehealth Policy"
        assert data["type"] == "policy"
        assert data["priority"] == 5
        assert data["is_active"] is True

    def test_list_training_items(self, client, enterprise_clinic, ent_token):
        # Create items
        client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={
                "title": "Intake Form",
                "content": "Patients must complete the intake form before first appointment.",
                "priority": 3,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={
                "title": "Insurance Required",
                "content": "All patients must provide active insurance coverage.",
                "priority": 8,
            },
            headers={"X-Clinic-Token": ent_token}
        )

        # List
        r = client.get(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) >= 2
        # Should be sorted by priority descending, find the two we just created
        items_by_priority = sorted(data["items"], key=lambda x: x["priority"], reverse=True)
        assert any(item["title"] == "Insurance Required" for item in items_by_priority[:3])
        assert any(item["title"] == "Intake Form" for item in items_by_priority)

    def test_update_training_item(self, client, enterprise_clinic, ent_token):
        # Create
        r = client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={
                "title": "Original Title",
                "content": "Original content",
                "priority": 2,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        training_id = r.json()["id"]

        # Update
        r = client.patch(
            f"/api/{enterprise_clinic.slug}/custom-ai-training/{training_id}",
            json={
                "title": "Updated Title",
                "priority": 7,
                "is_active": False,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Updated Title"
        assert data["priority"] == 7
        assert data["is_active"] is False

    def test_delete_training_item(self, client, enterprise_clinic, ent_token):
        # Create
        r = client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={"title": "To Delete", "content": "This will be deleted"},
            headers={"X-Clinic-Token": ent_token}
        )
        training_id = r.json()["id"]
        initial_count = r.json()["id"]  # Get initial state

        # Delete
        r = client.delete(
            f"/api/{enterprise_clinic.slug}/custom-ai-training/{training_id}",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["deleted"] is True

        # Verify deletion - the deleted item should not be in the list
        r = client.get(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert not any(item["id"] == training_id for item in items)

    def test_content_validation(self, client, enterprise_clinic, ent_token):
        # Content too long (> 5000 chars)
        long_content = "x" * 5001
        r = client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={
                "title": "Too Long",
                "content": long_content,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 400

    def test_missing_required_fields(self, client, enterprise_clinic, ent_token):
        # Missing title
        r = client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={"content": "Some content"},
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 400

    def test_priority_bounds(self, client, enterprise_clinic, ent_token):
        # Priority > 10 should be clamped to 10
        r = client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={
                "title": "High Priority",
                "content": "Test",
                "priority": 15,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["priority"] == 10

        # Priority < 0 should be clamped to 0
        r = client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={
                "title": "Low Priority",
                "content": "Test",
                "priority": -5,
            },
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        assert r.json()["priority"] == 0

    def test_summary_endpoint(self, client, enterprise_clinic, ent_token):
        # Create a few items
        r1 = client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={"title": "Item 1", "content": "Content 1", "is_active": True},
            headers={"X-Clinic-Token": ent_token}
        )
        initial_items = r1.json()["id"] - 1  # items created before this test

        client.post(
            f"/api/{enterprise_clinic.slug}/custom-ai-training",
            json={"title": "Item 2", "content": "Content 2", "is_active": False},
            headers={"X-Clinic-Token": ent_token}
        )

        r = client.get(
            f"/api/{enterprise_clinic.slug}/custom-ai-training/summary",
            headers={"X-Clinic-Token": ent_token}
        )
        assert r.status_code == 200
        data = r.json()
        # At least the 2 we just created should be there
        assert data["total_items"] >= 2
        assert data["active_items"] >= 1
        assert len(data["items"]) >= 2
        # Verify our items are in the list
        titles = [item["title"] for item in data["items"]]
        assert "Item 1" in titles
        assert "Item 2" in titles
