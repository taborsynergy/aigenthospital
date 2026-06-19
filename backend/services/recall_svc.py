"""
Patient Recall Campaign service (EMAIL).

Recall campaigns send automated EMAIL outreach to patients who haven't visited
in a configurable period (3, 6, 12, or 24 months).

Message template variables:
  {patient_name} {first_name} {clinic_name} {visit_type} {clinic_phone}

Entry points:
  run_campaign(db, clinic, campaign)        — called by cron or manual trigger
  run_all_active_campaigns(db)              — daily cron
  preview_campaign(db, clinic_id, campaign) — patients due, no email sent

Recall is gated to Growth/Enterprise plans. Patient contact key is the email
address. Every recall email carries a signed unsubscribe link
(GET /api/unsubscribe) for CAN-SPAM compliance; opted-out patients are skipped.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = (
    "Hi {first_name}! It's been a while since your last visit at {clinic_name}. "
    "You may be due for your {visit_type}."
)


def _render_message(template: str, patient_name: str, clinic_name: str,
                    visit_type: str, clinic_phone: str = "") -> str:
    first_name = patient_name.split()[0] if patient_name else "there"
    msg = (template or DEFAULT_TEMPLATE)
    msg = msg.replace("{patient_name}", patient_name)
    msg = msg.replace("{first_name}", first_name)
    msg = msg.replace("{clinic_name}", clinic_name)
    msg = msg.replace("{visit_type}", visit_type)
    msg = msg.replace("{clinic_phone}", clinic_phone or clinic_name)
    return msg


def _email_body(message: str, clinic, unsub_url: str = "") -> str:
    from backend.config import settings
    lines = [message, ""]
    chat_url = f"{settings.base_url}/c/{clinic.slug}"
    lines.append(f"Book your appointment here: {chat_url}")
    if getattr(clinic, "phone", ""):
        lines.append(f"Or call us at {clinic.phone}.")
    lines += ["", f"— {clinic.name}"]
    if unsub_url:
        lines += ["", "—" * 20,
                  f"Don't want these reminders? Unsubscribe: {unsub_url}"]
    return "\n".join(lines)


def preview_campaign(db: Session, clinic_id: int, campaign) -> list[dict]:
    """Patients who would receive this recall — dry run, no email sent."""
    from backend.db.crud import find_patients_due_for_recall, get_recall_log, is_opted_out
    due = find_patients_due_for_recall(db, clinic_id, campaign.interval_months)
    cutoff = datetime.utcnow() - timedelta(days=campaign.interval_months * 30)
    result = []
    for patient in due:
        email = patient["patient_email"]
        if is_opted_out(db, clinic_id, email):
            continue
        recent = get_recall_log(db, clinic_id, email, since=cutoff)
        if any(r.campaign_id == campaign.id for r in recent if r.status in ("sent", "booked")):
            continue
        result.append(patient)
    return result


def run_campaign(db: Session, clinic, campaign) -> dict:
    """Email recall to all patients due for this campaign. Returns stats."""
    from backend.plans import can_use_reminders
    from backend.db.crud import (
        find_patients_due_for_recall, get_recall_log, is_opted_out, log_recall_sent,
    )
    from backend.services.email_svc import send_email

    stats = {"sent": 0, "skipped": 0, "errors": 0, "opted_out": 0}
    if not can_use_reminders(clinic):
        logger.info("Recall skipped — not in plan: clinic=%s", clinic.slug)
        return stats
    if not campaign.is_active:
        return stats

    due = find_patients_due_for_recall(db, clinic.id, campaign.interval_months)
    cutoff = datetime.utcnow() - timedelta(days=campaign.interval_months * 30)

    for patient in due:
        email = patient["patient_email"]
        name = patient["patient_name"]

        if is_opted_out(db, clinic.id, email):
            stats["opted_out"] += 1
            continue

        recent = get_recall_log(db, clinic.id, email, since=cutoff)
        if any(r.campaign_id == campaign.id for r in recent if r.status in ("sent", "booked")):
            stats["skipped"] += 1
            continue

        message = _render_message(
            campaign.message_template, patient_name=name, clinic_name=clinic.name,
            visit_type=campaign.visit_type, clinic_phone=getattr(clinic, "phone", "") or "",
        )
        subject = f"You may be due for your {campaign.visit_type} — {clinic.name}"
        from backend.unsub import make_unsub_token
        from backend.config import settings
        unsub_url = f"{settings.base_url}/api/unsubscribe?token={make_unsub_token(clinic.id, email)}"
        ok = send_email(to=email, subject=subject, body=_email_body(message, clinic, unsub_url))
        log_recall_sent(db, campaign.id, clinic.id, name, email, "sent" if ok else "failed")

        if ok:
            stats["sent"] += 1
            logger.info("Recall email sent: campaign=%s patient=%s to=%s", campaign.id, name, email)
        else:
            stats["errors"] += 1
            logger.warning("Recall email failed: campaign=%s patient=%s", campaign.id, name)

    return stats


def run_all_active_campaigns(db: Session) -> dict:
    """Daily cron entry point. Runs all active recall campaigns across all clinics."""
    from backend.db.crud import list_clinics, list_recall_campaigns
    from backend.plans import can_use_reminders

    totals = {"campaigns_run": 0, "sent": 0, "skipped": 0, "errors": 0, "opted_out": 0}
    for clinic in list_clinics(db):
        if not can_use_reminders(clinic):
            continue
        for campaign in list_recall_campaigns(db, clinic.id):
            if not campaign.is_active:
                continue
            stats = run_campaign(db, clinic, campaign)
            totals["campaigns_run"] += 1
            for k in ("sent", "skipped", "errors", "opted_out"):
                totals[k] += stats.get(k, 0)

    logger.info("Recall run complete: %s", totals)
    return totals
