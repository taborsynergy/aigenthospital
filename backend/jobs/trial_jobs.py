"""Background jobs for trial management (expiry checks, reminders)."""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from backend.db import crud
from backend.services import email_svc
from backend.config import settings

logger = logging.getLogger(__name__)

# Send an expiry reminder once at each of these day-marks before the end date.
REMINDER_THRESHOLDS = (7, 3, 1)


def reminder_bucket(days_left: int, thresholds=REMINDER_THRESHOLDS):
    """The most-urgent threshold reached for `days_left`, or None if not yet due.

    days_left=8 -> None, 7..4 -> 7, 3..2 -> 3, 1 -> 1.
    """
    reached = [t for t in thresholds if days_left <= t]
    return min(reached) if reached else None


def _should_send(last_sent, bucket) -> bool:
    """Fire only when we reach a more-urgent (smaller) bucket than last time."""
    return bucket is not None and (last_sent is None or bucket < last_sent)


def check_trial_expiry_and_remind(db: Session) -> dict:
    """
    Daily job: expire trials past their end date and send expiry reminders
    at 7, 3 and 1 days remaining (once each, never on consecutive days).
    Returns: {expired, reminders_sent, errors}
    """
    stats = {"expired": 0, "reminders_sent": 0, "errors": 0}

    try:
        # Expire any trials past their trial_ends_at
        for clinic in crud.get_expired_trials(db):
            try:
                crud.expire_trial(db, clinic.id)
                logger.info(f"Trial expired: clinic_id={clinic.id}, slug={clinic.slug}")
                stats["expired"] += 1
                email_svc.send_trial_expired_to_clinic({
                    "clinic_name": clinic.name,
                    "clinic_email": clinic.email,
                    "upgrade_url": f"{settings.base_url.rstrip('/')}/c/{clinic.slug}",
                })
            except Exception as e:
                logger.error(f"Failed to expire trial for clinic {clinic.id}: {e}")
                stats["errors"] += 1

        # Reminders for trials inside the 7-day window (deduped at 7/3/1)
        for clinic in crud.get_trials_expiring_soon(db, days_until=max(REMINDER_THRESHOLDS) + 1):
            try:
                if not clinic.trial_ends_at:
                    continue
                days_left = (clinic.trial_ends_at - datetime.now(timezone.utc).replace(tzinfo=None)).days
                bucket = reminder_bucket(days_left)
                if not _should_send(clinic.trial_reminder_day, bucket):
                    continue
                ok = email_svc.send_trial_expiry_reminder_to_clinic({
                    "clinic_name": clinic.name,
                    "clinic_email": clinic.email,
                    "days_remaining": max(days_left, 0),
                    "trial_ends_at": clinic.trial_ends_at.strftime("%B %d, %Y"),
                    "upgrade_url": f"{settings.base_url.rstrip('/')}/c/{clinic.slug}",
                })
                if ok:
                    clinic.trial_reminder_day = bucket
                    db.commit()
                    logger.info(f"Trial reminder sent: clinic_id={clinic.id}, bucket={bucket}d")
                    stats["reminders_sent"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                logger.error(f"Failed to send reminder for clinic {clinic.id}: {e}")
                stats["errors"] += 1

        logger.info(f"Trial job completed: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Trial expiry check job failed: {e}")
        stats["errors"] += 1
        return stats
