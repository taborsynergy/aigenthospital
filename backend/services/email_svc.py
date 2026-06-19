"""
SMTP email sender for internal notifications (trial signups, quote requests).
Configure SMTP_HOST / SMTP_USER / SMTP_PASS in your .env or Render env vars.

Gmail setup:
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=465          ← use 465 (SSL) or 587 (STARTTLS); 465 is more reliable on Render
  SMTP_USER=your-gmail@gmail.com
  SMTP_PASS=xxxx xxxx xxxx xxxx   ← 16-char App Password (2FA must be on)
  NOTIFY_EMAIL=admin@tabor.taborsynergy.com

Emails are always CC'd to SMTP_USER so you receive them in your sending inbox
even if NOTIFY_EMAIL uses a domain without email hosting.
"""
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from backend.config import settings

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _recipients() -> List[str]:
    """Return deduplicated list: notify_email + smtp_user (as fallback CC)."""
    addrs = [settings.notify_email]
    if settings.smtp_user and settings.smtp_user not in addrs:
        addrs.append(settings.smtp_user)
    return addrs


def _build_msg(subject: str, plain: str, html: str, reply_to: str = "") -> MIMEMultipart:
    recipients = _recipients()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Tabor Synergy Alerts <{settings.smtp_user}>"
    msg["To"]      = recipients[0]
    if len(recipients) > 1:
        msg["Cc"]  = ", ".join(recipients[1:])
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))
    return msg


def _email_from() -> str:
    """Verified sender address for outbound mail."""
    return settings.email_from or settings.smtp_user or settings.notify_email


def _extract_parts(msg: MIMEMultipart) -> tuple:
    """Pull (plain, html) bodies out of a MIMEMultipart alternative message."""
    plain, html = "", ""
    for part in msg.walk():
        ct = part.get_content_type()
        payload = part.get_payload(decode=True)
        text = payload.decode("utf-8", errors="replace") if payload else ""
        if ct == "text/plain" and not plain:
            plain = text
        elif ct == "text/html" and not html:
            html = text
    return plain, html


def _sendgrid_send(to_list: List[str], subject: str, plain: str, html: str = "", reply_to: str = "") -> bool:
    """Send email over HTTPS via the SendGrid API (used when SENDGRID_API_KEY is set)."""
    import httpx
    content = []
    if plain:
        content.append({"type": "text/plain", "value": plain})
    if html:
        content.append({"type": "text/html", "value": html})
    if not content:
        content = [{"type": "text/plain", "value": ""}]
    payload = {
        "personalizations": [{"to": [{"email": a} for a in to_list]}],
        "from": {"email": _email_from(), "name": "Tabor Synergy"},
        "subject": subject or "(no subject)",
        "content": content,
    }
    if reply_to:
        payload["reply_to"] = {"email": reply_to}
    try:
        r = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {settings.sendgrid_api_key}",
                     "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if r.status_code in (200, 201, 202):
            logger.info("Email sent via SendGrid to %s", to_list)
            return True
        logger.error("SendGrid send failed: HTTP %s: %s", r.status_code, r.text[:300])
        return False
    except Exception as exc:
        logger.error("SendGrid send error to=%s: %s: %s", to_list, type(exc).__name__, exc)
        return False


