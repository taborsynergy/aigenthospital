"""
Onboarding email sequence — runs daily, sends timed emails to new clinics.

Schedule (days since signup):
  Day 0  → Welcome + first steps           (sent at signup via send_onboarding_day0)
  Day 1  → Widget / SMS check-in
  Day 3  → Power tips (insurance + recall)
  Day 7  → Halfway check + upgrade nudge
  Day 12 → Trial ending soon + activate CTA
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from backend.db.crud import get_db_clinics_for_onboarding
from backend.services.email_svc import (
    send_onboarding_day1,
    send_onboarding_day3,
    send_onboarding_day7,
    send_onboarding_day12,
)

logger = logging.getLogger(__name__)

# Map: days_since_signup → (minimum emails_sent_value, sender_fn, next_emails_sent_value)
_SEQUENCE = [
    (1,  0,  send_onboarding_day1,  1),
    (3,  1,  send_onboarding_day3,  3),
    (7,  3,  send_onboarding_day7,  7),
    (12, 7,  send_onboarding_day12, 12),
]


def run_onboarding_email_sequence(db: Session) -> dict:
    """
    Daily job: check all trial/active clinics and send the next onboarding
    email in sequence based on how many days since they signed up.
    """
    stats = {"sent": 0, "skipped": 0, "errors": 0}
    now = datetime.utcnow()

    try:
        clinics = get_db_clinics_for_onboarding(db)
        for clinic in clinics:
            if not clinic.created_at:
                continue
            days_since = (now - clinic.created_at).days
            sent_level = clinic.onboarding_emails_sent or 0

            for target_day, required_sent, send_fn, new_level in _SEQUENCE:
                if days_since >= target_day and sent_level == required_sent:
                    try:
                        data = {
                            "clinic_name":   clinic.name,
                            "clinic_email":  clinic.email,
                            "first_name":    clinic.name.split()[0] if clinic.name else "there",
                            "slug":          clinic.slug,
                            "plan":          clinic.plan or "starter",
                            "trial_ends_at": (
                                clinic.trial_ends_at.strftime("%B %d, %Y")
                                if clinic.trial_ends_at else "soon"
                            ),
                            "portal_url": f"https://aifrontdesk.taborsynergy.com/c/{clinic.slug}",
                        }
                        success = send_fn(data)
                        if success:
                            clinic.onboarding_emails_sent = new_level
                            db.commit()
                            logger.info(
                                "Onboarding Day%s sent: clinic=%s email=%s",
                                target_day, clinic.slug, clinic.email,
                            )
                            stats["sent"] += 1
                        else:
                            stats["errors"] += 1
                    except Exception as e:
                        logger.error(
                            "Onboarding email error: clinic=%s day=%s err=%s",
                            clinic.slug, target_day, e,
                        )
                        stats["errors"] += 1
                    break  # only send one email per clinic per run
                else:
                    stats["skipped"] += 1

    except Exception as e:
        logger.error("Onboarding job failed: %s", e)
        stats["errors"] += 1

    logger.info("Onboarding job: %s", stats)
    return stats
