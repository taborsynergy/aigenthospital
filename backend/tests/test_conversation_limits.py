"""Tests for monthly conversation tracking + enforcement.

Verifies: usage is counted per distinct session (not per message), the /plan
endpoint surfaces conversations_used vs conversations_limit, the cap is enforced
with an upgrade message, and Enterprise is unlimited.
"""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_conv_limits.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, UsageLog
from backend.db import crud
from backend.routers.clinic_auth import hash_password

_n = 0


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


def _clinic(db, plan="professional"):
    global _n
    _n += 1
    slug = f"conv-{_n}"
    c = Clinic(slug=slug, name=f"Conv Clinic {_n}", specialty="FM", plan=plan,
               email=f"{slug}@test.com", subscription_status="active",
               customer_password_hash=hash_password("testpass123"), is_active=True,
               subscription_ends_at=datetime.utcnow() + timedelta(days=30))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _login(client, clinic):
    r = client.post("/api/clinic-auth/login",
                    json={"email": clinic.email, "password": "testpass123"})
    return r.json()["token"]


def _seed_sessions(db, clinic, n_sessions, msgs_each=1):
    db.add_all([
        UsageLog(clinic_id=clinic.id, session_id=f"s{clinic.id}-{i}",
                 channel="web", input_tokens=1, output_tokens=1)
        for i in range(n_sessions) for _ in range(msgs_each)
    ])
    db.commit()


def test_many_messages_one_session_count_once(db):
    """A patient sending 20 messages in one visit = 1 conversation."""
    c = _clinic(db, "professional")
    _seed_sessions(db, c, n_sessions=1, msgs_each=20)
    assert crud.get_usage_this_month(db, c.id) == 1


def test_distinct_sessions_counted(db):
    c = _clinic(db, "professional")
    _seed_sessions(db, c, n_sessions=5, msgs_each=3)  # 5 sessions, 3 msgs each
    assert crud.get_usage_this_month(db, c.id) == 5


def test_plan_endpoint_surfaces_usage_and_limit(client, db):
    c = _clinic(db, "professional")
    _seed_sessions(db, c, n_sessions=4)
    r = client.get(f"/api/{c.slug}/plan", headers={"x-clinic-token": _login(client, c)})
    assert r.status_code == 200
    j = r.json()
    assert j["conversations_limit"] == 1000
    assert j["conversations_used"] == 4


def test_starter_blocked_at_cap(client, db):
    c = _clinic(db, "starter")  # 300/month cap
    _seed_sessions(db, c, n_sessions=300)
    r = client.post(f"/api/{c.slug}/chat", json={"message": "Hi", "session_id": "new-visit"})
    assert r.status_code == 403
    assert "limit" in (r.json().get("error", "").lower())


def test_under_cap_allows_chat(client, db):
    c = _clinic(db, "starter")
    _seed_sessions(db, c, n_sessions=5)  # well under 300
    r = client.post(f"/api/{c.slug}/chat", json={"message": "Hi", "session_id": "v1"})
    assert r.status_code == 200


def test_enterprise_unlimited(client, db):
    c = _clinic(db, "enterprise")
    _seed_sessions(db, c, n_sessions=50)
    # /plan reports no limit
    r = client.get(f"/api/{c.slug}/plan", headers={"x-clinic-token": _login(client, c)})
    assert r.json()["conversations_limit"] is None
    # and chat is never blocked
    r2 = client.post(f"/api/{c.slug}/chat", json={"message": "Hi", "session_id": "ent"})
    assert r2.status_code == 200