def _send(msg: MIMEMultipart) -> bool:
    """
    Send via SendGrid HTTP API if configured (works where SMTP is blocked),
    else fall back to SMTP: SSL (465) first, then STARTTLS (587).
    """
    recipients = _recipients()

    if settings.sendgrid_api_key:
        plain, html = _extract_parts(msg)
        return _sendgrid_send(recipients, msg["Subject"] or "", plain, html, msg.get("Reply-To", ""))

    def _via_ssl() -> None:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, 465, context=ctx, timeout=15) as smtp:
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.sendmail(settings.smtp_user, recipients, msg.as_string())

    def _via_starttls() -> None:
        port = settings.smtp_port or 587
        with smtplib.SMTP(settings.smtp_host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.sendmail(settings.smtp_user, recipients, msg.as_string())

    for attempt, send_fn in [("SSL/465", _via_ssl), ("STARTTLS/587", _via_starttls)]:
        try:
            send_fn()
            logger.info("Email sent via %s to %s", attempt, recipients)
            return True
        except Exception as exc:
            logger.warning("Email attempt %s failed: %s: %s", attempt, type(exc).__name__, exc)

    logger.error(
        "All email delivery attempts failed. "
        "Check SMTP_HOST/SMTP_USER/SMTP_PASS in Render env vars. "
        "For Gmail: ensure 2FA is on and SMTP_PASS is a 16-char App Password."
    )
    return False


def send_email(to: str, subject: str, body: str) -> bool:
    """
    Generic plain-text email to an arbitrary recipient (clinic users, password resets).
    Uses SendGrid HTTP API if configured, else SMTP. Returns False gracefully if
    neither is configured — never raises, so callers never crash on email failure.
    """
    if settings.sendgrid_api_key:
        return _sendgrid_send([to], subject, body, "")

    if not settings.smtp_host or not settings.smtp_user:
        logger.warning("send_email skipped — email not configured (to=%s, subject=%s)", to, subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Aria AI <{settings.smtp_user}>"
    msg["To"]      = to
    msg.attach(MIMEText(body, "plain"))

    def _via_ssl() -> None:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, 465, context=ctx, timeout=15) as smtp:
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.sendmail(settings.smtp_user, [to], msg.as_string())

    def _via_starttls() -> None:
        port = settings.smtp_port or 587
        with smtplib.SMTP(settings.smtp_host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.sendmail(settings.smtp_user, [to], msg.as_string())

    for attempt, send_fn in [("SSL/465", _via_ssl), ("STARTTLS/587", _via_starttls)]:
        try:
            send_fn()
            logger.info("send_email sent via %s to %s", attempt, to)
            return True
        except Exception as exc:
            logger.warning("send_email attempt %s failed: %s: %s", attempt, type(exc).__name__, exc)

    logger.error("send_email: all delivery attempts failed for %s", to)
    return False


def send_booking_confirmation_email(clinic, appt) -> bool:
    """
    Email a booking confirmation to the PATIENT (appt.patient_email).
    Best-effort: returns False if no email / not configured. Available on all plans
    (included on all plans).
    """
    to = (getattr(appt, "patient_email", "") or "").strip()
    if not to:
        return False

    clinic_name = getattr(clinic, "name", "your clinic")
    lines = [
        f"Hi {getattr(appt, 'patient_name', '') or 'there'},",
        "",
        f"Your appointment at {clinic_name} is confirmed!",
        "",
        f"Confirmation #: {getattr(appt, 'confirmation_number', '')}",
        f"Service:        {getattr(appt, 'appointment_type', '')}",
        f"When:           {getattr(appt, 'appointment_datetime', '')}",
    ]
    if getattr(appt, "provider", ""):
        lines.append(f"Provider:       {appt.provider}")
    if getattr(clinic, "address", ""):
        lines.append(f"Where:          {clinic.address}")
    lines += [
        "",
        "What to bring: your insurance card, a photo ID, and a list of any current medications.",
    ]
    if getattr(clinic, "cancellation_policy", ""):
        lines += ["", clinic.cancellation_policy]
    if getattr(clinic, "phone", ""):
        lines += ["", f"Need to reschedule or have questions? Call us at {clinic.phone}."]
    lines += ["", "See you then!", f"— {clinic_name}"]

    subject = f"Your appointment is confirmed — {clinic_name}"
    return send_email(to=to, subject=subject, body="\n".join(lines))


# ── public API ────────────────────────────────────────────────────────────────

def send_trial_signup_email(data: dict) -> bool:
    """Notify admin when a new trial clinic signs up."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        logger.warning(
            "SMTP not configured — trial signup NOT emailed. "
            "Set SMTP_HOST, SMTP_USER, SMTP_PASS in Render environment variables. "
            "Signup details: %s", data
        )
        return False

    practice = data.get("practice_name", "Unknown Practice")
    subject  = f"[Tabor Synergy] New Trial Signup — {practice}"

    plain = "\n".join([
        "A new practice just signed up for a 14-day free trial on Tabor Synergy.",
        "",
        f"Practice Name:  {data.get('practice_name', '—')}",
        f"Specialty:      {data.get('specialty', '—')}",
        f"Contact Email:  {data.get('contact_email', '—')}",
        f"Phone:          {data.get('phone') or '—'}",
        f"Plan:           {data.get('plan', '—').title()}",
        f"Monthly Rate:   ${data.get('monthly_rate', '—')}",
        f"Trial Ends:     {data.get('trial_ends_at', '—')}",
        f"Clinic Slug:    {data.get('slug', '—')}",
        f"Chat URL:       {data.get('chat_url', '—')}",
        "",
        "— Tabor Synergy automated notification",
    ])

    html = f"""
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#0F3D91;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">New Trial Signup</h2>
  <p style="color:#a0c4ff;margin:4px 0 0">Tabor Synergy — AI Medical Front Desk</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p style="margin-top:0">A new practice just signed up for a <strong>14-day free trial</strong>.</p>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:8px;color:#666;width:40%">Practice Name</td>
        <td style="padding:8px;font-weight:bold">{data.get('practice_name','—')}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Specialty</td>
        <td style="padding:8px">{data.get('specialty','—')}</td></tr>
    <tr><td style="padding:8px;color:#666">Contact Email</td>
        <td style="padding:8px"><a href="mailto:{data.get('contact_email','')}">{data.get('contact_email','—')}</a></td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Phone</td>
        <td style="padding:8px">{data.get('phone') or '—'}</td></tr>
    <tr><td style="padding:8px;color:#666">Plan</td>
        <td style="padding:8px;font-weight:bold;color:#0F3D91">{data.get('plan','—').title()}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Monthly Rate</td>
        <td style="padding:8px">${data.get('monthly_rate','—')}/mo</td></tr>
    <tr><td style="padding:8px;color:#666">Trial Ends</td>
        <td style="padding:8px">{data.get('trial_ends_at','—')}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Clinic Slug</td>
        <td style="padding:8px"><code>{data.get('slug','—')}</code></td></tr>
    <tr><td style="padding:8px;color:#666">Chat URL</td>
        <td style="padding:8px"><a href="{data.get('chat_url','')}">{data.get('chat_url','—')}</a></td></tr>
  </table>
  <p style="margin-top:20px;font-size:12px;color:#999">Tabor Synergy — automated notification</p>
</div>
</body></html>
"""

    msg = _build_msg(subject, plain, html, reply_to=data.get("contact_email", ""))
    return _send(msg)


def send_upgrade_request_email(data: dict) -> bool:
    """Notify admin when a clinic requests a plan upgrade."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        logger.warning("SMTP not configured — upgrade request NOT emailed. Details: %s", data)
        return False

    clinic   = data.get("clinic_name", "Unknown")
    subject  = f"[Tabor Synergy] Upgrade Request — {clinic} → {data.get('new_plan','').title()}"

    plain = "\n".join([
        f"{clinic} has requested a plan upgrade.",
        "",
        f"Clinic:       {clinic}",
        f"Email:        {data.get('clinic_email', '—')}",
        f"Current Plan: {data.get('current_plan', '—').title()}",
        f"New Plan:     {data.get('new_plan', '—').title()} (${data.get('new_price', '—')}/mo)",
        f"PayPal Link:  {data.get('paypal_url', '—')}",
        "",
        "Action required: after payment is received, activate the new plan in the admin dashboard.",
        "  1. Open the admin panel",
        f"  2. Find clinic: {data.get('clinic_slug', '—')}",
        "  3. Edit the clinic, set the new plan and rate, then click Activate 30d",
        "",
        "— Tabor Synergy automated notification",
    ])

    html = f"""
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#7C3AED;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Plan Upgrade Request</h2>
  <p style="color:#e9d5ff;margin:4px 0 0">Tabor Synergy — AI Medical Front Desk</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p style="margin-top:0"><strong>{clinic}</strong> has requested a plan upgrade.</p>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:8px;color:#666;width:40%">Clinic</td>
        <td style="padding:8px;font-weight:bold">{data.get('clinic_name','—')}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Email</td>
        <td style="padding:8px"><a href="mailto:{data.get('clinic_email','')}">{data.get('clinic_email','—')}</a></td></tr>
    <tr><td style="padding:8px;color:#666">Current Plan</td>
        <td style="padding:8px">{data.get('current_plan','—').title()}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Requested Plan</td>
        <td style="padding:8px;font-weight:bold;color:#7C3AED">{data.get('new_plan','—').title()} — ${data.get('new_price','—')}/mo</td></tr>
    <tr><td style="padding:8px;color:#666">PayPal Link</td>
        <td style="padding:8px"><a href="{data.get('paypal_url','')}" style="background:#003087;color:#fff;padding:6px 14px;border-radius:4px;text-decoration:none;font-weight:bold">Open PayPal →</a></td></tr>
  </table>
  <div style="margin-top:20px;padding:14px;background:#EDE9FE;border-left:4px solid #7C3AED;border-radius:4px">
    <strong>Action required:</strong> After confirming payment, go to the admin panel,
    find <code>{data.get('clinic_slug','—')}</code>, update the plan to
    <strong>{data.get('new_plan','—').title()}</strong> and click <strong>Activate 30d</strong>.
  </div>
  <p style="margin-top:20px;font-size:12px;color:#999">Tabor Synergy — automated notification</p>
</div>
</body></html>
"""
    msg = _build_msg(subject, plain, html)
    return _send(msg)


def send_subscription_activated_email(data: dict) -> bool:
    """Notify clinic when their PayPal subscription is manually activated by admin."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        return False

    clinic  = data.get("clinic_name", "Your clinic")
    plan    = data.get("plan", "professional").title()
    rate    = data.get("rate", "—")
    ends_at = data.get("ends_at", "—")
    portal  = data.get("portal_url", settings.base_url)
    subject = f"[Tabor Synergy] Subscription Activated — {clinic} ({plan})"

    plain = "\n".join([
        f"Great news! Your {plan} subscription for {clinic} is now active.",
        "",
        f"Plan:          {plan}",
        f"Monthly rate:  ${rate}/mo",
        f"Active until:  {ends_at}",
        f"Portal:        {portal}",
        "",
        "Thank you for choosing Tabor Synergy!",
        "— The Tabor Synergy Team",
    ])
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#059669;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Subscription Activated!</h2>
  <p style="color:#d1fae5;margin:4px 0 0">Tabor Synergy — AI Medical Front Desk</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p style="margin-top:0">Your <strong>{plan}</strong> subscription for <strong>{clinic}</strong> is now active.</p>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:8px;color:#666;width:40%">Plan</td>
        <td style="padding:8px;font-weight:bold;color:#059669">{plan}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Monthly Rate</td>
        <td style="padding:8px">${rate}/mo</td></tr>
    <tr><td style="padding:8px;color:#666">Active Until</td>
        <td style="padding:8px">{ends_at}</td></tr>
  </table>
  <div style="margin-top:20px;text-align:center">
    <a href="{portal}" style="background:#059669;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:700">
      Go to Your Portal →
    </a>
  </div>
  <p style="margin-top:20px;font-size:12px;color:#999">Tabor Synergy — automated notification</p>
</div></body></html>"""
    msg = _build_msg(subject, plain, html, reply_to=settings.notify_email)
    return _send(msg)


def send_subscription_cancelled_email(data: dict) -> bool:
    """Notify clinic when their subscription is cancelled."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        return False

    clinic  = data.get("clinic_name", "Your clinic")
    email   = data.get("clinic_email", "")
    subject = f"[Tabor Synergy] Subscription Cancelled — {clinic}"

    plain = "\n".join([
        f"Your Tabor Synergy subscription for {clinic} has been cancelled.",
        "",
        "Your AI front desk will remain active until the end of your current billing period.",
        "After that, patients will no longer be able to chat with Aria.",
        "",
        f"To reactivate, contact us at {settings.notify_email}",
        "— The Tabor Synergy Team",
    ])
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#6B7280;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Subscription Cancelled</h2>
  <p style="color:#e5e7eb;margin:4px 0 0">Tabor Synergy — AI Medical Front Desk</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p>Your subscription for <strong>{clinic}</strong> has been cancelled.</p>
  <p>Aria will remain active until the end of your current billing period. After that, the chat service will be disabled.</p>
  <p>Changed your mind? <a href="mailto:{settings.notify_email}">Contact us</a> to reactivate.</p>
  <p style="font-size:12px;color:#999;margin-top:20px">Tabor Synergy — automated billing notification</p>
</div></body></html>"""
    msg = _build_msg(subject, plain, html)
    if email:
        msg.replace_header("To", email)
    return _send(msg)


def send_quote_email(data: dict) -> bool:
    """Send a White Label quote request to the notify_email address."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        logger.warning(
            "SMTP not configured — quote request NOT emailed. "
            "Set SMTP_HOST, SMTP_USER, SMTP_PASS in Render environment variables. "
            "Quote details: %s", data
        )
        return False

    company  = data.get("company", "Unknown")
    subject  = f"[Tabor Synergy] White Label Quote — {company}"

    plain = "\n".join([
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
        data.get("message", "(none)"),
        "",
        "— Tabor Synergy automated notification",
    ])

    html = f"""
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#14B8A6;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">White Label Quote Request</h2>
  <p style="color:#ccfbf1;margin:4px 0 0">Tabor Synergy — AI Medical Front Desk</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p style="margin-top:0">A new White Label quote request has been submitted.</p>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:8px;color:#666;width:40%">Name</td>
        <td style="padding:8px;font-weight:bold">{data.get('full_name','—')}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Email</td>
        <td style="padding:8px"><a href="mailto:{data.get('email','')}">{data.get('email','—')}</a></td></tr>
    <tr><td style="padding:8px;color:#666">Organization</td>
        <td style="padding:8px">{data.get('company','—')}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Phone</td>
        <td style="padding:8px">{data.get('phone') or '—'}</td></tr>
    <tr><td style="padding:8px;color:#666">Locations</td>
        <td style="padding:8px">{data.get('locations') or '—'}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Current EHR/PMS</td>
        <td style="padding:8px">{data.get('pms') or '—'}</td></tr>
  </table>
  {"<div style='margin-top:16px;padding:12px;background:#fff;border-left:4px solid #14B8A6'><strong>Message:</strong><br>" + data.get('message','(none)') + "</div>" if data.get('message') else ""}
  <p style="margin-top:20px;font-size:12px;color:#999">Tabor Synergy — automated notification</p>
</div>
</body></html>
"""

    msg = _build_msg(subject, plain, html, reply_to=data.get("email", ""))
    return _send(msg)


# ── Trial Emails ──────────────────────────────────────────────────────────────

def send_trial_confirmation_to_clinic(data: dict) -> bool:
    """Send trial confirmation email to newly signed-up clinic."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        logger.warning("SMTP not configured — trial confirmation NOT emailed. Details: %s", data)
        return False

    clinic_name = data.get("clinic_name", "Your Clinic")
    clinic_email = data.get("clinic_email", "")
    trial_ends = data.get("trial_ends_at", "—")
    portal_url = data.get("portal_url", settings.base_url)
    subject = f"Welcome to TaborSynergy Agent — 14-Day Free Trial!"

    plain = "\n".join([
        f"Welcome {clinic_name}!",
        "",
        "Your 14-day free trial of TaborSynergy Agent is now active.",
        "",
        "✅ Appointment booking chat",
        "✅ Basic insurance Q&A",
        "✅ Email support",
        "",
        f"Your trial ends: {trial_ends}",
        f"Portal: {portal_url}",
        "",
        "Questions? Contact us at support@taborsynergy.com",
        "— The TaborSynergy Team",
    ])

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#0F3D91;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Welcome to TaborSynergy Agent!</h2>
  <p style="color:#a0c4ff;margin:4px 0 0">14-Day Free Trial Activated</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p style="margin-top:0">Hi <strong>{clinic_name}</strong>,</p>
  <p>Your 14-day free trial is now active. Start booking appointments with AI immediately.</p>
  <div style="background:#E0F2FE;padding:16px;border-left:4px solid #0F3D91;border-radius:4px;margin:20px 0">
    <strong>What's Included:</strong>
    <ul style="margin:8px 0;padding-left:20px">
      <li>Appointment booking chat</li>
      <li>Basic insurance Q&A</li>
      <li>Email support</li>
    </ul>
  </div>
  <table style="width:100%;border-collapse:collapse;margin:20px 0">
    <tr><td style="padding:8px;color:#666;width:40%">Trial Ends</td>
        <td style="padding:8px;font-weight:bold">{trial_ends}</td></tr>
    <tr style="background:#fff"><td style="padding:8px;color:#666">Plan</td>
        <td style="padding:8px">Starter (Free)</td></tr>
  </table>
  <div style="margin:20px 0;text-align:center">
    <a href="{portal_url}" style="background:#0F3D91;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:700">
      Go to Your Portal →
    </a>
  </div>
  <p style="margin-top:20px;font-size:12px;color:#999">TaborSynergy — automated notification</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to=settings.notify_email)
    if clinic_email:
        msg.replace_header("To", clinic_email)
    return _send(msg)


def send_trial_expiry_reminder_to_clinic(data: dict) -> bool:
    """Send trial expiry reminder email to clinic (5+ days before expiry)."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        logger.warning("SMTP not configured — trial reminder NOT emailed. Details: %s", data)
        return False

    clinic_name = data.get("clinic_name", "Your Clinic")
    clinic_email = data.get("clinic_email", "")
    days_remaining = data.get("days_remaining", 5)
    trial_ends = data.get("trial_ends_at", "—")
    upgrade_url = data.get("upgrade_url", settings.base_url + "/clinic/upgrade")
    subject = f"Your TaborSynergy Trial Expires in {days_remaining} Days"

    plain = "\n".join([
        f"Hi {clinic_name},",
        "",
        f"Your 14-day trial ends on {trial_ends} ({days_remaining} days remaining).",
        "",
        "Don't lose access! Upgrade now to continue using TaborSynergy Agent.",
        "",
        "Growth Plan: $597/month",
        "  ✅ Email reminders & recall",
        "  ✅ Custom insurance knowledge",
        "  ✅ Monthly reports",
        "",
        "Enterprise Plan: $997/month",
        "  ✅ Multi-location routing",
        "  ✅ EHR integration",
        "  ✅ Custom AI training",
        "",
        f"Upgrade: {upgrade_url}",
        "",
        "— The TaborSynergy Team",
    ])

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#DC2626;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Trial Expiring Soon</h2>
  <p style="color:#fecaca;margin:4px 0 0">{days_remaining} days remaining</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p style="margin-top:0">Hi <strong>{clinic_name}</strong>,</p>
  <p>Your TaborSynergy Agent trial expires on <strong>{trial_ends}</strong> ({days_remaining} days remaining).</p>
  <p style="margin:20px 0"><strong>Upgrade now</strong> to continue booking appointments and get access to:</p>
  <div style="background:#FEF2F2;padding:16px;border-left:4px solid #DC2626;border-radius:4px">
    <strong>Growth Plan: $597/month</strong>
    <ul style="margin:8px 0;padding-left:20px;font-size:14px">
      <li>Email reminders &amp; recall</li>
      <li>Custom insurance knowledge</li>
      <li>Monthly performance reports</li>
      <li>Priority support</li>
    </ul>
  </div>
  <p></p>
  <div style="background:#EFF6FF;padding:16px;border-left:4px solid #0F3D91;border-radius:4px;margin:12px 0">
    <strong>Enterprise Plan: $997/month</strong>
    <ul style="margin:8px 0;padding-left:20px;font-size:14px">
      <li>Multi-location intelligent routing</li>
      <li>EHR system integration</li>
      <li>Custom AI training</li>
      <li>Dedicated account manager</li>
    </ul>
  </div>
  <div style="margin:20px 0;text-align:center">
    <a href="{upgrade_url}" style="background:#DC2626;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:700">
      Upgrade Now →
    </a>
  </div>
  <p style="margin-top:20px;font-size:12px;color:#999">TaborSynergy — automated notification</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to=settings.notify_email)
    if clinic_email:
        msg.replace_header("To", clinic_email)
    return _send(msg)


def send_trial_expired_to_clinic(data: dict) -> bool:
    """Send trial expired notification to clinic."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        logger.warning("SMTP not configured — trial expired email NOT sent. Details: %s", data)
        return False

    clinic_name = data.get("clinic_name", "Your Clinic")
    clinic_email = data.get("clinic_email", "")
    upgrade_url = data.get("upgrade_url", settings.base_url + "/clinic/upgrade")
    subject = "Your TaborSynergy Agent Trial Has Ended"

    plain = "\n".join([
        f"Hi {clinic_name},",
        "",
        "Your 14-day trial has ended. To continue using TaborSynergy Agent and booking appointments,",
        "please upgrade to a paid plan.",
        "",
        "Upgrade: " + upgrade_url,
        "",
        "Questions? Contact support@taborsynergy.com",
        "— The TaborSynergy Team",
    ])

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#6B7280;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Trial Ended</h2>
  <p style="color:#e5e7eb;margin:4px 0 0">Upgrade to continue</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p style="margin-top:0">Hi <strong>{clinic_name}</strong>,</p>
  <p>Your 14-day trial has ended. To continue booking appointments and using TaborSynergy Agent, please upgrade to a paid plan.</p>
  <div style="margin:20px 0;text-align:center">
    <a href="{upgrade_url}" style="background:#0F3D91;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:700">
      Upgrade Now →
    </a>
  </div>
  <p style="font-size:13px;color:#666">
    Without an active subscription, patients will no longer be able to chat with your AI front desk.
  </p>
  <p style="margin-top:20px;font-size:12px;color:#999">TaborSynergy — automated notification</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to=settings.notify_email)
    if clinic_email:
        msg.replace_header("To", clinic_email)
    return _send(msg)


