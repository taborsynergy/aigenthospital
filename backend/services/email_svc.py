"""
Simple SMTP email sender for internal notifications (quote requests, etc.).
Configure SMTP_HOST / SMTP_USER / SMTP_PASS in your .env.
If SMTP is not configured the send is skipped and the submission is only logged.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from backend.config import settings

logger = logging.getLogger(__name__)


def send_trial_signup_email(data: dict) -> bool:
    """
    Notify admin when a new trial clinic signs up.
    Returns True if sent, False if SMTP not configured or send fails.
    """
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
        logger.warning("SMTP not configured — trial signup not emailed. Details: %s", data)
        return False

    subject = f"New Trial Signup — {data.get('practice_name', 'Unknown Practice')}"

    body_lines = [
        "A new practice just signed up for a 14-day free trial on Tabor Synergy.",
        "",
        f"Practice Name:  {data.get('practice_name', '—')}",
        f"Specialty:      {data.get('specialty', '—')}",
        f"Contact Email:  {data.get('contact_email', '—')}",
        f"Phone:          {data.get('phone', '—') or '—'}",
        f"Plan:           {data.get('plan', '—').title()}",
        f"Monthly Rate:   ${data.get('monthly_rate', '—')}",
        f"Trial Ends:     {data.get('trial_ends_at', '—')}",
        f"Clinic Slug:    {data.get('slug', '—')}",
        f"Chat URL:       {data.get('chat_url', '—')}",
        "",
        "— Tabor Synergy automated notification",
    ]
    body = "\n".join(body_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"]  = subject
    msg["From"]     = settings.smtp_user
    msg["To"]       = settings.notify_email
    msg["Reply-To"] = data.get("contact_email", settings.smtp_user)
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.sendmail(settings.smtp_user, settings.notify_email, msg.as_string())
        logger.info("Trial signup email sent for %s", data.get("contact_email"))
        return True
    except Exception:
        logger.exception("Failed to send trial signup email")
        return False


def send_quote_email(data: dict) -> bool:
    """
    Send a White Label quote request to the notify_email address.
    Returns True if sent, False if SMTP is not configured or send fails.
    """
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
        logger.warning(
            "SMTP not configured — quote request not emailed. Details: %s", data
        )
        return False

    subject = f"White Label Quote Request — {data.get('company', 'Unknown')}"

    body_lines = [
        "A new White Label quote request has been submitted via the website.",
        "",
        f"Name:              {data.get('full_name', '—')}",
        f"Email:             {data.get('email', '—')}",
        f"Organization:      {data.get('company', '—')}",
        f"Phone:             {data.get('phone', '—')}",
        f"Locations:         {data.get('locations', '—')}",
        f"Current EHR/PMS:   {data.get('pms', '—')}",
        "",
        "Message:",
        data.get('message', '(none)'),
        "",
        "— Tabor Synergy automated notification",
    ]
    body = "\n".join(body_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.smtp_user
    msg["To"]      = settings.notify_email
    msg["Reply-To"] = data.get("email", settings.smtp_user)
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.sendmail(settings.smtp_user, settings.notify_email, msg.as_string())
        logger.info("Quote email sent for %s", data.get("email"))
        return True
    except Exception:
        logger.exception("Failed to send quote email")
        return False
