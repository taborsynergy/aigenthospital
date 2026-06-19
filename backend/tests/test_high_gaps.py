"""HIGH-priority gap fixes (H-1..H-8):
  H-1 admin activation idempotency (no double-charge on double-click)
  H-2 timezone-aware reminder window (fires at clinic-local time)
  H-3 password-reset token single-use + expiry
  H-4 user-create role allowlist (no privilege escalation)
  H-5 transaction rollback leaves no partial state
  H-6 concurrent update is deterministic (no corruption)
  H-7 concurrency smoke (full load test lives in perf/k6_load.js)
  H-8 Supabase RLS anon lockout (skipped unless live creds provided)
"""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_highgaps.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, ClinicUser, Appointment
from backend.db import crud
from backend.routers.clinic_auth import hash_password
from backend.services import reminders_svc, email_svc
from backend.timezones import clinic_local_now, iana_zone

ADMIN = {"X-Admin-Password": "test-admin-secret"}
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


def _clinic(db, **kw):
    global _n
    _n += 1
    base = dict(slug=f"hg-{_n}", name=f"HG {_n}", specialty="FM", email=f"hg{_n}@x.com",
                plan="professional", subscription_status="active",
                customer_password_hash=hash_password("testpass123"), is_active=True)
    base.update(kw)
    c = Clinic(**base)
    db.add(c); db.commit(); db.refresh(c)
    return c


@pytest.fixture
def no_email(monkeypatch):
    monkeypatch.setattr(email_svc, "send_email", lambda **kw: True)


# ── H-1: activation idempotency ───────────────────────────────────────────────

def test_activation_double_click_is_idempotent(db):
    c = _clinic(db, subscription_status="trial", subscription_ends_at=None)
    first = crud.activate_subscription(db, c.slug)
    ends1 = first.subscription_ends_at
    second = crud.activate_subscription(db, c.slug)          # accidental double-click
    assert second.subscription_ends_at == ends1             # no second month stacked


def test_activation_near_expiry_still_extends(db):
    soon = dt.datetime.utcnow() + dt.timedelta(days=2)
    c = _clinic(db, subscription_status="active", subscription_ends_at=soon)
    out = crud.activate_subscription(db, c.slug)            # legit renewal near expiry
    assert out.subscription_ends_at > dt.datetime.utcnow() + dt.timedelta(days=30)


# ── H-2: timezone-aware reminder window ───────────────────────────────────────

def test_timezone_mapping():
    assert iana_zone("Central Time (CT)") == "America/Chicago"
    assert iana_zone("Pacific Time (PT)") == "America/Los_Angeles"
    assert iana_zone("UTC") == "UTC"
    assert iana_zone("nonsense") == "UTC"


def _add_appt(db, clinic, ts):
    global _n
    _n += 1
    a = Appointment(clinic_id=clinic.id, confirmation_number=f"HG{_n}", patient_name="Pat",
                    patient_email="pat@x.com", appointment_type="Physical",
                    appointment_datetime="soon", appointment_ts=ts, status="scheduled",
                    reminder_24h_sent=False, created_at=dt.datetime.utcnow())
    db.add(a); db.commit(); db.refresh(a)
    return a


def test_reminder_fires_at_clinic_local_time(db, no_email):
    c = _clinic(db, timezone="Pacific Time (PT)")
    appt = _add_appt(db, c, clinic_local_now(c) + dt.timedelta(hours=24))
    reminders_svc.send_due_reminders(db)
    db.refresh(appt)
    assert appt.reminder_24h_sent is True


def test_reminder_does_not_fire_on_wrong_tz_frame(db, no_email):
    # A Pacific clinic with an appt placed in the UTC frame is hours out of window
    c = _clinic(db, timezone="Pacific Time (PT)")
    appt = _add_appt(db, c, dt.datetime.utcnow() + dt.timedelta(hours=24))
    reminders_svc.send_due_reminders(db)
    db.refresh(appt)
    assert appt.reminder_24h_sent is False


# ── H-3: password-reset token single-use + expiry ─────────────────────────────