def send_renewal_reminder_to_clinic(data: dict) -> bool:
    """Remind an active paying clinic that their monthly subscription renews soon."""
    if not settings.sendgrid_api_key and (not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass):
        logger.warning("SMTP not configured — renewal reminder NOT emailed. Details: %s", data)
        return False

    clinic_name = data.get("clinic_name", "Your Clinic")
    clinic_email = data.get("clinic_email", "")
    days_remaining = data.get("days_remaining", 7)
    renews_on = data.get("renews_on", "—")
    plan = data.get("plan", "your plan")
    amount = data.get("amount", "")
    manage_url = data.get("manage_url", settings.base_url + "/clinic/billing")
    amount_str = f" ({amount})" if amount else ""
    subject = f"Your TaborSynergy subscription renews in {days_remaining} days"

    plain = "\n".join([
        f"Hi {clinic_name},",
        "",
        f"A quick heads-up: your {plan} subscription{amount_str} renews on {renews_on} "
        f"({days_remaining} days from now).",
        "",
        "No action is needed if you'd like to continue — your AI front desk keeps running.",
        "To update billing, change plan, or cancel, visit your billing page:",
        f"  {manage_url}",
        "",
        "Thanks for being with us!",
        "— The TaborSynergy Team",
    ])

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#0F3D91;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Subscription Renewal</h2>
  <p style="color:#c7d2fe;margin:4px 0 0">Renews in {days_remaining} days</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p style="margin-top:0">Hi <strong>{clinic_name}</strong>,</p>
  <p>Your <strong>{plan}</strong> subscription{amount_str} renews on
     <strong>{renews_on}</strong> ({days_remaining} days from now).</p>
  <p>No action is needed to continue — your AI front desk keeps running. You can update
     billing, change plan, or cancel anytime.</p>
  <div style="margin:20px 0;text-align:center">
    <a href="{manage_url}" style="background:#0F3D91;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:700">
      Manage Billing →
    </a>
  </div>
  <p style="margin-top:20px;font-size:12px;color:#999">TaborSynergy — automated notification</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to=settings.notify_email)
    if clinic_email:
        msg.replace_header("To", clinic_email)
    return _send(msg)


