"""GAP2 HIGH fixes: payment reconciliation (PAY-001), DB-restart resilience
(REL-RESTART), and the multi-worker scheduler gate / perf harness (PERF-EXEC)."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_resbill.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.main import app
from backend.db.database import Base, engine, get_db
from backend.db.models import Clinic
from backend.db import crud
from backend.routers.clinic_auth import hash_password

ADMIN = {"X-Admin-Password": "test-admin-secret"}
_n = 0
ROOT = pathlib.Path(__file__).resolve().parents[2]


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


def _clinic(db, **kw):
    global _n
    _n += 1
    base = dict(slug=f"rb-{_n}", name=f"RB {_n}", specialty="FM", email=f"rb{_n}@x.com",
                plan="professional", subscription_status="trial",
                customer_password_hash=hash_password("testpass123"), is_active=True)
    base.update(kw)
    c = Clinic(**base)
    db.add(c); db.commit(); db.refresh(c)
    return c


# ── GAP2-PAY-001: payment <-> activation reconciliation ───────────────────────

def test_same_payment_reference_is_not_double_credited(db):
    c = _clinic(db)
    first = crud.activate_subscription(db, c.slug, payment_reference="PAYPAL-TX-1")
    ends1 = first.subscription_ends_at
    assert first.last_payment_reference == "PAYPAL-TX-1"
    # Duplicate webhook / double-click with the SAME payment id -> no extra month
    second = crud.activate_subscription(db, c.slug, payment_reference="PAYPAL-TX-1")
    assert second.subscription_ends_at == ends1


def test_new_payment_reference_extends_near_expiry(db):
    soon = dt.datetime.utcnow() + dt.timedelta(days=2)
    c = _clinic(db, subscription_status="active", subscription_ends_at=soon,
                last_payment_reference="PAYPAL-TX-1")
    out = crud.activate_subscription(db, c.slug, payment_reference="PAYPAL-TX-2")
    assert out.subscription_ends_at > dt.datetime.utcnow() + dt.timedelta(days=30)
    assert out.last_payment_reference == "PAYPAL-TX-2"


def test_activate_endpoint_idempotent_per_payment(client, db):
    c = _clinic(db)
    url = f"/admin/api/clinics/{c.slug}/activate?payment_reference=RX-9"
    r1 = client.post(url, headers=ADMIN)
    assert r1.status_code == 200
    ends1 = r1.json()["subscription_ends_at"]
    r2 = client.post(url, headers=ADMIN)          # same payment ref again
    assert r2.status_code == 200
    assert r2.json()["subscription_ends_at"] == ends1   # no second month


# ── GAP2-REL-RESTART: DB unreachable -> clean 503, not a 500 trace ────────────

def test_get_db_converts_db_error_to_clean_503():
    # Realistic DB restart: a query inside the request raises OperationalError, which
    # propagates back into the get_db generator at `yield`. get_db must convert it to
    # a clean 503 HTTPException (always rendered as JSON, never a 500 stack trace).
    from fastapi import HTTPException
    gen = get_db()
    next(gen)  # obtain the session (no I/O yet — lazy connect)
    with pytest.raises(HTTPException) as ei:
        gen.throw(OperationalError("SELECT 1", {}, Exception("database is starting up")))
    assert ei.value.status_code == 503
    assert "unavailable" in str(ei.value.detail).lower()


def test_db_error_handler_registered_returns_503():
    # The app-level handler is a belt-and-suspenders fallback for connectivity
    # errors raised outside a get_db-scoped query.
    import asyncio
    from backend.main import _db_unavailable_handler
    resp = asyncio.run(_db_unavailable_handler(None, OperationalError("x", {}, Exception("down"))))
    assert resp.status_code == 503


def test_pool_pre_ping_configured_for_postgres():
    # On SQLite the pool args don't apply; assert intent is encoded for PG.
    import backend.db.database as dbmod
    if dbmod._is_sqlite:
        pytest.skip("pre-ping is a Postgres pool setting; not used for SQLite")
    assert engine.pool._pre_ping is True


# ── GAP2-PERF-EXEC: multi-worker scheduler gate + perf harness present ────────

def test_scheduler_gate_flag_defaults_on():
    assert settings.enable_scheduler is True   # default; set false when multi-worker


def test_perf_harness_artifacts_exist():
    assert (ROOT / "perf" / "k6_load.js").exists()
    assert (ROOT / ".github" / "workflows" / "perf-k6.yml").exists()
