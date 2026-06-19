"""Edge-case tests (L-3/L-4/L-5): invalid appointment dates, negative/garbage IDs,
IDN/garbage domains, large-batch (volume) recall, and DB index validation."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_edge.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment, RecallCampaign
from backend.routers.clinic_auth import hash_password
from backend.services import appointment_svc, recall_svc, email_svc
from backend.routers.whitelabel import _is_valid_domain

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
    c = Clinic(slug=f"edge-{_n}", name=f"Edge {_n}", specialty="FM", email=f"edge{_n}@x.com",
               phone="555", plan=plan, subscription_status="active", timezone="UTC",
               customer_password_hash=hash_password("testpass123"), is_active=True,
               subscription_ends_at=dt.datetime.utcnow() + dt.timedelta(days=30))
    db.add(c); db.commit(); db.refresh(c)
    return c


def _token(client, c):
    return client.post("/api/clinic-auth/login",
                       json={"email": c.email, "password": "testpass123"}).json()["token"]


def _future_str(days=45):
    return (dt.date.today() + dt.timedelta(days=days)).strftime("%B %d, %Y") + " at 10:00 AM"


# ── L-5: invalid appointment dates ────────────────────────────────────────────

def test_book_past_date_rejected(db):
    c = _clinic(db)
    r = appointment_svc.book_appointment(c, db, patient_name="Pat",
                                         appointment_type="Physical",
                                         datetime_str="January 1, 2020 at 10:00 AM")
    assert r["success"] is False and "past" in r["error"].lower()


def test_book_absurd_year_rejected(db):
    c = _clinic(db)
    r = appointment_svc.book_appointment(c, db, patient_name="Pat",
                                         appointment_type="Physical",
                                         datetime_str="January 1, 9999 at 10:00 AM")
    assert r["success"] is False


def test_impossible_calendar_date_not_parsed():
    # February 30 can never exist -> parser returns None (never a real timestamp)
    assert appointment_svc._parse_datetime_str("February 30, 2027 at 10:00 AM") is None


def test_book_valid_future_date_succeeds(db):
    c = _clinic(db)
    r = appointment_svc.book_appointment(c, db, patient_name="Pat",
                                         appointment_type="Physical",
                                         datetime_str=_future_str())
    assert r["success"] is True


def test_reschedule_to_past_rejected(db):
    c = _clinic(db)
    r = appointment_svc.reschedule_appointment(c, db, patient_name="Pat",
                                               new_datetime="January 1, 2019 at 9:00 AM")
    assert r["success"] is False


# ── L-4: negative / garbage IDs ───────────────────────────────────────────────

def test_negative_provider_id_not_found(client, db):
    c = _clinic(db)
    tok = _token(client, c)
    r = client.get(f"/api/{c.slug}/providers/-1", headers={"x-clinic-token": tok})
    assert r.status_code == 404


def test_non_numeric_provider_id_422(client, db):
    c = _clinic(db)
    tok = _token(client, c)
    r = client.get(f"/api/{c.slug}/providers/abc", headers={"x-clinic-token": tok})
    assert r.status_code == 422


# ── L-4: IDN + garbage domain validation ──────────────────────────────────────

@pytest.mark.parametrize("domain,ok", [
    ("clinic.example.com", True),
    ("a.co", True),
    ("xn--mnchen-3ya.de", True),     # punycode IDN
    ("münchen.de", True),            # unicode IDN (normalized to punycode)
    ("notadomain", False),
    ("http://x.com", False),
    ("clinic.example.com/path", False),
    ("has space.com", False),
    ("javascript:alert(1)", False),
    ("", False),
])
def test_domain_validation_matrix(domain, ok):
    assert _is_valid_domain(domain) is ok


# ── L-3: large-batch (volume) recall is processed end to end ──────────────────

def test_large_recall_batch_volume(db, monkeypatch):
    monkeypatch.setattr(email_svc, "send_email", lambda **kw: True)
    c = _clinic(db)
    old = dt.datetime.utcnow() - dt.timedelta(days=400)
    N = 150
    for i in range(N):
        db.add(Appointment(clinic_id=c.id, confirmation_number=f"VOL{_n}-{i}",
                           patient_name=f"P{i}", patient_email=f"p{i}-{_n}@x.com",
                           appointment_type="Physical", appointment_datetime="last year",
                           appointment_ts=old, status="completed", created_at=old))
    camp = RecallCampaign(clinic_id=c.id, name="Annual", visit_type="annual physical",
                          interval_months=12, is_active=True, message_template="")
    db.add(camp); db.commit(); db.refresh(camp)

    stats = recall_svc.run_campaign(db, c, camp)
    assert stats["sent"] == N        # every due patient processed in one batch


# ── L-3: hot-path indexes exist (query-performance guard) ─────────────────────

def test_hot_path_indexes_exist():
    insp = sa_inspect(engine)
    appt_indexed = {col for ix in insp.get_indexes("appointments") for col in ix["column_names"]}
    # clinic_id is the primary tenant filter on the largest table
    assert "clinic_id" in appt_indexed
    # chat_sessions has the composite (clinic_id, session_id) lookup index
    cs_indexes = insp.get_indexes("chat_sessions")
    assert any("clinic_id" in ix["column_names"] and "session_id" in ix["column_names"]
               for ix in cs_indexes)