# ── Onboarding Email Sequence ─────────────────────────────────────────────────

def send_onboarding_day0(data: dict) -> bool:
    """Day 0 — Welcome email sent immediately on signup."""
    clinic_email = data.get("clinic_email", "")
    if not clinic_email:
        return False

    plan = data.get("plan", "starter")
    subject = {
        "starter":      "Your AI front desk is ready — here's how to turn it on ⚕️",
        "professional": "Welcome to Professional — let's get your reminders live ⚕️",
        "enterprise":   "Welcome to Enterprise — let's schedule your onboarding call ⚕️",
        "white_label":  "White Label access granted — your platform is ready to deploy ⚕️",
    }.get(plan, "Your AI front desk is ready ⚕️")

    plain = f"""Hi {data.get('first_name', 'there')},

Welcome to Tabor Synergy! Your 14-day free trial starts now.

Your clinic portal: {data.get('portal_url', 'https://aifrontdesk.taborsynergy.com')}

3-STEP LAUNCH:
1. Fill in your clinic profile (Settings tab) — 5 minutes
2. Embed Aria on your website (Widget tab) — 5 minutes
3. Send a test message → type "I need an appointment"

Trial ends: {data.get('trial_ends_at', 'in 14 days')}
No credit card needed until then.

Questions? Reply to this email — I respond personally.

— Dinakar, Founder · Tabor Synergy
aifrontdesk.taborsynergy.com"""

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#1E40AF;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Welcome to Tabor Synergy</h2>
  <p style="color:#93C5FD;margin:4px 0 0">Your 14-day free trial starts now ⚕️</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p>Hi <strong>{data.get('first_name', 'there')}</strong>,</p>
  <p>Welcome! Your free trial is activated. Let's get Aria live in 3 steps:</p>
  <ol style="color:#0F172A">
    <li><strong>Fill in your clinic profile</strong> (Settings tab) — 5 min</li>
    <li><strong>Embed Aria on your website</strong> (Widget tab) — 5 min</li>
    <li><strong>Send a test message</strong> → type "I need an appointment"</li>
  </ol>
  <p>Your clinic portal: <a href="{data.get('portal_url', 'https://aifrontdesk.taborsynergy.com')}" style="color:#1E40AF">{data.get('portal_url', 'https://aifrontdesk.taborsynergy.com')}</a></p>
  <p><strong>Trial ends:</strong> {data.get('trial_ends_at', 'in 14 days')}<br/>No credit card required until then.</p>
  <p style="margin-top:20px;font-size:13px;color:#666">Questions? Just reply to this email — I respond personally.</p>
  <p style="margin-top:20px;font-size:12px;color:#999">— Dinakar<br/>Founder, Tabor Synergy</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to="write2dinakar10@gmail.com")
    msg.replace_header("To", clinic_email)
    return _send(msg)


