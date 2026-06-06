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


def _send(msg: MIMEMultipart) -> bool:
    """
    Try SSL (port 465) first, then STARTTLS (port 587).
    Logs the specific error so it shows clearly in Render logs.
    """
    recipients = _recipients()

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


# ── public API ────────────────────────────────────────────────────────────────

def send_trial_signup_email(data: dict) -> bool:
    """Notify admin when a new trial clinic signs up."""
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
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
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
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
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
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
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
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
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
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
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
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
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
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
        "  ✅ SMS & WhatsApp messaging",
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
      <li>SMS & WhatsApp messaging</li>
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
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
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
