"""Cross-tenant isolation across ALL scoped routes (GAP-SEC-008) and idempotency
of repeatable background jobs (GAP-API: recall + reminder dedup). Extends the
single appointments-isolation test already in the suite to the full route surface."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_xtenant.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, RecallCampaign
from backend.routers.clinic_auth import hash_password
from backend.services import email_svc, recall_svc, reminders_svc

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
    c = Clinic(slug=f"xt-{_n}", name=f"XT {_n}", specialty="FM", email=f"xt{_n}@x.com",
               phone="555", plan=plan, subscription_status="active", timezone="UTC",
               customer_password_hash=hash_password("testpass123"), is_active=True,
               subscription_ends_at=dt.datetime.utcnow() + dt.timedelta(days=30))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _token(client, c):
    return client.post("/api/clinic-auth/login",
                       json={"email": c.email, "password": "testpass123"}).json()["token"]


# ── GAP-SEC-008: A's token cannot read B's data on ANY scoped route ───────────

SCOPED_GET_ROUTES = [
    "/api/{slug}/analytics",
    "/api/{slug}/profile",
    "/api/{slug}/recall-campaigns",
    "/api/{slug}/providers",
    "/api/{slug}/locations",
    "/api/{slug}/whitelabel",
    "/api/{slug}/custom-ai-training",
    "/api/{slug}/ehr-config",
    "/api/{slug}/insurance-knowledge",
    "/api/{slug}/report/monthly",
]


@pytest.mark.parametrize("route", SCOPED_GET_ROUTES)
def test_cross_tenant_get_blocked(client, db, route):
    a = _clinic(db)
    b = _clinic(db)
    a_tok = _token(client, a)
    r = client.get(route.format(slug=b.slug), headers={"x-clinic-token": a_tok})
    assert r.status_code == 403, f"{route} leaked across tenants: {r.status_code}"


def test_own_tenant_not_blocked(client, db):
    """Sanity: the guard is not a blanket 403 — own slug is allowed."""
    a = _clinic(db)
    a_tok = _token(client, a)
    for route in ["/api/{slug}/providers", "/api/{slug}/profile"]:
        r = client.get(route.format(slug=a.slug), headers={"x-clinic-token": a_tok})
        assert r.status_code != 403


def test_no_token_blocked(client, db):
    b = _clinic(db)
    assert client.get(f"/api/{b.slug}/providers").status_code == 403


# ── GAP-API: recall is idempotent across repeated runs (cron overlap safe) ────

@pytest.fixture
def no_email(monkeypatch):
    monkeypatch.setattr(email_svc, "send_email", lambda **kw: True)


def test_recall_run_is_idempotent(db, no_email):
    c = _clinic(db)
    old = dt.datetime.utcnow() - dt.timedelta(days=400)
    db.add(Appointment(clinic_id=c.id, confirmation_number=f"R{_n}", patient_name="Old",
                       patient_email="old@x.com", appointment_type="Physical",
                       appointment_datetime="last year", appointment_ts=old,
                       status="completed", created_at=old))
    camp = RecallCampaign(clinic_id=c.id, name="Annual", visit_type="annual physical",
                          interval_months=12, is_active=True, message_template="")
    db.add(camp)
    db.commit()
    db.refresh(camp)

    first = recall_svc.run_campaign(db, c, camp)
    second = recall_svc.run_campaign(db, c, camp)
    assert first["sent"] == 1
    assert second["sent"] == 0          # dedup via recall log — no double email


# ── GAP-API: appointment reminders don't re-send (sent-flag dedup) ────────────

def test_reminder_send_is_idempotent(db, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(email_svc, "send_email",
                        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or True))
    c = _clinic(db)
    soon = dt.datetime.utcnow() + dt.timedelta(hours=24)
    db.add(Appointment(clinic_id=c.id, confirmation_number=f"A{_n}", patient_name="Pat",
                       patient_email="pat@x.com", appointment_type="Physical",
                       appointment_datetime="tomorrow", appointment_ts=soon,
                       status="scheduled", reminder_24h_sent=False,
                       created_at=dt.datetime.utcnow()))
    db.commit()

    reminders_svc.send_due_reminders(db)
    after_first = calls["n"]
    reminders_svc.send_due_reminders(db)
    assert after_first >= 1
    assert calls["n"] == after_first    # second run sends nothing more