def send_onboarding_day1(data: dict) -> bool:
    """Day 1 — Widget / reminders check-in."""
    clinic_email = data.get("clinic_email", "")
    if not clinic_email:
        return False

    subject = f"Is Aria live on your website yet? [{data.get('clinic_name', '')}]"
    plain = f"""Hi {data.get('first_name', 'there')},

Quick check-in — did you embed Aria on your website yesterday?

If not yet, here's the 2-minute fix:
1. Login to {data.get('portal_url')}
2. Go to "Widget" tab
3. Copy the embed code
4. Paste before </body> tag on your website

WordPress:    Appearance → Theme Editor → footer.php
Squarespace:  Settings → Advanced → Code Injection → Footer
Wix:          Add → HTML iFrame → paste code
Custom HTML:  Paste before closing </body> tag

Still stuck? Reply with your website URL and I'll write the exact code.

— Dinakar, Tabor Synergy"""

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#1E40AF;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Day 1 Check-In</h2>
  <p style="color:#93C5FD;margin:4px 0 0">Is Aria live on your website yet?</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p>Hi <strong>{data.get('first_name', 'there')}</strong>,</p>
  <p>Quick check-in — did you embed Aria on your website yesterday? If yes, great! Test it with "I need an appointment." If not yet, here's the 2-minute fix:</p>
  <ol style="color:#0F172A">
    <li>Login to <a href="{data.get('portal_url')}" style="color:#1E40AF">{data.get('portal_url')}</a></li>
    <li>Click <strong>Widget</strong> tab</li>
    <li>Copy the embed code</li>
    <li>Paste before <code>&lt;/body&gt;</code> on your website</li>
  </ol>
  <p style="font-size:13px;color:#666;margin-top:16px"><strong>Stuck?</strong> Reply with your website URL and I'll write the exact code for you.</p>
  <p style="margin-top:20px;font-size:12px;color:#999">— Dinakar · Tabor Synergy</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to="write2dinakar10@gmail.com")
    msg.replace_header("To", clinic_email)
    return _send(msg)


