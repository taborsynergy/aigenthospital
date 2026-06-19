"""Tests for trial-reminder dedup (7/3/1) and subscription renewal reminders."""
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_renewal.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import datetime as dt
import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.db import crud
from backend.services import email_svc
from backend.jobs.trial_jobs import (
    reminder_bucket, check_trial_expiry_and_remind, REMINDER_THRESHOLDS,
)
from backend.jobs.billing_jobs import check_renewals_and_remind

_n = 0


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = S()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def captured(monkeypatch):
    """Capture reminder emails instead of sending them."""
    box = {"trial": [], "renewal": [], "expired": []}
    monkeypatch.setattr(email_svc, "send_trial_expiry_reminder_to_clinic",
                        lambda data: (box["trial"].append(data) or True))
    monkeypatch.setattr(email_svc, "send_renewal_reminder_to_clinic",
                        lambda data: (box["renewal"].append(data) or True))
    monkeypatch.setattr(email_svc, "send_trial_expired_to_clinic",
                        lambda data: (box["expired"].append(data) or True))
    return box


def _days(n: int) -> dt.datetime:
    """A timestamp whose (ts - now).days floors to exactly n."""
    return dt.datetime.utcnow() + dt.timedelta(days=n, hours=2)


def _clinic(db, **kw):
    global _n
    _n += 1
    defaults = dict(slug=f"ren-{_n}", name=f"Clinic {_n}", specialty="FM",
                    email=f"clinic{_n}@x.com", plan="professional",
                    monthly_rate=597.0, customer_password_hash="x", is_active=True)
    defaults.update(kw)
    c = Clinic(**defaults)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ── Pure bucket helper ────────────────────────────────────────────────────────

@pytest.mark.parametrize("days_left,expected", [
    (10, None), (8, None), (7, 7), (6, 7), (4, 7),
    (3, 3), (2, 3), (1, 1), (0, 1),
])
def test_reminder_bucket(days_left, expected):
    assert reminder_bucket(days_left) == expected


# ── Trial reminders fire once per 7/3/1 bucket (no daily spam) ─────────────────

def test_trial_reminders_dedup_to_three(db, captured):
    c = _clinic(db, subscription_status="trial", trial_ends_at=_days(7))

    # day 7 → one email
    check_trial_expiry_and_remind(db)
    assert len(captured["trial"]) == 1
    db.refresh(c); assert c.trial_reminder_day == 7

    # same day re-run → no new email
    check_trial_expiry_and_remind(db)
    assert len(captured["trial"]) == 1

    # day 5 → still bucket 7 → no new email
    c.trial_ends_at = _days(5); db.commit()
    check_trial_expiry_and_remind(db)
    assert len(captured["trial"]) == 1

    # day 3 → second email
    c.trial_ends_at = _days(3); db.commit()
    check_trial_expiry_and_remind(db)
    assert len(captured["trial"]) == 2
    db.refresh(c); assert c.trial_reminder_day == 3

    # day 1 → third email
    c.trial_ends_at = _days(1); db.commit()
    check_trial_expiry_and_remind(db)
    assert len(captured["trial"]) == 3
    db.refresh(c); assert c.trial_reminder_day == 1


def test_trial_no_reminder_outside_window(db, captured):
    _clinic(db, subscription_status="trial", trial_ends_at=_days(10))
    check_trial_expiry_and_remind(db)
    assert captured["trial"] == []


# ── Renewal reminders for active paid clinics ─────────────────────────────────

def test_renewal_reminders_dedup_to_three(db, captured):
    c = _clinic(db, subscription_status="active", subscription_ends_at=_days(7))

    check_renewals_and_remind(db)
    assert len(captured["renewal"]) == 1
    db.refresh(c); assert c.renewal_reminder_day == 7
    # email carries plan + amount + date
    assert captured["renewal"][0]["days_remaining"] == 7
    assert "$597" in captured["renewal"][0]["amount"]

    check_renewals_and_remind(db)          # same day, no repeat
    assert len(captured["renewal"]) == 1

    c.subscription_ends_at = _days(3); db.commit()
    check_renewals_and_remind(db)
    assert len(captured["renewal"]) == 2

    c.subscription_ends_at = _days(1); db.commit()
    check_renewals_and_remind(db)
    assert len(captured["renewal"]) == 3
    db.refresh(c); assert c.renewal_reminder_day == 1


def test_renewal_only_for_active_not_trial(db, captured):
    _clinic(db, subscription_status="trial", subscription_ends_at=_days(3))
    check_renewals_and_remind(db)
    assert captured["renewal"] == []


def test_activate_subscription_rearms_renewal(db, captured):
    c = _clinic(db, subscription_status="active",
                subscription_ends_at=_days(1), renewal_reminder_day=1)
    crud.activate_subscription(db, c.slug)
    db.refresh(c)
    assert c.renewal_reminder_day is None              # re-armed
    assert c.subscription_ends_at > _days(20)          # extended ~30d
