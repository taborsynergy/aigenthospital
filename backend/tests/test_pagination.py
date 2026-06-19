"""Pagination / filter / sort + boundary extremes (GAP2-API-PAGE, GAP2-BVA-PAGE)
for the appointments and admin-clinics list endpoints."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_pagination.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic, Appointment
from backend.routers.clinic_auth import hash_password

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


def _clinic(db):
    global _n
    _n += 1
    c = Clinic(slug=f"pg-{_n}", name=f"PG {_n}", specialty="FM", email=f"pg{_n}@x.com",
               plan="professional", subscription_status="active",
               customer_password_hash=hash_password("testpass123"), is_active=True,
               subscription_ends_at=dt.datetime.utcnow() + dt.timedelta(days=30))
    db.add(c); db.commit(); db.refresh(c)
    return c


_seed_seq = 0


def _seed_appts(db, clinic, n, status="scheduled"):
    global _seed_seq
    base = dt.datetime.utcnow() - dt.timedelta(hours=n)
    for i in range(n):
        _seed_seq += 1
        db.add(Appointment(clinic_id=clinic.id, confirmation_number=f"PG{clinic.id}-{_seed_seq}",
                           patient_name=f"P{i}", appointment_type="Physical",
                           appointment_datetime="soon", status=status,
                           created_at=base + dt.timedelta(hours=i)))
    db.commit()


def _token(client, c):
    return client.post("/api/clinic-auth/login",
                       json={"email": c.email, "password": "testpass123"}).json()["token"]


# ── Appointments pagination ───────────────────────────────────────────────────

def test_appts_limit_and_total_count(client, db):
    c = _clinic(db); _seed_appts(db, c, 5)
    tok = _token(client, c)
    r = client.get(f"/api/{c.slug}/appointments?limit=2", headers={"x-clinic-token": tok})
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert r.headers["X-Total-Count"] == "5"


def test_appts_offset_paging(client, db):
    c = _clinic(db); _seed_appts(db, c, 5)
    tok = _token(client, c)
    p1 = client.get(f"/api/{c.slug}/appointments?limit=2&offset=0", headers={"x-clinic-token": tok}).json()
    p2 = client.get(f"/api/{c.slug}/appointments?limit=2&offset=2", headers={"x-clinic-token": tok}).json()
    assert {a["confirmation_number"] for a in p1} & {a["confirmation_number"] for a in p2} == set()


def test_appts_status_filter(client, db):
    c = _clinic(db)
    _seed_appts(db, c, 3, status="scheduled")
    _seed_appts(db, c, 2, status="cancelled")
    tok = _token(client, c)
    r = client.get(f"/api/{c.slug}/appointments?status=cancelled", headers={"x-clinic-token": tok})
    assert r.headers["X-Total-Count"] == "2"
    assert all(a["status"] == "cancelled" for a in r.json())


def test_appts_sort_asc_vs_desc(client, db):
    c = _clinic(db); _seed_appts(db, c, 4)
    tok = _token(client, c)
    asc = client.get(f"/api/{c.slug}/appointments?sort=asc", headers={"x-clinic-token": tok}).json()
    desc = client.get(f"/api/{c.slug}/appointments?sort=desc", headers={"x-clinic-token": tok}).json()
    assert [a["confirmation_number"] for a in asc] == [a["confirmation_number"] for a in desc][::-1]


# ── Boundary extremes (BVA-PAGE) ──────────────────────────────────────────────

@pytest.mark.parametrize("qs,expect_max", [
    ("limit=0", 25),      # 0 -> clamped to >=1 (won't error); we seed 25 so <=25
    ("limit=100000", 25), # huge -> capped at 200, but only 25 exist
    ("offset=-5", 25),    # negative offset -> clamped to 0
    ("limit=abc", 25),    # garbage -> default
])
def test_appts_pagination_extremes_dont_error(client, db, qs, expect_max):
    c = _clinic(db); _seed_appts(db, c, 25)
    tok = _token(client, c)
    r = client.get(f"/api/{c.slug}/appointments?{qs}", headers={"x-clinic-token": tok})
    assert r.status_code == 200
    assert 1 <= len(r.json()) <= expect_max


# ── Admin clinics pagination ──────────────────────────────────────────────────

def test_admin_clinics_pagination(client, db):
    for _ in range(3):
        _clinic(db)
    r = client.get("/admin/api/clinics?limit=2", headers=ADMIN)
    assert r.status_code == 200
    assert len(r.json()) <= 2
    assert int(r.headers["X-Total-Count"]) >= 3


def test_admin_clinics_status_filter(client, db):
    c = _clinic(db)
    r = client.get("/admin/api/clinics?status=active&limit=500", headers=ADMIN)
    assert r.status_code == 200
    assert all(x["subscription_status"] == "active" for x in r.json())
