"""
Patient Recall Campaign service.

Recall campaigns send automated SMS outreach to patients who haven't visited
in a configurable period (3, 6, 12, or 24 months).

Default message template variables:
  {patient_name}  → patient's full name
  {first_name}    → first word of patient name
  {clinic_name}   → clinic display name
  {visit_type}    → campaign's visit type (e.g. "annual physical")
  {clinic_phone}  → clinic contact number

Entry points:
  run_campaign(db, clinic, campaign)           — called by cron or manual trigger
  run_all_active_campaigns(db)                  — called by daily cron
  preview_campaign(db, clinic_id, campaign)     — returns patients due, no SMS sent
  handle_book_reply(db, clinic, patient_phone)  — BOOK reply → send chat link
  handle_optout(db, clinic_id, patient_phone)   — OPTOUT/UNSUBSCRIBE → mark opted out
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = (
    "Hi {first_name}! It's been a while since your last visit at {clinic_name}. "
    "You may be due for your {visit_type}. "
    "Reply BOOK to schedule or STOP to unsubscribe."
)


def _render_message(template: str, patient_name: str, clinic_name: str,
                    visit_type: str, clinic_phone: str = "") -> str:
    first_name = patient_name.split()[0] if patient_name else "there"
    msg = (template or DEFAULT_TEMPLATE)
    msg = msg.replace("{patient_name}", patient_name)
    msg = msg.replace("{first_name}",   first_name)
    msg = msg.replace("{clinic_name}",  clinic_name)
    msg = msg.replace("{visit_type}",   visit_type)
    msg = msg.replace("{clinic_phone}", clinic_phone or clinic_name)
    return msg


def preview_campaign(db: Session, clinic_id: int, campaign) -> list[dict]:
    """
    Return patients who would receive a recall for this campaign — dry run, no SMS sent.
    Respects opt-outs and recent-send deduplication.
    """
    from backend.db.crud import (
        find_patients_due_for_recall, get_recall_log, is_opted_out,
    )
    due = find_patients_due_for_recall(db, clinic_id, campaign.interval_months)
    result = []
    cutoff = datetime.utcnow() - timedelta(days=campaign.interval_months * 30)

    for patient in due:
        phone = patient["patient_phone"]
        if is_opted_out(db, clinic_id, phone):
            continue
        # Skip if already recalled within the interval period
        recent = get_recall_log(db, clinic_id, phone, since=cutoff)
        already_sent = any(
            r.campaign_id == campaign.id for r in recent
            if r.status in ("sent", "booked")
        )
        if already_sent:
            continue
        result.append(patient)
    return result


def run_campaign(db: Session, clinic, campaign) -> dict:
    """
    Send recall SMS to all patients due for this campaign.
    Returns stats: {sent, skipped, errors, opted_out}.
    """
    from backend.plans import can_use_sms
    from backend.db.crud import (
        find_patients_due_for_recall, get_recall_log,
        is_opted_out, log_recall_sent,
    )
    from backend.services.twilio_svc import send_sms

    stats = {"sent": 0, "skipped": 0, "errors": 0, "opted_out": 0}

    if not can_use_sms(clinic):
        logger.info("Recall skipped — SMS not in plan: clinic=%s", clinic.slug)
        return stats

    if not campaign.is_active:
        return stats

    due = find_patients_due_for_recall(db, clinic.id, campaign.interval_months)
    cutoff = datetime.utcnow() - timedelta(days=campaign.interval_months * 30)
    from_number = clinic.twilio_phone or None

    for patient in due:
        phone = patient["patient_phone"]
        name  = patient["patient_name"]

        if is_opted_out(db, clinic.id, phone):
            stats["opted_out"] += 1
            continue

        # Skip if already sent for this campaign within the interval
        recent = get_recall_log(db, clinic.id, phone, since=cutoff)
        already_sent = any(
            r.campaign_id == campaign.id for r in recent
            if r.status in ("sent", "booked")
        )
        if already_sent:
            stats["skipped"] += 1
            continue

        message = _render_message(
            campaign.message_template,
            patient_name=name,
            clinic_name=clinic.name,
            visit_type=campaign.visit_type,
            clinic_phone=clinic.phone or "",
        )

        ok = send_sms(phone, message, from_=from_number)
        status = "sent" if ok else "failed"
        log_recall_sent(db, campaign.id, clinic.id, name, phone, status)

        if ok:
            stats["sent"] += 1
            logger.info("Recall sent: campaign=%s patient=%s to=%s",
                        campaign.id, name, phone)
        else:
            stats["errors"] += 1
            logger.warning("Recall failed: campaign=%s patient=%s to=%s",
                           campaign.id, name, phone)

    return stats


def run_all_active_campaigns(db: Session) -> dict:
    """
    Daily cron entry point. Runs all active recall campaigns across all clinics.
    Returns aggregated stats.
    """
    from backend.db.crud import list_clinics, list_recall_campaigns
    from backend.plans import can_use_sms

    totals = {"campaigns_run": 0, "sent": 0, "skipped": 0, "errors": 0, "opted_out": 0}
    clinics = list_clinics(db)

    for clinic in clinics:
        if not can_use_sms(clinic):
            continue
        campaigns = list_recall_campaigns(db, clinic.id)
        for campaign in campaigns:
            if not campaign.is_active:
                continue
            stats = run_campaign(db, clinic, campaign)
            totals["campaigns_run"] += 1
            for k in ("sent", "skipped", "errors", "opted_out"):
                totals[k] += stats.get(k, 0)

    logger.info("Recall run complete: %s", totals)
    return totals


def handle_book_reply(db: Session, clinic, patient_phone: str) -> Optional[str]:
    """
    Patient replied BOOK to a recall SMS — send them the clinic chat link.
    Also marks the most recent recall log as 'booked'.
    """
    from backend.config import settings
    from backend.db.crud import get_recall_log

    chat_url = f"{settings.base_url}/chat/{clinic.slug}"

    # Mark most recent recall as booked
    recent = get_recall_log(
        db, clinic.id, patient_phone,
        since=datetime.utcnow() - timedelta(days=365),
    )
    if recent:
        latest = max(recent, key=lambda r: r.sent_at)
        latest.status = "booked"
        db.commit()

    return (
        f"Great! You can book your appointment here: {chat_url}\n"
        f"Or call us at {clinic.phone or clinic.name}."
    )


def handle_optout(db: Session, clinic_id: int, patient_phone: str) -> str:
    """Patient replied OPTOUT/UNSUBSCRIBE — mark as opted out and confirm."""
    from backend.db.crud import mark_recall_opted_out
    mark_recall_opted_out(db, clinic_id, patient_phone)
    logger.info("Recall opt-out: clinic=%d phone=%s", clinic_id, patient_phone)
    return "You've been unsubscribed from appointment reminders. Reply START to resubscribe."