def send_onboarding_day3(data: dict) -> bool:
    """Day 3 — Power tips (insurance + recall)."""
    clinic_email = data.get("clinic_email", "")
    if not clinic_email:
        return False

    subject = f"3 things that make Aria 10x better"
    plain = f"""Hi {data.get('first_name', 'there')},

3 days in — here are the 3 things that make the biggest difference:

1. FILL IN YOUR INSURANCE LIST
   Login → Settings → Insurance Accepted → add every plan you accept
   This makes Aria answer "Do you accept my insurance?" instantly.

2. SET YOUR AFTER-HOURS MESSAGE
   Settings → After Hours Protocol
   Example: "For emergencies call 911. We return calls by 9am next day."

3. ADD YOUR CANCELLATION POLICY
   Settings → Cancellation Policy
   Example: "24-hour notice required. Late cancellations incur $50 fee."

These 3 changes take 10 minutes and double Aria's response quality.

Portal: {data.get('portal_url')}

— Dinakar, Tabor Synergy

P.S. Your trial has 11 days remaining."""

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#1E40AF;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Power Tips</h2>
  <p style="color:#93C5FD;margin:4px 0 0">3 settings that make Aria 10x better</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p>Hi <strong>{data.get('first_name', 'there')}</strong>,</p>
  <p>You're 3 days in! Here are the 3 settings that make the biggest difference:</p>
  <h3 style="color:#0F172A;font-size:14px;margin:16px 0 8px">1. Insurance List</h3>
  <p style="margin:0;font-size:13px;color:#666">Settings → Insurance Accepted → add every plan you accept. Aria will then answer "Do you accept my insurance?" instantly.</p>
  <h3 style="color:#0F172A;font-size:14px;margin:16px 0 8px">2. After-Hours Message</h3>
  <p style="margin:0;font-size:13px;color:#666">Settings → After Hours Protocol. Example: "For emergencies call 911. We return calls by 9am next day."</p>
  <h3 style="color:#0F172A;font-size:14px;margin:16px 0 8px">3. Cancellation Policy</h3>
  <p style="margin:0;font-size:13px;color:#666">Settings → Cancellation Policy. Example: "24-hour notice required. Late cancellations incur $50 fee."</p>
  <p style="margin:16px 0;font-size:13px;color:#666">These 3 changes take 10 minutes and double Aria's quality. <a href="{data.get('portal_url')}" style="color:#1E40AF">Update your settings →</a></p>
  <p style="font-size:12px;color:#999;margin-top:20px">— Dinakar<br/>Founder, Tabor Synergy</p>
  <p style="font-size:11px;color:#CCC;margin-top:12px;padding-top:12px;border-top:1px solid #E5E7EB">P.S. Your trial has 11 days remaining.</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to="write2dinakar10@gmail.com")
    msg.replace_header("To", clinic_email)
    return _send(msg)


