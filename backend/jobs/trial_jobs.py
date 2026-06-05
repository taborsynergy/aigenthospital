"""Background jobs for trial management (expiry checks, reminders)."""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from backend.db import crud
from backend.services import email_svc

logger = logging.getLogger(__name__)


def check_trial_expiry_and_remind(db: Session) -> dict:
    """
    Background job: run daily to check for expired trials and send reminders.
    Returns: {expired: count, reminders_sent: count}
    """
    stats = {"expired": 0, "reminders_sent": 0, "errors": 0}

    try:
        # Expire any trials past their trial_ends_at
        expired_clinics = crud.get_expired_trials(db)
        for clinic in expired_clinics:
            try:
                crud.expire_trial(db, clinic.id)
                logger.info(f"Trial expired: clinic_id={clinic.id}, slug={clinic.slug}")
                stats["expired"] += 1

                # Send expiry email to clinic
                email_svc.send_trial_expired_to_clinic({
                    "clinic_name": clinic.name,
                    "clinic_email": clinic.email,
                    "upgrade_url": f"https://app.taborsynergy.com/clinic/{clinic.slug}/upgrade",
                })
            except Exception as e:
                logger.error(f"Failed to expire trial for clinic {clinic.id}: {e}")
                stats["errors"] += 1

        # Send reminders for trials expiring in 5+ days
        expiring_soon = crud.get_trials_expiring_soon(db, days_until=5)
        for clinic in expiring_soon:
            try:
                # Calculate days remaining
                if clinic.trial_ends_at:
                    days_left = (clinic.trial_ends_at - datetime.utcnow()).days
                    if days_left > 0 and days_left <= 5:
                        email_svc.send_trial_expiry_reminder_to_clinic({
                            "clinic_name": clinic.name,
                            "clinic_email": clinic.email,
                            "days_remaining": days_left,
                            "trial_ends_at": clinic.trial_ends_at.strftime("%B %d, %Y"),
                            "upgrade_url": f"https://app.taborsynergy.com/clinic/{clinic.slug}/upgrade",
                        })
                        logger.info(f"Trial reminder sent: clinic_id={clinic.id}, days_left={days_left}")
                        stats["reminders_sent"] += 1
            except Exception as e:
                logger.error(f"Failed to send reminder for clinic {clinic.id}: {e}")
                stats["errors"] += 1

        logger.info(f"Trial job completed: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Trial expiry check job failed: {e}")
        stats["errors"] += 1
        return stats
