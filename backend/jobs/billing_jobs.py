"""Background job: remind paying clinics before their monthly subscription renews.

Mirrors the trial reminder cadence — one email at 7, 3 and 1 days before
`subscription_ends_at`, deduped via `clinic.renewal_reminder_day`. The marker is
reset to None whenever the subscription is extended (see crud.activate_subscription),
so each billing cycle gets its own set of reminders.
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session
from backend.db import crud
from backend.plans import get_plan
from backend.services import email_svc
from backend.config import settings
from backend.jobs.trial_jobs import reminder_bucket, _should_send, REMINDER_THRESHOLDS

logger = logging.getLogger(__name__)


def check_renewals_and_remind(db: Session) -> dict:
    """Daily job: email active clinics 7/3/1 days before their renewal date."""
    stats = {"reminders_sent": 0, "errors": 0}

    try:
        for clinic in crud.get_active_subscriptions_ending_soon(db, days_until=max(REMINDER_THRESHOLDS) + 1):
            try:
                if not clinic.subscription_ends_at:
                    continue
                days_left = (clinic.subscription_ends_at - datetime.utcnow()).days
                bucket = reminder_bucket(days_left)
                if not _should_send(clinic.renewal_reminder_day, bucket):
                    continue

                plan = get_plan(clinic)
                rate = clinic.monthly_rate or plan.get("price")
                ok = email_svc.send_renewal_reminder_to_clinic({
                    "clinic_name": clinic.name,
                    "clinic_email": clinic.email,
                    "days_remaining": max(days_left, 0),
                    "renews_on": clinic.subscription_ends_at.strftime("%B %d, %Y"),
                    "plan": plan.get("name", clinic.plan or "your plan"),
                    "amount": f"${int(rate)}/mo" if rate else "",
                    "manage_url": f"{settings.base_url.rstrip('/')}/c/{clinic.slug}",
                })
                if ok:
                    clinic.renewal_reminder_day = bucket
                    db.commit()
                    logger.info(f"Renewal reminder sent: clinic_id={clinic.id}, bucket={bucket}d")
                    stats["reminders_sent"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                logger.error(f"Failed to send renewal reminder for clinic {clinic.id}: {e}")
                stats["errors"] += 1

        logger.info(f"Renewal job completed: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Renewal reminder job failed: {e}")
        stats["errors"] += 1
        return stats