def _user(db, clinic, **kw):
    global _n
    _n += 1
    base = dict(clinic_id=clinic.id, email=f"hguser{_n}@x.com", password_hash=hash_password("oldpass12"),
                full_name="U", role="admin")
    base.update(kw)
    u = ClinicUser(**base)
    db.add(u); db.commit(); db.refresh(u)
    return u


def test_reset_token_single_use(client, db):
    c = _clinic(db)
    u = _user(db, c, reset_token="tok-single-123",
              reset_token_expires=dt.datetime.utcnow() + dt.timedelta(hours=1))
    body = {"token": "tok-single-123", "new_password": "brandnew123"}
    assert client.post("/api/clinic/users/reset-password", json=body).status_code == 200
    # token cleared -> second use rejected
    assert client.post("/api/clinic/users/reset-password", json=body).status_code == 400


def test_reset_token_expired_rejected(client, db):
    c = _clinic(db)
    _user(db, c, reset_token="tok-expired-123",
          reset_token_expires=dt.datetime.utcnow() - dt.timedelta(minutes=1))
    r = client.post("/api/clinic/users/reset-password",
                    json={"token": "tok-expired-123", "new_password": "brandnew123"})
    assert r.status_code == 400


# ── H-4: user-create role allowlist (no privilege escalation) ─────────────────

def test_user_create_rejects_unknown_role(client, db):
    c = _clinic(db)
    global _n; _n += 1
    r = client.post("/api/clinic/users/create", headers=ADMIN, json={
        "clinic_slug": c.slug, "email": f"esc{_n}@x.com", "full_name": "E",
        "password": "validpass12", "role": "superadmin"})
    assert r.status_code == 400


def test_user_create_accepts_allowlisted_role(client, db):
    c = _clinic(db)
    global _n; _n += 1
    r = client.post("/api/clinic/users/create", headers=ADMIN, json={
        "clinic_slug": c.slug, "email": f"mgr{_n}@x.com", "full_name": "M",
        "password": "validpass12", "role": "manager"})
    assert r.status_code in (200, 201)


# ── H-5: transaction rollback leaves no partial state ─────────────────────────

def test_failed_commit_rolls_back_cleanly(db):
    c = _clinic(db)
    before = db.query(Clinic).count()
    db.add(Clinic(slug=c.slug, name="dup", specialty="FM",
                  email="dup-h5@x.com", customer_password_hash="x"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.query(Clinic).count() == before          # no partial row persisted
    assert crud.get_clinic(db, c.slug) is not None      # session still usable


# ── H-6: concurrent update is deterministic (last-writer-wins, no corruption) ─

def test_concurrent_update_last_writer_wins(db):
    c = _clinic(db)
    S = sessionmaker(bind=engine)
    s1, s2 = S(), S()
    try:
        c1 = s1.query(Clinic).filter(Clinic.id == c.id).one()
        c2 = s2.query(Clinic).filter(Clinic.id == c.id).one()
        c1.specialty = "Cardiology"
        c2.specialty = "Dermatology"
        s1.commit()
        s2.commit()                       # no exception/corruption
    finally:
        s1.close(); s2.close()
    db.expire_all()
    assert db.query(Clinic).filter(Clinic.id == c.id).one().specialty == "Dermatology"


# ── H-7: concurrency smoke (full load test = perf/k6_load.js) ─────────────────

def test_concurrent_requests_smoke(client):
    def hit(_):
        return client.get("/api/health").status_code
    with ThreadPoolExecutor(max_workers=10) as ex:
        codes = list(ex.map(hit, range(30)))
    assert all(code == 200 for code in codes)


# ── H-8: Supabase RLS anon lockout (live integration — skipped without creds) ─

@pytest.mark.skipif(not os.getenv("SUPABASE_ANON_TEST_URL"),
                    reason="set SUPABASE_ANON_TEST_URL + SUPABASE_ANON_KEY to run live RLS check")
def test_supabase_rls_blocks_anonymous_reads():
    import httpx
    url = os.environ["SUPABASE_ANON_TEST_URL"].rstrip("/") + "/rest/v1/clinics?select=*"
    key = os.environ["SUPABASE_ANON_KEY"]
    r = httpx.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=15)
    # RLS enabled -> anon gets 401/403 or an empty set, never real rows
    assert r.status_code in (401, 403) or r.json() == []