def send_onboarding_day7(data: dict) -> bool:
    """Day 7 — Usage review + upgrade nudge."""
    clinic_email = data.get("clinic_email", "")
    if not clinic_email:
        return False

    plan = data.get("plan", "starter")
    subject = f"Halfway through your trial — how is it going?"

    upgrade_section = ""
    if plan == "starter":
        upgrade_section = "\nREADY FOR MORE?\nProfessional ($597/mo) adds email reminders, recall campaigns, and 5 providers.\nUpgrade anytime: Billing tab → Upgrade Plan"

    plain = f"""Hi {data.get('first_name', 'there')},

You're halfway through your 14-day trial! Quick question:
Has Aria answered any patient messages yet?

Check your usage: {data.get('portal_url')} → Analytics{upgrade_section}

Your trial ends on {data.get('trial_ends_at', 'soon')}.
To keep Aria running: Billing tab → Activate Subscription.

Questions? Just reply — happy to help.

— Dinakar, Tabor Synergy"""

    upgrade_html = ""
    if plan == "starter":
        portal_url = data.get('portal_url')
        upgrade_html = f'<div style="background:#FEF9C3;border:1px solid #FDE68A;border-radius:6px;padding:14px;margin:16px 0;font-size:13px"><strong style="color:#92400E">Ready for more?</strong><br/>Professional ($597/mo) adds email reminders, recall campaigns, and 5 providers.<br/><a href="{portal_url}" style="color:#1E40AF">Upgrade Plan →</a></div>'

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#1E40AF;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Halfway Through</h2>
  <p style="color:#93C5FD;margin:4px 0 0">How is Aria working for you?</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p>Hi <strong>{data.get('first_name', 'there')}</strong>,</p>
  <p>You're halfway through your trial! Quick question: <strong>Has Aria answered any patient messages yet?</strong></p>
  <p>Check your usage: <a href="{data.get('portal_url')}" style="color:#1E40AF">{data.get('portal_url')}</a> → Analytics</p>
  {upgrade_html}
  <p style="margin-top:16px;font-size:13px;color:#666"><strong>Your trial ends:</strong> {data.get('trial_ends_at', 'soon')}<br/>To keep Aria running, go to Billing tab → Activate Subscription.</p>
  <p style="margin-top:20px;font-size:12px;color:#999">Questions? Just reply — happy to help.<br/>— Dinakar · Tabor Synergy</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to="write2dinakar10@gmail.com")
    msg.replace_header("To", clinic_email)
    return _send(msg)


def send_onboarding_day12(data: dict) -> bool:
    """Day 12 — Trial ending in 2 days."""
    clinic_email = data.get("clinic_email", "")
    if not clinic_email:
        return False

    plan = data.get("plan", "starter")
    prices = {"starter": "$297", "professional": "$597", "enterprise": "$997", "white_label": "$997"}
    price = prices.get(plan, "$297")
    plan_label = {"starter": "Starter", "professional": "Professional", "enterprise": "Enterprise", "white_label": "White Label"}.get(plan, "Starter")

    subject = f"Your trial ends in 2 days — activate to continue"
    plain = f"""Hi {data.get('first_name', 'there')},

Your 14-day trial ends on {data.get('trial_ends_at', 'soon')} — in 2 days.

To keep Aria running for your patients, activate your subscription:
{data.get('portal_url')} → Billing → Activate

{plan_label.upper()} PLAN: {price}/month
Everything you've been using during your trial
Cancel anytime, no contracts

If you have questions before deciding, reply to this email.
I'll personally help.

If timing isn't right now, no problem — your account stays accessible
and you can reactivate whenever you're ready.

Thank you for trying Tabor Synergy!

— Dinakar
Founder, Tabor Synergy
aifrontdesk.taborsynergy.com"""

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
<div style="background:#DC2626;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:#fff;margin:0">Trial Ends in 2 Days</h2>
  <p style="color:#FECACA;margin:4px 0 0">Activate your subscription to continue</p>
</div>
<div style="background:#f9f9f9;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
  <p>Hi <strong>{data.get('first_name', 'there')}</strong>,</p>
  <p>Your 14-day trial ends on <strong>{data.get('trial_ends_at', 'soon')}</strong> — in 2 days.</p>
  <p style="margin:16px 0;">To keep Aria running for your patients, activate your subscription:</p>
  <div style="background:#1E40AF;color:#fff;padding:16px;border-radius:8px;text-align:center;margin:16px 0">
    <a href="{data.get('portal_url')}/billing" style="color:#fff;text-decoration:none;font-weight:700;font-size:16px">Activate Subscription →</a>
  </div>
  <table style="width:100%;font-size:13px;margin:16px 0">
    <tr><td style="padding:6px 0"><strong>{plan_label.upper()} PLAN</strong></td><td style="text-align:right;font-weight:700">{price}/month</td></tr>
    <tr><td colspan="2" style="padding:6px 0;color:#666;font-size:12px">✓ Everything you've been using<br/>✓ Cancel anytime<br/>✓ No contracts</td></tr>
  </table>
  <p style="font-size:13px;color:#666;margin:16px 0">If you have questions before deciding, <strong>reply to this email</strong>. I'll help personally.</p>
  <p style="font-size:13px;color:#666;margin:16px 0">If timing isn't right now, your account stays accessible and you can reactivate whenever you're ready.</p>
  <p style="font-size:12px;color:#999;margin-top:20px;padding-top:16px;border-top:1px solid #E5E7EB">Thank you for trying Tabor Synergy!<br/>— Dinakar<br/>Founder, Tabor Synergy</p>
</div></body></html>"""

    msg = _build_msg(subject, plain, html, reply_to="write2dinakar10@gmail.com")
    msg.replace_header("To", clinic_email)
    return _send(msg)
