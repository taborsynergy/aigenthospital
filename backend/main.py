import json
import logging
import logging.config
import re
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.config import settings
from backend.db.database import get_db, init_db
from backend.db.crud import get_clinic
from backend.limiter import limiter

# ── Sentry (initialize before anything else) ─────────────────────────────────
if settings.sentry_dsn and settings.sentry_dsn.startswith("https://"):
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        import logging as _logging

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
                LoggingIntegration(level=_logging.WARNING, event_level=_logging.ERROR),
            ],
            traces_sample_rate=0.2,       # 20% of requests traced for performance
            profiles_sample_rate=0.1,     # 10% profiling
            send_default_pii=False,        # HIPAA — never send PII to Sentry
            environment="production" if not settings.debug_mode else "development",
            release="taborsynergy@1.0.0",
            # Scrub sensitive fields before sending to Sentry
            before_send=lambda event, hint: _scrub_sentry_event(event),
        )
        print("✓ Sentry initialized — error tracking active")
    except Exception as e:
        print(f"Warning: Sentry init failed: {e} — continuing without error tracking")


def _scrub_sentry_event(event: dict) -> dict:
    """Remove HIPAA-sensitive fields from Sentry events before transmission."""
    _PHI_KEYS = {
        "patient_name", "patient_phone", "patient_email", "patient_dob",
        "member_id", "group_number", "ssn", "date_of_birth",
        "password", "token", "session_token", "api_key", "api_key",
    }
    def _scrub(obj):
        if isinstance(obj, dict):
            return {k: "[REDACTED]" if k.lower() in _PHI_KEYS else _scrub(v)
                    for k, v in obj.items()}
        if isinstance(obj, list):
            return [_scrub(i) for i in obj]
        return obj
    return _scrub(event)

# ── PHI redaction filter ──────────────────────────────────────────────────────
_PHI_PATTERNS = [
    (re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"), "[SSN]"),       # SSN
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),     # phone
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b(19|20)\d{2}[-/]\d{2}[-/]\d{2}\b"), "[DOB]"),      # DOB YYYY-MM-DD
]

class _PhiRedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern, replacement in _PHI_PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = ()
        return True

# ── Structured JSON logging ───────────────────────────────────────────────────
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":      self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)

_phi_filter = _PhiRedactFilter()
_handler = logging.StreamHandler()
_handler.addFilter(_phi_filter)
_handler.setFormatter(_JsonFormatter())
logging.root.setLevel(logging.INFO)
logging.root.handlers = [_handler]
from backend.routers.chat import router as chat_router  # noqa: E402
from backend.routers.admin import router as admin_router  # noqa: E402
from backend.routers.sms import router as sms_router  # noqa: E402
from backend.routers.billing import router as billing_router  # noqa: E402
from backend.routers.signup import router as signup_router  # noqa: E402
from backend.routers.clinic_auth import router as clinic_auth_router  # noqa: E402
from backend.routers.reminders import router as reminders_router  # noqa: E402
from backend.routers.recall import router as recall_router  # noqa: E402
from backend.routers.locations import router as locations_router  # noqa: E402
from backend.routers.widget import router as widget_router  # noqa: E402
from backend.routers.insurance import router as insurance_router  # noqa: E402
from backend.routers.ehr import router as ehr_router  # noqa: E402
from backend.routers.custom_ai_training import router as custom_ai_training_router  # noqa: E402
from backend.routers.providers import router as providers_router  # noqa: E402
from backend.routers.onboarding import router as onboarding_router  # noqa: E402
from backend.routers.whitelabel import router as whitelabel_router  # noqa: E402

_SPECIALTY_ICONS = {
    "dental": "🦷", "dentistry": "🦷", "orthodontics": "🦷",
    "endodontics": "🦷", "periodontics": "🦷", "oral surgery": "🦷",
    "dermatology": "🔬",
    "pediatrics": "👶", "pediatric": "👶",
    "orthopedics": "🦴", "orthopedic": "🦴", "sports medicine": "🦴", "chiropractic": "🦴",
    "ophthalmology": "👁️", "optometry": "👁️", "eye care": "👁️",
    "ob-gyn": "🤰", "obstetrics": "🤰", "gynecology": "🤰", "prenatal": "🤰",
    "ent": "👂", "ear, nose": "👂", "ear nose": "👂",
    "cardiology": "❤️", "cardiac": "❤️", "heart": "❤️",
    "oncology": "🎗️", "cancer": "🎗️",
    "family medicine": "🏠", "family practice": "🏠", "primary care": "🏠",
    "urgent care": "🚑", "emergency": "🚑",
    "neurology": "🧠", "neuroscience": "🧠", "psychiatry": "🧠", "psychology": "🧠",
    "pulmonology": "🫁", "respiratory": "🫁",
    "nephrology": "🫘", "kidney": "🫘",
    "gastroenterology": "🏥", "gastro": "🏥",
    "endocrinology": "💉", "diabetes": "💉",
    "radiology": "🩻",
    "physical therapy": "🏃", "rehabilitation": "🏃",
    "urology": "🏥", "rheumatology": "🏥", "surgery": "🏥",
}


def _specialty_icon(specialty: str) -> str:
    s = specialty.lower()
    for key, icon in _SPECIALTY_ICONS.items():
        if key in s:
            return icon
    return "🏥"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title="Tabor Synergy — Universal Medical Front Desk Agent",
    version="2.0.0",
    docs_url="/docs"        if settings.debug_mode else None,
    redoc_url="/redoc"      if settings.debug_mode else None,
    openapi_url="/openapi.json" if settings.debug_mode else None,
)


class SecurityHeadersMiddleware:
    """
    Pure ASGI middleware — injects security headers without wrapping the
    response body. BaseHTTPMiddleware has a known bug where it overwrites
    the Content-Type of FileResponse (streaming) to application/json.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                security_headers = [
                    (b"x-content-type-options",  b"nosniff"),
                    (b"x-frame-options",          b"DENY"),
                    (b"x-xss-protection",         b"1; mode=block"),
                    (b"strict-transport-security",b"max-age=63072000; includeSubDomains"),
                    (b"referrer-policy",          b"strict-origin-when-cross-origin"),
                    (b"content-security-policy",  (
                        b"default-src 'self'; "
                        b"script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                        b"style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
                        b"font-src 'self' fonts.gstatic.com; "
                        b"img-src 'self' data: https://api.qrserver.com https:; "
                        b"connect-src 'self' wss: ws: https:; "
                        b"frame-ancestors 'none';"
                    )),
                ]
                # Only add if not already present (preserves FileResponse Content-Type)
                existing_keys = {h[0].lower() for h in headers}
                for key, val in security_headers:
                    if key not in existing_keys:
                        headers.append((key, val))
                message = dict(message, headers=headers)
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

origins = ["*"] if settings.allowed_origins == "*" else settings.allowed_origins.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(sms_router)
app.include_router(billing_router)
app.include_router(signup_router)
app.include_router(clinic_auth_router)
app.include_router(reminders_router)
app.include_router(recall_router)
app.include_router(locations_router)
app.include_router(widget_router)
app.include_router(insurance_router)
app.include_router(ehr_router)
app.include_router(custom_ai_training_router)
app.include_router(providers_router)
app.include_router(onboarding_router)
app.include_router(whitelabel_router)

# ── Clinic widget pages ───────────────────────────────────────────────────────
@app.get("/c/{clinic_slug}", response_class=HTMLResponse)
async def clinic_page(clinic_slug: str, db: Session = Depends(get_db)):
    clinic = get_clinic(db, clinic_slug)
    if not clinic:
        return HTMLResponse("<h1>Clinic not found</h1>", status_code=404)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{clinic.name} — Clinic Portal</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #F0F7FF; min-height: 100vh; color: #1F2937; }}

    /* ── Login ── */
    #login-screen {{
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; padding: 16px;
    }}
    .login-card {{
      background: #fff; border-radius: 16px; padding: 40px 36px;
      max-width: 400px; width: 100%;
      box-shadow: 0 8px 40px rgba(0,0,0,.12); text-align: center;
    }}
    .login-logo {{ font-size: 40px; margin-bottom: 12px; }}
    .login-card h1 {{ font-size: 20px; font-weight: 800; color: #1E3A5F; margin-bottom: 4px; }}
    .login-card .sub {{ font-size: 13px; color: #6B7280; margin-bottom: 28px; }}
    .fg {{ margin-bottom: 14px; text-align: left; }}
    .fg label {{ display: block; font-size: 12px; font-weight: 600; color: #374151; margin-bottom: 4px; }}
    .fg input {{
      width: 100%; border: 1px solid #D1D5DB; border-radius: 8px;
      padding: 10px 12px; font-size: 14px; outline: none;
    }}
    .fg input:focus {{ border-color: #3B82F6; box-shadow: 0 0 0 3px rgba(59,130,246,.15); }}
    .btn-login {{
      width: 100%; background: #1E40AF; color: #fff; border: none;
      border-radius: 8px; padding: 12px; font-size: 15px; font-weight: 700;
      cursor: pointer; margin-top: 4px; transition: background .2s;
    }}
    .btn-login:hover {{ background: #1E3A8A; }}
    .btn-login:disabled {{ background: #93C5FD; cursor: not-allowed; }}
    .login-err {{
      display: none; background: #FEE2E2; border: 1px solid #FCA5A5;
      color: #991B1B; font-size: 14px; font-weight: 500;
      padding: 10px 14px; border-radius: 8px; margin-top: 14px;
      text-align: left; line-height: 1.5;
    }}
    .login-err.show {{ display: block; }}
    .login-footer {{ font-size: 12px; color: #9CA3AF; margin-top: 20px; }}
    .login-footer a {{ color: #3B82F6; text-decoration: none; }}

    /* ── Dashboard ── */
    #dash-screen {{ display: none; }}
    .topbar {{
      background: #1E40AF; color: #fff; padding: 0 24px; height: 56px;
      display: flex; align-items: center; justify-content: space-between;
      position: sticky; top: 0; z-index: 100;
    }}
    .topbar-brand {{ font-weight: 700; font-size: 16px; }}
    .topbar-sub {{ font-size: 12px; opacity: .75; }}
    .btn-logout {{
      background: rgba(255,255,255,.15); border: none; color: #fff;
      border-radius: 6px; padding: 6px 14px; font-size: 13px;
      cursor: pointer; transition: background .15s;
    }}
    .btn-logout:hover {{ background: rgba(255,255,255,.25); }}

    .dash-body {{ max-width: 960px; margin: 0 auto; padding: 32px 20px; }}

    /* ── Tab nav ── */
    .tabs {{ display: flex; gap: 4px; margin-bottom: 28px;
             background: #E8F0FE; border-radius: 10px; padding: 4px; }}
    .tab-btn {{
      flex: 1; padding: 10px 16px; border: none; background: transparent;
      border-radius: 8px; font-size: 14px; font-weight: 600; color: #4B5563;
      cursor: pointer; transition: all .2s;
    }}
    .tab-btn.active {{ background: #fff; color: #1E40AF;
                       box-shadow: 0 1px 4px rgba(0,0,0,.1); }}
    .tab-btn:hover:not(.active) {{ background: rgba(255,255,255,.5); }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}

    /* ── Share panel ── */
    .share-card {{
      background: #fff; border-radius: 16px; padding: 28px;
      box-shadow: 0 2px 12px rgba(0,0,0,.07); margin-bottom: 20px;
    }}
    .share-card h2 {{ font-size: 17px; font-weight: 700; color: #1E3A5F; margin-bottom: 6px; }}
    .share-card p {{ font-size: 14px; color: #6B7280; margin-bottom: 18px; line-height: 1.6; }}
    .url-row {{
      display: flex; gap: 8px; align-items: center;
      background: #F3F4F6; border: 1px solid #E5E7EB;
      border-radius: 10px; padding: 10px 14px;
      margin-bottom: 10px;
    }}
    .url-text {{
      flex: 1; font-size: 13px; color: #1F2937; font-family: monospace;
      word-break: break-all;
    }}
    .btn-copy {{
      background: #1E40AF; color: #fff; border: none;
      border-radius: 7px; padding: 6px 16px; font-size: 12px;
      font-weight: 600; cursor: pointer; white-space: nowrap;
      transition: background .2s;
    }}
    .btn-copy:hover {{ background: #1E3A8A; }}
    .btn-copy.copied {{ background: #059669; }}
    .embed-box {{
      background: #0D1117; border-radius: 10px; padding: 16px;
      font-size: 12px; font-family: monospace; color: #C9D1D9;
      line-height: 1.7; white-space: pre-wrap; margin-bottom: 10px;
    }}
    .share-steps {{ list-style: none; padding: 0; }}
    .share-steps li {{
      display: flex; align-items: flex-start; gap: 12px;
      padding: 12px 0; border-bottom: 1px solid #F3F4F6; font-size: 14px;
    }}
    .share-steps li:last-child {{ border-bottom: none; }}
    .step-num {{
      width: 24px; height: 24px; border-radius: 50%;
      background: #1E40AF; color: #fff; font-size: 12px; font-weight: 700;
      display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    }}
    .channel-pills {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
    .pill {{
      background: #EFF6FF; border: 1px solid #BFDBFE;
      color: #1D4ED8; border-radius: 20px; padding: 4px 14px;
      font-size: 12px; font-weight: 600;
    }}
    .qr-box {{ text-align: center; padding: 16px 0; }}
    .qr-box img {{ border-radius: 10px; border: 1px solid #E5E7EB; }}
    .qr-box p {{ font-size: 12px; color: #9CA3AF; margin-top: 8px; }}

    /* ── Try Aria panel ── */
    .aria-hint {{
      background: #DBEAFE; border: 1px solid #BFDBFE; border-radius: 12px;
      padding: 20px 24px; font-size: 14px; color: #1D4ED8; text-align: center;
      margin-bottom: 20px; line-height: 1.7;
    }}
    .aria-hint strong {{ display: block; font-size: 16px; margin-bottom: 6px; }}

    /* ── Appointments tab ── */
    .appt-toolbar {{
      display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;
    }}
    .appt-toolbar input {{
      flex: 1; min-width: 180px; border: 1px solid #D1D5DB; border-radius: 8px;
      padding: 8px 12px; font-size: 14px; outline: none;
    }}
    .appt-toolbar input:focus {{ border-color: #3B82F6; box-shadow: 0 0 0 3px rgba(59,130,246,.15); }}
    .btn-refresh {{
      background: #1E40AF; color: #fff; border: none; border-radius: 8px;
      padding: 8px 18px; font-size: 13px; font-weight: 600; cursor: pointer;
      transition: background .2s; white-space: nowrap;
    }}
    .btn-refresh:hover {{ background: #1E3A8A; }}
    .appt-count {{ font-size: 13px; color: #6B7280; }}
    .appt-table-wrap {{
      background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.07);
      overflow-x: auto;
    }}
    .appt-table {{
      width: 100%; border-collapse: collapse; font-size: 13px;
    }}
    .appt-table th {{
      background: #F8FAFC; color: #374151; font-weight: 700; font-size: 12px;
      text-transform: uppercase; letter-spacing: .5px;
      padding: 12px 14px; text-align: left; border-bottom: 1px solid #E5E7EB;
      white-space: nowrap;
    }}
    .appt-table td {{
      padding: 12px 14px; border-bottom: 1px solid #F3F4F6; color: #1F2937;
      vertical-align: top;
    }}
    .appt-table tr:last-child td {{ border-bottom: none; }}
    .appt-table tr:hover td {{ background: #F9FAFB; }}
    .badge {{
      display: inline-block; border-radius: 20px; padding: 2px 10px;
      font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .4px;
    }}
    .badge-scheduled  {{ background: #D1FAE5; color: #065F46; }}
    .badge-cancelled  {{ background: #FEE2E2; color: #991B1B; }}
    .badge-rescheduled{{ background: #FEF3C7; color: #92400E; }}
    .appt-empty {{
      text-align: center; padding: 48px 20px; color: #9CA3AF; font-size: 14px;
    }}
    .appt-empty p {{ margin-top: 8px; }}
  </style>
</head>
<body>

<!-- ── Login ─────────────────────────────────────────────── -->
<div id="login-screen">
  <div class="login-card">
    <div class="login-logo">🏥</div>
    <h1>{clinic.name}</h1>
    <p class="sub">{clinic.specialty} · Sign in to your clinic portal</p>
    <form id="login-form" onsubmit="doLogin(event)">
      <div class="fg">
        <label>Email</label>
        <input id="l-email" type="email" required placeholder="you@yourpractice.com"
               autocomplete="username" />
      </div>
      <div class="fg">
        <label>Password</label>
        <input id="l-pass" type="password" required placeholder="••••••••"
               autocomplete="current-password" />
      </div>
      <button class="btn-login" type="submit" id="login-btn">Sign In →</button>
    </form>
    <div class="login-err" id="login-err"></div>
    <div class="login-footer">
      Forgot your password? Email
      <a href="mailto:admin@tabor.taborsynergy.com">admin@tabor.taborsynergy.com</a>
    </div>
  </div>
</div>

<!-- ── Dashboard ─────────────────────────────────────────── -->
<div id="dash-screen">
  <div class="topbar">
    <div>
      <div class="topbar-brand">🏥 {clinic.name}</div>
      <div class="topbar-sub">{clinic.specialty} · Clinic Portal</div>
    </div>
    <button class="btn-logout" onclick="doLogout()">Sign Out</button>
  </div>

  <div class="dash-body">

    <!-- Tabs -->
    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('share', this)">📤 Share with Patients</button>
      <button class="tab-btn" onclick="switchTab('appts', this)" id="tab-btn-appts">📋 Appointments</button>
      <button class="tab-btn" onclick="switchTab('plan', this)" id="tab-btn-plan">💳 Plan & Billing</button>
      <button class="tab-btn" onclick="switchTab('try', this)">💬 Try Aria</button>
      <button class="tab-btn" onclick="switchTab('embed', this)">🔧 Embed on Website</button>
      <button class="tab-btn" id="tab-btn-whitelabel" onclick="switchTab('whitelabel', this)" style="display:none;">🏷️ White Label</button>
    </div>

    <!-- ── TAB 1: Share with Patients ── -->
    <div id="tab-share" class="tab-panel active">

      <div class="share-card">
        <h2>🔗 Patient Chat Link</h2>
        <p>Share this link with your patients via SMS, WhatsApp, or email. They can open it in any browser — no app or login needed — and start chatting with {clinic.agent_name} instantly.</p>
        <div class="url-row">
          <span class="url-text" id="patient-url"></span>
          <button class="btn-copy" onclick="copyText('patient-url', this)">Copy Link</button>
        </div>
        <div class="qr-box">
          <img id="qr-img" src="" width="160" height="160" alt="QR Code" />
          <p>Scan to open chat on mobile</p>
        </div>
      </div>

      <div class="share-card">
        <h2>📲 How to Share</h2>
        <p>Choose any channel to distribute the patient link:</p>
        <ul class="share-steps">
          <li>
            <span class="step-num">1</span>
            <div>
              <strong>Copy the link above</strong> and paste it into any message to your patients.
              <div class="channel-pills">
                <span class="pill">📱 SMS / Text</span>
                <span class="pill">💬 WhatsApp</span>
                <span class="pill">✉️ Email</span>
                <span class="pill">📘 Facebook</span>
                <span class="pill">📷 Instagram Bio</span>
              </div>
            </div>
          </li>
          <li>
            <span class="step-num">2</span>
            <div><strong>Print the QR code</strong> and display it at your front desk, waiting room, or on appointment reminder cards. Patients scan it and are connected instantly.</div>
          </li>
          <li>
            <span class="step-num">3</span>
            <div><strong>Add to email signatures</strong> — e.g., "Chat with our AI front desk: [link]" — so every email you send promotes self-service.</div>
          </li>
          <li>
            <span class="step-num">4</span>
            <div><strong>Embed on your website</strong> using the code in the "Embed on Website" tab above — a floating chat bubble appears on every page.</div>
          </li>
        </ul>
      </div>

    </div>

    <!-- ── TAB 2: Appointments ── -->
    <div id="tab-appts" class="tab-panel">
      <div class="share-card" style="padding-bottom:12px;">
        <h2 style="margin-bottom:14px;">📋 Patient Appointments</h2>
        <div class="appt-toolbar">
          <input id="appt-search" type="text" placeholder="Search by patient name, type, provider…"
                 oninput="filterAppts()" />
          <button class="btn-refresh" onclick="loadAppts()">↻ Refresh</button>
          <span class="appt-count" id="appt-count"></span>
        </div>
        <div class="appt-table-wrap">
          <table class="appt-table">
            <thead>
              <tr>
                <th>Confirmation #</th>
                <th>Patient</th>
                <th>Appointment</th>
                <th>Date / Time</th>
                <th>Provider</th>
                <th>Type</th>
                <th>Status</th>
                <th>Booked At</th>
              </tr>
            </thead>
            <tbody id="appt-tbody">
              <tr><td colspan="8" class="appt-empty">Loading appointments…</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ── TAB 3: Plan & Billing ── -->
    <div id="tab-plan" class="tab-panel">
      <div id="plan-loading" class="share-card" style="text-align:center;padding:40px;">
        Loading plan details…
      </div>
      <div id="plan-content" style="display:none;">

        <!-- Current plan card -->
        <div class="share-card" id="plan-summary-card">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px;">
            <div>
              <h2 id="plan-name-heading" style="margin-bottom:4px;">— Plan</h2>
              <div id="plan-status-text" style="font-size:13px;color:#6B7280;"></div>
            </div>
            <div id="plan-price-badge" style="font-size:22px;font-weight:800;color:#1E40AF;"></div>
          </div>

          <!-- Usage bar -->
          <div id="plan-usage-section" style="margin-bottom:20px;">
            <div style="display:flex;justify-content:space-between;font-size:13px;color:#374151;margin-bottom:6px;">
              <span>Conversations this month</span>
              <span id="plan-usage-text"></span>
            </div>
            <div style="background:#E5E7EB;border-radius:99px;height:8px;overflow:hidden;">
              <div id="plan-usage-bar" style="height:100%;border-radius:99px;background:#1E40AF;width:0%;transition:width .5s;"></div>
            </div>
          </div>

          <!-- Feature list -->
          <div id="plan-features" style="display:grid;grid-template-columns:1fr 1fr;gap:10px;"></div>
        </div>

        <!-- All plans comparison -->
        <div class="share-card">
          <h2 style="margin-bottom:18px;">Compare Plans</h2>
          <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;font-size:13px;">
              <thead>
                <tr>
                  <th style="text-align:left;padding:10px 12px;border-bottom:2px solid #E5E7EB;color:#374151;">Feature</th>
                  <th style="text-align:center;padding:10px 12px;border-bottom:2px solid #E5E7EB;color:#6B7280;">Starter<br><span style="font-weight:400;">$297/mo</span></th>
                  <th style="text-align:center;padding:10px 12px;border-bottom:2px solid #1E40AF;color:#1E40AF;background:#EFF6FF;">Professional<br><span style="font-weight:400;">$597/mo</span></th>
                  <th style="text-align:center;padding:10px 12px;border-bottom:2px solid #7C3AED;color:#7C3AED;">Enterprise<br><span style="font-weight:400;">$997/mo</span></th>
                </tr>
              </thead>
              <tbody id="plan-compare-body">
                <tr><td colspan="4" style="text-align:center;padding:20px;color:#9CA3AF;">Loading…</td></tr>
              </tbody>
            </table>
          </div>
          <div style="margin-top:16px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
            <button id="upgrade-btn" onclick="openUpgradeModal()"
               style="display:inline-block;background:#1E40AF;color:#fff;padding:10px 28px;
                      border-radius:8px;font-weight:700;border:none;cursor:pointer;font-size:14px;">
              Upgrade Plan →
            </button>
            <button id="cancel-sub-btn" onclick="openCancelModal()"
               style="display:none;background:#fff;color:#DC2626;padding:10px 22px;
                      border-radius:8px;font-weight:600;border:1.5px solid #DC2626;cursor:pointer;font-size:14px;">
              Cancel Subscription
            </button>
          </div>
        </div>

<!-- ── Upgrade Modal ── -->
<div id="upgrade-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;align-items:center;justify-content:center;">
  <div style="background:#fff;border-radius:12px;padding:32px;max-width:460px;width:92%;box-shadow:0 8px 40px rgba(0,0,0,.25);position:relative;">
    <button onclick="closeUpgradeModal()" style="position:absolute;top:14px;right:16px;background:none;border:none;font-size:20px;cursor:pointer;color:#6B7280;">✕</button>
    <h2 style="margin:0 0 4px;font-size:20px;">Upgrade Your Plan</h2>
    <p style="color:#6B7280;margin:0 0 20px;font-size:14px;">Choose a plan below. After clicking "Pay with PayPal" you'll complete payment, then we'll activate your new plan within 24 hours.</p>
    <div id="upgrade-options" style="display:flex;flex-direction:column;gap:12px;"></div>
    <div id="upgrade-msg" style="margin-top:14px;font-size:14px;display:none;"></div>
    <div style="margin-top:20px;text-align:right;">
      <button id="upgrade-submit-btn" onclick="submitUpgrade()"
        style="background:#1E40AF;color:#fff;padding:10px 24px;border-radius:8px;font-weight:700;border:none;cursor:pointer;font-size:14px;">
        Pay with PayPal →
      </button>
    </div>
  </div>
</div>

<!-- ── Cancel Subscription Modal ── -->
<div id="cancel-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;align-items:center;justify-content:center;">
  <div style="background:#fff;border-radius:12px;padding:32px;max-width:440px;width:92%;box-shadow:0 8px 40px rgba(0,0,0,.25);position:relative;">
    <button onclick="closeCancelModal()" style="position:absolute;top:14px;right:16px;background:none;border:none;font-size:20px;cursor:pointer;color:#6B7280;">✕</button>
    <div style="text-align:center;margin-bottom:20px;">
      <div style="font-size:40px;margin-bottom:8px;">⚠️</div>
      <h2 style="margin:0 0 6px;font-size:20px;color:#DC2626;">Cancel Subscription?</h2>
      <p style="color:#6B7280;margin:0;font-size:14px;">Your access will remain active until the end of your current billing period. This action cannot be undone.</p>
    </div>
    <div id="cancel-ends-at-note" style="background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;padding:10px 14px;font-size:13px;color:#991B1B;margin-bottom:20px;display:none;"></div>
    <div id="cancel-modal-msg" style="font-size:13px;margin-bottom:12px;display:none;"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end;">
      <button onclick="closeCancelModal()" style="background:#F3F4F6;color:#374151;padding:10px 20px;border-radius:8px;font-weight:600;border:none;cursor:pointer;font-size:14px;">
        Keep Subscription
      </button>
      <button id="cancel-confirm-btn" onclick="confirmCancelSubscription()"
        style="background:#DC2626;color:#fff;padding:10px 20px;border-radius:8px;font-weight:700;border:none;cursor:pointer;font-size:14px;">
        Yes, Cancel →
      </button>
    </div>
  </div>
</div>

      </div>
    </div>

    <!-- ── TAB 4: Try Aria ── -->
    <div id="tab-try" class="tab-panel">
      <div class="share-card" style="text-align:center;padding:28px 24px;">
        <div style="font-size:48px;margin-bottom:12px;">💬</div>
        <h2 style="margin:0 0 8px;">Chat with {clinic.agent_name} Now</h2>
        <p style="color:#6B7280;margin:0 0 20px;">Experience exactly what your patients will see when they reach out.</p>
        <a id="open-chat-btn" href="/chat/{clinic_slug}" target="_blank"
           style="display:inline-block;background:#1E40AF;color:#fff;text-align:center;
                  padding:14px 32px;border-radius:8px;font-weight:700;text-decoration:none;
                  font-size:16px;letter-spacing:.3px;">
          Open Patient Chat →
        </a>
        <p style="margin-top:14px;font-size:13px;color:#9CA3AF;">
          Or use the 💬 bubble in the bottom-right corner of this page.
        </p>
      </div>
      <div class="share-card">
        <h2>Test scenarios to try:</h2>
        <ul class="share-steps">
          <li><span class="step-num">→</span><div>"I want to book an appointment for tomorrow"</div></li>
          <li><span class="step-num">→</span><div>"Does Blue Cross cover my procedure?"</div></li>
          <li><span class="step-num">→</span><div>"I want to cancel my appointment"</div></li>
          <li><span class="step-num">→</span><div>"Why is my bill $350?"</div></li>
          <li><span class="step-num">→</span><div>"I am a new patient"</div></li>
          <li><span class="step-num">→</span><div>"Show today's appointments" (admin query)</div></li>
          <li><span class="step-num">→</span><div>"My father has chest pain and cannot breathe" (emergency test)</div></li>
        </ul>
      </div>
    </div>

    <!-- ── TAB 3: Embed on Website ── -->
    <div id="tab-embed" class="tab-panel">
      <div class="share-card">
        <h2>🔧 Embed on Your Website</h2>
        <p>Paste this snippet just before the <code>&lt;/body&gt;</code> tag on any page of your website. A floating chat bubble will appear for all visitors — no backend changes needed.</p>
        <div class="embed-box" id="embed-code"></div>
        <button class="btn-copy" onclick="copyText('embed-code', this)">Copy Embed Code</button>
      </div>
      <div class="share-card">
        <h2>📧 Patient Invite Message Template</h2>
        <p>Copy and send this to your patients via SMS or email:</p>
        <div class="embed-box" id="invite-msg"></div>
        <button class="btn-copy" onclick="copyText('invite-msg', this)">Copy Message</button>
      </div>
    </div>

    <!-- ── TAB 6: White Label ── -->
    <div id="tab-whitelabel" class="tab-panel">
      <div id="wl-loading" class="share-card" style="text-align:center;padding:40px;">Loading white label settings…</div>
      <div id="wl-content" style="display:none;">

        <!-- Branding Card -->
        <div class="share-card">
          <h2>🎨 Custom Branding</h2>
          <p style="font-size:13px;color:#6B7280;margin-bottom:20px;">Customize your platform's look and feel with your own brand colors, logo, and company name.</p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px;">
            <div>
              <label style="font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:5px;">Company Name</label>
              <input id="wl-company-name" type="text" placeholder="Your Company Name"
                style="width:100%;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;outline:none;box-sizing:border-box;"
                onfocus="this.style.borderColor='#1E40AF'" onblur="this.style.borderColor='#E5E7EB'"/>
            </div>
            <div>
              <label style="font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:5px;">Logo URL</label>
              <input id="wl-logo-url" type="url" placeholder="https://yoursite.com/logo.png"
                style="width:100%;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;outline:none;box-sizing:border-box;"
                onfocus="this.style.borderColor='#1E40AF'" onblur="this.style.borderColor='#E5E7EB'"/>
            </div>
            <div>
              <label style="font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:5px;">Primary Color</label>
              <div style="display:flex;gap:8px;align-items:center;">
                <input id="wl-primary-color-picker" type="color" value="#007ACC"
                  style="width:40px;height:36px;border:1px solid #E5E7EB;border-radius:6px;cursor:pointer;padding:2px;"
                  oninput="document.getElementById('wl-primary-color').value=this.value"/>
                <input id="wl-primary-color" type="text" placeholder="#007ACC" maxlength="7"
                  style="flex:1;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;outline:none;font-family:monospace;"
                  onfocus="this.style.borderColor='#1E40AF'" onblur="this.style.borderColor='#E5E7EB'"
                  oninput="if(this.value.startsWith('#')&&this.value.length===7)document.getElementById('wl-primary-color-picker').value=this.value"/>
              </div>
            </div>
            <div>
              <label style="font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:5px;">Accent Color</label>
              <div style="display:flex;gap:8px;align-items:center;">
                <input id="wl-accent-color-picker" type="color" value="#FF6B6B"
                  style="width:40px;height:36px;border:1px solid #E5E7EB;border-radius:6px;cursor:pointer;padding:2px;"
                  oninput="document.getElementById('wl-accent-color').value=this.value"/>
                <input id="wl-accent-color" type="text" placeholder="#FF6B6B" maxlength="7"
                  style="flex:1;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;outline:none;font-family:monospace;"
                  onfocus="this.style.borderColor='#1E40AF'" onblur="this.style.borderColor='#E5E7EB'"
                  oninput="if(this.value.startsWith('#')&&this.value.length===7)document.getElementById('wl-accent-color-picker').value=this.value"/>
              </div>
            </div>
          </div>
          <div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap;">
            <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;">
              <input id="wl-remove-tabor" type="checkbox"
                style="width:16px;height:16px;cursor:pointer;accent-color:#7C3AED;"/>
              Remove Tabor branding from UI
            </label>
            <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;">
              <input id="wl-remove-powered-by" type="checkbox"
                style="width:16px;height:16px;cursor:pointer;accent-color:#7C3AED;"/>
              Remove "Powered by Tabor" footer
            </label>
          </div>
          <div style="margin-bottom:16px;">
            <label style="font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:5px;">Custom Footer Text</label>
            <input id="wl-footer-text" type="text" placeholder="© 2026 Your Company. All rights reserved."
              style="width:100%;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;outline:none;box-sizing:border-box;"
              onfocus="this.style.borderColor='#1E40AF'" onblur="this.style.borderColor='#E5E7EB'"/>
          </div>
          <button id="wl-save-branding-btn" onclick="saveWlBranding()"
            style="background:#1E40AF;color:#fff;padding:10px 24px;border-radius:8px;font-weight:700;border:none;cursor:pointer;font-size:14px;">
            Save Branding →
          </button>
          <span id="wl-branding-msg" style="margin-left:12px;font-size:13px;display:none;"></span>
        </div>

        <!-- Custom Domain Card -->
        <div class="share-card">
          <h2>🌐 Custom Domain</h2>
          <p style="font-size:13px;color:#6B7280;margin-bottom:16px;">Map your own domain (e.g. <code>clinic.yourcompany.com</code>) to this platform. DNS verification required.</p>
          <div id="wl-domain-current" style="font-size:13px;color:#374151;margin-bottom:12px;display:none;">
            Current: <strong id="wl-current-domain"></strong>
            <span id="wl-domain-verified-badge" style="margin-left:8px;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:700;"></span>
          </div>
          <div style="display:flex;gap:10px;align-items:flex-start;">
            <input id="wl-custom-domain" type="text" placeholder="clinic.yourcompany.com"
              style="flex:1;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;outline:none;"
              onfocus="this.style.borderColor='#1E40AF'" onblur="this.style.borderColor='#E5E7EB'"/>
            <button onclick="setWlDomain()"
              style="background:#059669;color:#fff;padding:10px 20px;border-radius:8px;font-weight:700;border:none;cursor:pointer;font-size:14px;white-space:nowrap;">
              Set Domain →
            </button>
          </div>
          <div id="wl-domain-instructions" style="display:none;margin-top:14px;background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;padding:12px;font-size:13px;line-height:1.6;"></div>
          <span id="wl-domain-msg" style="display:block;margin-top:8px;font-size:13px;"></span>
        </div>

        <!-- Reseller Card -->
        <div class="share-card">
          <h2>🤝 Reseller Mode</h2>
          <p style="font-size:13px;color:#6B7280;margin-bottom:16px;">Enable reseller mode to create and manage your own clinic sub-tenants. Set a commission rate and billing rules.</p>
          <div id="wl-reseller-status" style="margin-bottom:16px;padding:10px 14px;border-radius:8px;font-size:13px;background:#F9FAFB;border:1px solid #E5E7EB;"></div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px;" id="wl-reseller-form">
            <div>
              <label style="font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:5px;">Commission Rate (%)</label>
              <input id="wl-commission" type="number" placeholder="20" min="0" max="30" step="0.5"
                style="width:100%;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;outline:none;box-sizing:border-box;"
                onfocus="this.style.borderColor='#1E40AF'" onblur="this.style.borderColor='#E5E7EB'"/>
            </div>
            <div>
              <label style="font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:5px;">Max Sub-Clinics (0 = unlimited)</label>
              <input id="wl-max-subs" type="number" placeholder="0" min="0"
                style="width:100%;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;outline:none;box-sizing:border-box;"
                onfocus="this.style.borderColor='#1E40AF'" onblur="this.style.borderColor='#E5E7EB'"/>
            </div>
          </div>
          <button onclick="enableReseller()"
            style="background:#7C3AED;color:#fff;padding:10px 24px;border-radius:8px;font-weight:700;border:none;cursor:pointer;font-size:14px;">
            Enable Reseller Mode →
          </button>
          <span id="wl-reseller-msg" style="margin-left:12px;font-size:13px;display:none;"></span>
        </div>

        <!-- Source Code / Self-hosting Card -->
        <div class="share-card">
          <h2>💻 Source Code &amp; Self-Hosting</h2>
          <p style="font-size:13px;color:#6B7280;margin-bottom:16px;">Request access to the full source code to deploy on your own infrastructure. Includes Docker setup and support documentation.</p>
          <div id="wl-source-status" style="margin-bottom:16px;font-size:13px;color:#374151;"></div>
          <button id="wl-source-btn" onclick="requestSourceAccess()"
            style="background:#0F172A;color:#fff;padding:10px 24px;border-radius:8px;font-weight:700;border:none;cursor:pointer;font-size:14px;">
            Grant Source Code Access →
          </button>
          <div id="wl-source-instructions" style="display:none;margin-top:16px;background:#F0FDF4;border:1px solid #86EFAC;border-radius:8px;padding:14px;font-size:13px;line-height:1.8;white-space:pre-line;font-family:monospace;"></div>
          <span id="wl-source-msg" style="display:block;margin-top:8px;font-size:13px;"></span>
        </div>

      </div><!-- /wl-content -->
    </div><!-- /tab-whitelabel -->

  </div><!-- /dash-body -->
</div><!-- /dash-screen -->

<script>
var SLUG  = "{clinic_slug}";
var NAME  = "{clinic.name}";
var AGENT = "{clinic.agent_name}";
var TKEY  = "aria_token_" + SLUG;

function switchTab(name, btn) {{
  document.querySelectorAll(".tab-panel").forEach(function(p) {{ p.classList.remove("active"); }});
  document.querySelectorAll(".tab-btn").forEach(function(b) {{ b.classList.remove("active"); }});
  document.getElementById("tab-" + name).classList.add("active");
  btn.classList.add("active");
  if (name === "appts")      loadAppts();
  if (name === "plan")       loadPlan();
  if (name === "whitelabel") loadWhitelabel();
}}

var _allAppts = [];

function loadAppts() {{
  var token = localStorage.getItem(TKEY);
  var tbody = document.getElementById("appt-tbody");
  var countEl = document.getElementById("appt-count");
  tbody.innerHTML = '<tr><td colspan="8" class="appt-empty">Loading…</td></tr>';
  if (countEl) countEl.textContent = "";
  fetch("/api/" + SLUG + "/appointments", {{
    headers: {{ "X-Clinic-Token": token || "" }}
  }})
  .then(function(r) {{ return r.json(); }})
  .then(function(data) {{
    if (!Array.isArray(data)) {{
      tbody.innerHTML = '<tr><td colspan="8" class="appt-empty">⚠️ Failed to load appointments.</td></tr>';
      return;
    }}
    _allAppts = data;
    renderAppts(data);
  }})
  .catch(function() {{
    tbody.innerHTML = '<tr><td colspan="8" class="appt-empty">⚠️ Network error loading appointments.</td></tr>';
  }});
}}

function renderAppts(appts) {{
  var tbody = document.getElementById("appt-tbody");
  var countEl = document.getElementById("appt-count");
  if (countEl) countEl.textContent = appts.length + " record" + (appts.length === 1 ? "" : "s");
  if (!appts.length) {{
    tbody.innerHTML = '<tr><td colspan="8" class="appt-empty">📭 No appointments yet.<p>Share the patient link and appointments booked via Aria will appear here.</p></td></tr>';
    return;
  }}
  tbody.innerHTML = appts.map(function(a) {{
    var badgeCls = a.status === "scheduled" ? "badge-scheduled"
                 : a.status === "cancelled"  ? "badge-cancelled"
                 : "badge-rescheduled";
    var newPt = a.is_new_patient ? '<span style="font-size:10px;color:#7C3AED;font-weight:600;">NEW</span> ' : "";
    var phone = a.patient_phone ? '<br><span style="color:#6B7280;font-size:11px;">📞 ' + a.patient_phone + '</span>' : "";
    var email = a.patient_email ? '<br><span style="color:#6B7280;font-size:11px;">✉️ ' + a.patient_email + '</span>' : "";
    var dob   = a.patient_dob   ? '<br><span style="color:#6B7280;font-size:11px;">DOB: ' + a.patient_dob + '</span>' : "";
    var cc    = a.chief_complaint ? '<br><span style="color:#6B7280;font-size:11px;font-style:italic;">' + a.chief_complaint + '</span>' : "";
    return '<tr>' +
      '<td style="font-family:monospace;font-size:12px;">' + (a.confirmation_number || "—") + '</td>' +
      '<td>' + newPt + '<strong>' + a.patient_name + '</strong>' + phone + email + dob + '</td>' +
      '<td>' + a.appointment_type + cc + '</td>' +
      '<td style="white-space:nowrap;">' + (a.appointment_datetime || "—") + '</td>' +
      '<td>' + (a.provider || "—") + '</td>' +
      '<td><span style="font-size:11px;color:#4B5563;">' + (a.channel || "web").toUpperCase() + '</span></td>' +
      '<td><span class="badge ' + badgeCls + '">' + a.status + '</span></td>' +
      '<td style="white-space:nowrap;font-size:12px;color:#6B7280;">' + (a.booked_at || "—") + '</td>' +
    '</tr>';
  }}).join("");
}}

function loadPlan() {{
  var token = localStorage.getItem(TKEY);
  fetch("/api/" + SLUG + "/plan", {{ headers: {{ "X-Clinic-Token": token || "" }} }})
    .then(function(r) {{ return r.json(); }})
    .then(function(p) {{
      document.getElementById("plan-loading").style.display = "none";
      document.getElementById("plan-content").style.display = "block";

      // Track current plan for upgrade modal
      _currentPlanKey = p.plan_key || "professional";
      _currentSubStatus = p.subscription_status || "active";
      _currentEndsAt = p.subscription_ends_at || null;
      maybeShowWlTab(_currentPlanKey);

      var upgradeBtn = document.getElementById("upgrade-btn");
      if (upgradeBtn) {{
        if (_currentPlanKey === "enterprise" || _currentSubStatus === "cancelled") {{
          upgradeBtn.style.display = "none";
        }} else {{
          upgradeBtn.style.display = "inline-block";
          upgradeBtn.textContent = "Upgrade Plan →";
        }}
      }}

      // Show cancel button only for active paid subscriptions
      var cancelBtn = document.getElementById("cancel-sub-btn");
      if (cancelBtn) {{
        if (_currentSubStatus === "active") {{
          cancelBtn.style.display = "inline-block";
        }} else {{
          cancelBtn.style.display = "none";
        }}
      }}

      // Heading & status
      document.getElementById("plan-name-heading").textContent = p.plan_name + " Plan";
      document.getElementById("plan-price-badge").textContent  = "$" + p.price + "/mo";
      var statusMap = {{ trial:"🟡 Trial", active:"🟢 Active", past_due:"🔴 Past Due", cancelled:"⚫ Cancelled" }};
      var statusStr = (statusMap[p.subscription_status] || p.subscription_status);
      if (p.subscription_status === "trial" && p.trial_ends_at)
        statusStr += " · Ends " + p.trial_ends_at;
      else if (p.subscription_status === "active" && p.subscription_ends_at)
        statusStr += " · Renews " + p.subscription_ends_at;
      document.getElementById("plan-status-text").textContent = statusStr;

      // Usage bar
      var used  = p.conversations_used;
      var limit = p.conversations_limit;
      var usageSection = document.getElementById("plan-usage-section");
      var usageText    = document.getElementById("plan-usage-text");
      var usageBar     = document.getElementById("plan-usage-bar");
      if (limit === null) {{
        usageText.textContent = used + " used (Unlimited)";
        usageBar.style.width  = "20%";
        usageBar.style.background = "#059669";
      }} else {{
        var pct = Math.min(100, Math.round((used / limit) * 100));
        usageText.textContent  = used + " / " + limit;
        usageBar.style.width   = pct + "%";
        usageBar.style.background = pct >= 90 ? "#DC2626" : pct >= 70 ? "#D97706" : "#1E40AF";
      }}

      // Feature cards
      var fRows = [
        ["💬 SMS / WhatsApp",          p.features.sms],
        ["🔧 Website embed widget",    p.features.widget_embed],
        ["✏️ Custom agent name",       p.features.custom_agent_name],
        ["🏷️ White-label branding",   p.features.white_label],
        ["📍 Max locations",           p.features.max_locations === null ? "Unlimited" : p.features.max_locations],
        ["🎧 Support",                 p.features.support],
      ];
      var featEl = document.getElementById("plan-features");
      featEl.innerHTML = fRows.map(function(r) {{
        var val = r[1];
        var display = val === true  ? '<span style="color:#059669;font-weight:700;">✅ Included</span>'
                    : val === false ? '<span style="color:#9CA3AF;">❌ Not included</span>'
                    : '<span style="color:#1E40AF;font-weight:600;">' + val + '</span>';
        return '<div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;padding:10px 12px;">' +
               '<div style="font-size:12px;color:#6B7280;margin-bottom:3px;">' + r[0] + '</div>' +
               '<div style="font-size:13px;">' + display + '</div></div>';
      }}).join("");

      // Comparison table
      var ALL_PLANS = [
        {{ key:"starter",      name:"Starter",      price:297,  limit:300,  sms:false, embed:false, custom:false, wl:false, locs:1,    sup:"Email" }},
        {{ key:"professional", name:"Professional",  price:597,  limit:1000, sms:true,  embed:true,  custom:true,  wl:false, locs:3,    sup:"Priority email" }},
        {{ key:"enterprise",   name:"Enterprise",    price:997,  limit:null, sms:true,  embed:true,  custom:true,  wl:true,  locs:null, sup:"Priority email" }},
      ];
      var FEAT_ROWS = [
        ["Conversations/month", function(pl) {{ return pl.limit === null ? "Unlimited" : pl.limit.toLocaleString(); }}],
        ["Web AI chat",         function()   {{ return "✅"; }}],
        ["Appointment booking", function()   {{ return "✅"; }}],
        ["Insurance & billing", function()   {{ return "✅"; }}],
        ["Appointments dashboard", function(){{ return "✅"; }}],
        ["SMS / WhatsApp",      function(pl) {{ return pl.sms   ? "✅" : "❌"; }}],
        ["Website embed widget",function(pl) {{ return pl.embed ? "✅" : "❌"; }}],
        ["Custom agent name",   function(pl) {{ return pl.custom? "✅" : "❌"; }}],
        ["White-label",         function(pl) {{ return pl.wl    ? "✅" : "❌"; }}],
        ["Max clinic locations",function(pl) {{ return pl.locs  === null ? "Unlimited" : pl.locs; }}],
        ["Support",             function(pl) {{ return pl.sup; }}],
      ];
      var tbody = document.getElementById("plan-compare-body");
      tbody.innerHTML = FEAT_ROWS.map(function(row) {{
        var cells = ALL_PLANS.map(function(pl) {{
          var isActive = (pl.key === p.plan_key);
          return '<td style="text-align:center;padding:9px 12px;' +
                 (isActive ? 'background:#EFF6FF;font-weight:600;' : '') + '">' +
                 row[1](pl) + '</td>';
        }}).join("");
        return '<tr><td style="padding:9px 12px;color:#374151;border-bottom:1px solid #F3F4F6;">' +
               row[0] + '</td>' + cells + '</tr>';
      }}).join("");
    }})
    .catch(function() {{
      document.getElementById("plan-loading").textContent = "⚠️ Failed to load plan details.";
    }});
}}

// ── Upgrade modal ──────────────────────────────────────────────────────────
var _currentPlanKey = "professional";
var _selectedUpgradePlan = null;

var _UPGRADE_PLANS = [
  {{ key:"starter",      name:"Starter",      price:297,  desc:"300 patient sessions/mo · Email support" }},
  {{ key:"professional", name:"Professional",  price:597,  desc:"1,000 sessions/mo · SMS · Website widget · Priority email" }},
  {{ key:"enterprise",   name:"Enterprise",    price:997,  desc:"Unlimited sessions · White-label · Priority email" }},
];

var _PLAN_ORDER = {{ starter:0, professional:1, enterprise:2 }};

function openUpgradeModal() {{
  var modal = document.getElementById("upgrade-modal");
  modal.style.display = "flex";
  document.getElementById("upgrade-msg").style.display = "none";
  document.getElementById("upgrade-submit-btn").disabled = false;
  document.getElementById("upgrade-submit-btn").textContent = "Pay with PayPal →";
  _selectedUpgradePlan = null;
  var currentOrder = _PLAN_ORDER[_currentPlanKey] !== undefined ? _PLAN_ORDER[_currentPlanKey] : 1;
  var higher = _UPGRADE_PLANS.filter(function(p) {{ return _PLAN_ORDER[p.key] > currentOrder; }});
  var optionsEl = document.getElementById("upgrade-options");
  if (!higher.length) {{
    optionsEl.innerHTML = '<p style="color:#6B7280;text-align:center;">You are already on the highest plan.</p>';
    document.getElementById("upgrade-submit-btn").style.display = "none";
    return;
  }}
  document.getElementById("upgrade-submit-btn").style.display = "";
  optionsEl.innerHTML = higher.map(function(p) {{
    var colors = {{ starter:"#6B7280", professional:"#1E40AF", enterprise:"#7C3AED" }};
    var c = colors[p.key] || "#1E40AF";
    return '<label style="display:flex;align-items:flex-start;gap:12px;border:2px solid #E5E7EB;border-radius:10px;padding:14px 16px;cursor:pointer;transition:border-color .15s;" ' +
           'data-key="' + p.key + '" onclick="selectUpgradePlan(this, \\'' + p.key + '\\')">' +
           '<input type="radio" name="upgrade_plan" value="' + p.key + '" style="margin-top:3px;">' +
           '<div>' +
           '<div style="font-weight:700;color:' + c + ';font-size:15px;">' + p.name + ' — $' + p.price + '/mo</div>' +
           '<div style="font-size:12px;color:#6B7280;margin-top:3px;">' + p.desc + '</div>' +
           '</div></label>';
  }}).join("");
}}

function selectUpgradePlan(label, key) {{
  _selectedUpgradePlan = key;
  document.querySelectorAll("#upgrade-options label").forEach(function(el) {{
    var colors = {{ starter:"#6B7280", professional:"#1E40AF", enterprise:"#7C3AED" }};
    var isThis = el.dataset.key === key;
    el.style.borderColor = isThis ? (colors[key] || "#1E40AF") : "#E5E7EB";
    el.style.background  = isThis ? "#F0F4FF" : "#fff";
    var radio = el.querySelector("input[type=radio]");
    if (radio) radio.checked = isThis;
  }});
}}

function closeUpgradeModal() {{
  document.getElementById("upgrade-modal").style.display = "none";
}}

function submitUpgrade() {{
  if (!_selectedUpgradePlan) {{
    showUpgradeMsg("Please select a plan.", "#DC2626");
    return;
  }}
  var btn = document.getElementById("upgrade-submit-btn");
  btn.disabled = true;
  btn.textContent = "Sending…";
  var token = localStorage.getItem(TKEY);
  fetch("/api/" + SLUG + "/upgrade-request", {{
    method: "POST",
    headers: {{ "Content-Type": "application/json", "X-Clinic-Token": token || "" }},
    body: JSON.stringify({{ plan: _selectedUpgradePlan }})
  }})
  .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
  .then(function(res) {{
    if (!res.ok) {{
      showUpgradeMsg("⚠️ " + (res.data.error || "Request failed."), "#DC2626");
      btn.disabled = false;
      btn.textContent = "Pay with PayPal →";
      return;
    }}
    var d = res.data;
    window.open(d.paypal_url, "_blank");
    showUpgradeMsg(
      "✅ PayPal payment link opened! Once payment is confirmed, we'll activate your <strong>" +
      d.new_plan.charAt(0).toUpperCase() + d.new_plan.slice(1) +
      "</strong> plan ($" + d.new_price + "/mo) within 24 hours.",
      "#059669"
    );
    btn.style.display = "none";
  }})
  .catch(function() {{
    showUpgradeMsg("⚠️ Network error. Please try again.", "#DC2626");
    btn.disabled = false;
    btn.textContent = "Pay with PayPal →";
  }});
}}

function showUpgradeMsg(html, color) {{
  var el = document.getElementById("upgrade-msg");
  el.innerHTML = html;
  el.style.color = color || "#374151";
  el.style.display = "block";
}}

// ── Cancel Subscription ───────────────────────────────────────────────────────
var _currentSubStatus = "active";
var _currentEndsAt    = null;

function openCancelModal() {{
  var modal = document.getElementById("cancel-modal");
  modal.style.display = "flex";
  document.getElementById("cancel-modal-msg").style.display = "none";
  document.getElementById("cancel-confirm-btn").disabled = false;
  document.getElementById("cancel-confirm-btn").textContent = "Yes, Cancel →";

  var noteEl = document.getElementById("cancel-ends-at-note");
  if (_currentEndsAt) {{
    noteEl.textContent = "Your access will remain active until " + _currentEndsAt + ".";
    noteEl.style.display = "block";
  }} else {{
    noteEl.style.display = "none";
  }}
}}

function closeCancelModal() {{
  document.getElementById("cancel-modal").style.display = "none";
}}

function confirmCancelSubscription() {{
  var token = localStorage.getItem(TKEY);
  var btn = document.getElementById("cancel-confirm-btn");
  var msg = document.getElementById("cancel-modal-msg");
  btn.disabled = true;
  btn.textContent = "Cancelling…";

  fetch("/api/" + SLUG + "/cancel-subscription", {{
    method: "POST",
    headers: {{ "X-Clinic-Token": token || "" }}
  }})
  .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
  .then(function(res) {{
    msg.style.display = "block";
    if (res.ok) {{
      msg.style.color = "#059669";
      msg.textContent = "✅ " + (res.data.message || "Subscription cancelled.");
      btn.style.display = "none";
      // Update UI to reflect cancelled status
      document.getElementById("cancel-sub-btn").style.display = "none";
      document.getElementById("upgrade-btn").style.display = "none";
      _currentSubStatus = "cancelled";
      // Reload plan section after 2s
      setTimeout(function() {{ closeCancelModal(); loadPlan(); }}, 2500);
    }} else {{
      msg.style.color = "#DC2626";
      msg.textContent = "⚠️ " + (res.data.error || "Failed to cancel.");
      btn.disabled = false;
      btn.textContent = "Yes, Cancel →";
    }}
  }})
  .catch(function() {{
    msg.style.display = "block";
    msg.style.color = "#DC2626";
    msg.textContent = "⚠️ Network error. Please try again.";
    btn.disabled = false;
    btn.textContent = "Yes, Cancel →";
  }});
}}

// ── White Label ──────────────────────────────────────────────────────────────
var _wlLoaded = false;

function loadWhitelabel() {{
  if (_wlLoaded) return;
  var token = localStorage.getItem(TKEY);
  fetch("/api/" + SLUG + "/whitelabel", {{
    headers: {{ "X-Clinic-Token": token || "" }}
  }})
  .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
  .then(function(res) {{
    document.getElementById("wl-loading").style.display = "none";
    if (!res.ok) {{
      document.getElementById("wl-loading").textContent = "⚠️ " + (res.data.error || "White label not available on your plan.");
      document.getElementById("wl-loading").style.display = "block";
      return;
    }}
    _wlLoaded = true;
    var d = res.data;
    document.getElementById("wl-content").style.display = "block";
    // Populate branding fields
    document.getElementById("wl-company-name").value      = d.company_name || "";
    document.getElementById("wl-logo-url").value          = d.logo_url || "";
    document.getElementById("wl-primary-color").value     = d.primary_color || "#007ACC";
    document.getElementById("wl-primary-color-picker").value = d.primary_color || "#007ACC";
    document.getElementById("wl-accent-color").value      = d.accent_color || "#FF6B6B";
    document.getElementById("wl-accent-color-picker").value  = d.accent_color || "#FF6B6B";
    document.getElementById("wl-remove-tabor").checked    = !!d.remove_tabor_branding;
    document.getElementById("wl-remove-powered-by").checked = !!d.remove_powered_by;
    document.getElementById("wl-footer-text").value       = d.custom_footer_text || "";
    // Domain
    if (d.custom_domain) {{
      document.getElementById("wl-domain-current").style.display = "block";
      document.getElementById("wl-current-domain").textContent   = d.custom_domain;
      var badge = document.getElementById("wl-domain-verified-badge");
      if (d.domain_verified) {{
        badge.textContent = "✅ Verified";
        badge.style.background = "#D1FAE5"; badge.style.color = "#065F46";
      }} else {{
        badge.textContent = "⏳ Pending DNS";
        badge.style.background = "#FEF3C7"; badge.style.color = "#92400E";
      }}
    }}
    // Reseller
    var rStatus = document.getElementById("wl-reseller-status");
    if (d.is_reseller) {{
      rStatus.style.background = "#EDE9FE"; rStatus.style.borderColor = "#DDD6FE";
      rStatus.innerHTML = '<strong style="color:#7C3AED;">✅ Reseller Mode Active</strong>';
    }} else {{
      rStatus.textContent = "Reseller mode is currently disabled. Enable it below to start creating sub-clinics.";
    }}
    // Source code
    var srcEl = document.getElementById("wl-source-status");
    if (d.can_access_source) {{
      srcEl.innerHTML = '<strong style="color:#059669;">✅ Source code access granted.</strong> Clone the private repo and follow the self-hosting guide.';
      document.getElementById("wl-source-btn").textContent = "View Setup Instructions →";
    }} else {{
      srcEl.textContent = "Source code access not yet activated. Click below to grant access.";
    }}
  }})
  .catch(function() {{
    document.getElementById("wl-loading").textContent = "⚠️ Network error loading white label settings.";
  }});
}}

function saveWlBranding() {{
  var token = localStorage.getItem(TKEY);
  var btn = document.getElementById("wl-save-branding-btn");
  var msg = document.getElementById("wl-branding-msg");
  btn.disabled = true;
  btn.textContent = "Saving…";
  fetch("/api/" + SLUG + "/whitelabel", {{
    method: "PATCH",
    headers: {{ "X-Clinic-Token": token || "", "Content-Type": "application/json" }},
    body: JSON.stringify({{
      company_name:         document.getElementById("wl-company-name").value.trim(),
      logo_url:             document.getElementById("wl-logo-url").value.trim(),
      primary_color:        document.getElementById("wl-primary-color").value.trim(),
      accent_color:         document.getElementById("wl-accent-color").value.trim(),
      remove_tabor_branding: document.getElementById("wl-remove-tabor").checked,
      remove_powered_by:    document.getElementById("wl-remove-powered-by").checked,
      custom_footer_text:   document.getElementById("wl-footer-text").value.trim(),
    }})
  }})
  .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
  .then(function(res) {{
    btn.disabled = false; btn.textContent = "Save Branding →";
    msg.style.display = "inline";
    if (res.ok) {{
      msg.textContent = "✅ Branding saved!"; msg.style.color = "#059669";
    }} else {{
      msg.textContent = "⚠️ " + (res.data.error || "Save failed."); msg.style.color = "#DC2626";
    }}
    setTimeout(function() {{ msg.style.display = "none"; }}, 4000);
  }})
  .catch(function() {{
    btn.disabled = false; btn.textContent = "Save Branding →";
    msg.textContent = "⚠️ Network error."; msg.style.color = "#DC2626"; msg.style.display = "inline";
  }});
}}

function setWlDomain() {{
  var token = localStorage.getItem(TKEY);
  var domain = document.getElementById("wl-custom-domain").value.trim();
  var msg = document.getElementById("wl-domain-msg");
  if (!domain) {{ msg.textContent = "⚠️ Enter a domain."; msg.style.color = "#DC2626"; return; }}
  fetch("/api/" + SLUG + "/whitelabel/domain", {{
    method: "POST",
    headers: {{ "X-Clinic-Token": token || "", "Content-Type": "application/json" }},
    body: JSON.stringify({{ custom_domain: domain }})
  }})
  .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
  .then(function(res) {{
    if (res.ok) {{
      msg.textContent = "✅ Domain saved. DNS verification pending."; msg.style.color = "#059669";
      var instrEl = document.getElementById("wl-domain-instructions");
      instrEl.style.display = "block";
      instrEl.innerHTML = "<strong>DNS Setup Required:</strong><br>" + res.data.verification_instructions;
      document.getElementById("wl-domain-current").style.display = "block";
      document.getElementById("wl-current-domain").textContent = res.data.custom_domain;
      _wlLoaded = false; // Force refresh next time
    }} else {{
      msg.textContent = "⚠️ " + (res.data.error || "Failed."); msg.style.color = "#DC2626";
    }}
  }})
  .catch(function() {{ msg.textContent = "⚠️ Network error."; msg.style.color = "#DC2626"; }});
}}

function enableReseller() {{
  var token = localStorage.getItem(TKEY);
  var msg = document.getElementById("wl-reseller-msg");
  var commission = parseFloat(document.getElementById("wl-commission").value) || 20;
  var maxSubs = parseInt(document.getElementById("wl-max-subs").value) || 0;
  fetch("/api/" + SLUG + "/whitelabel/reseller/enable", {{
    method: "POST",
    headers: {{ "X-Clinic-Token": token || "", "Content-Type": "application/json" }},
    body: JSON.stringify({{ reseller_commission: commission, max_sub_clinics: maxSubs }})
  }})
  .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
  .then(function(res) {{
    msg.style.display = "inline";
    if (res.ok) {{
      msg.textContent = "✅ Reseller mode enabled!"; msg.style.color = "#7C3AED";
      var rStatus = document.getElementById("wl-reseller-status");
      rStatus.style.background = "#EDE9FE"; rStatus.style.borderColor = "#DDD6FE";
      rStatus.innerHTML = '<strong style="color:#7C3AED;">✅ Reseller Mode Active</strong> · Commission: ' +
                           res.data.reseller_commission + '% · Sub-clinics: ' + res.data.max_sub_clinics;
    }} else {{
      msg.textContent = "⚠️ " + (res.data.error || "Failed."); msg.style.color = "#DC2626";
    }}
    setTimeout(function() {{ msg.style.display = "none"; }}, 5000);
  }})
  .catch(function() {{ msg.textContent = "⚠️ Network error."; msg.style.color = "#DC2626"; msg.style.display = "inline"; }});
}}

function requestSourceAccess() {{
  var token = localStorage.getItem(TKEY);
  var msg = document.getElementById("wl-source-msg");
  fetch("/api/" + SLUG + "/whitelabel/source-code", {{
    method: "POST",
    headers: {{ "X-Clinic-Token": token || "" }}
  }})
  .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
  .then(function(res) {{
    if (res.ok) {{
      msg.textContent = "✅ Source code access granted!"; msg.style.color = "#059669";
      document.getElementById("wl-source-status").innerHTML =
        '<strong style="color:#059669;">✅ Source code access granted.</strong>';
      var instrEl = document.getElementById("wl-source-instructions");
      instrEl.style.display = "block";
      instrEl.textContent = res.data.setup_instructions || "";
      document.getElementById("wl-source-btn").style.display = "none";
    }} else {{
      msg.textContent = "⚠️ " + (res.data.error || "Failed."); msg.style.color = "#DC2626";
    }}
  }})
  .catch(function() {{ msg.textContent = "⚠️ Network error."; msg.style.color = "#DC2626"; }});
}}

// Show/hide white label tab based on plan
function maybeShowWlTab(plan) {{
  if (plan === "enterprise") {{
    document.getElementById("tab-btn-whitelabel").style.display = "";
  }}
}}

function filterAppts() {{
  var q = (document.getElementById("appt-search").value || "").toLowerCase();
  if (!q) {{ renderAppts(_allAppts); return; }}
  var filtered = _allAppts.filter(function(a) {{
    return (a.patient_name || "").toLowerCase().includes(q)
        || (a.appointment_type || "").toLowerCase().includes(q)
        || (a.provider || "").toLowerCase().includes(q)
        || (a.confirmation_number || "").toLowerCase().includes(q)
        || (a.appointment_datetime || "").toLowerCase().includes(q);
  }});
  renderAppts(filtered);
}}

function copyText(elemId, btn) {{
  var el = document.getElementById(elemId);
  var text = el.innerText || el.textContent;
  navigator.clipboard.writeText(text.trim()).then(function() {{
    var orig = btn.textContent;
    btn.textContent = "✓ Copied!";
    btn.classList.add("copied");
    setTimeout(function() {{ btn.textContent = orig; btn.classList.remove("copied"); }}, 2000);
  }});
}}

function showDash() {{
  var loginEl = document.getElementById("login-screen");
  var dashEl  = document.getElementById("dash-screen");
  if (loginEl) loginEl.style.display = "none";
  if (dashEl)  dashEl.style.display  = "block";

  var patientUrl = window.location.origin + "/chat/" + SLUG;

  var puEl = document.getElementById("patient-url");
  if (puEl) puEl.textContent = patientUrl;

  var qrEl = document.getElementById("qr-img");
  if (qrEl) qrEl.src =
    "https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=" + encodeURIComponent(patientUrl);

  var ecEl = document.getElementById("embed-code");
  if (ecEl) ecEl.textContent = `<!-- Tabor Synergy — ${{NAME}} AI Chat -->
<script src="${{window.location.origin}}/widget.js?clinic=${{SLUG}}" data-clinic="${{SLUG}}" async><\\/script>`;

  var imEl = document.getElementById("invite-msg");
  if (imEl) imEl.textContent = `Hi! 👋

You can now chat with our AI front desk assistant ${{AGENT}} at ${{NAME}}.

Book appointments, check insurance, ask billing questions, and more — anytime, 24/7.

💬 Start chatting: ${{patientUrl}}

Reply STOP to opt out.`;

  if (!window._widgetLoaded) {{
    window.ARIA_CLINIC_SLUG = SLUG;
    var s = document.createElement("script");
    s.src = "/widget.js?clinic=" + SLUG;
    s.setAttribute("data-clinic", SLUG);
    document.body.appendChild(s);
    window._widgetLoaded = true;
  }}
}}

function doLogin(e) {{
  e.preventDefault();
  var btn = document.getElementById("login-btn");
  var err = document.getElementById("login-err");
  btn.disabled = true; btn.textContent = "Signing in…";
  err.classList.remove("show"); err.textContent = "";
  fetch("/api/clinic-auth/login", {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{
      email:    document.getElementById("l-email").value.trim(),
      password: document.getElementById("l-pass").value,
    }}),
  }})
  .then(function(r) {{
    return r.json().then(function(d) {{ return {{ ok: r.ok, status: r.status, data: d }}; }});
  }})
  .then(function(res) {{
    if (!res.ok) {{
      var msg = (res.data && (res.data.error || res.data.detail)) || "Login failed. Please try again.";
      err.textContent = msg; err.classList.add("show");
      return;
    }}
    localStorage.setItem(TKEY, res.data.token);
    try {{
      showDash();
    }} catch (dashErr) {{
      console.error("Dashboard init error:", dashErr);
      err.textContent = "Login succeeded but dashboard failed to load — please refresh the page.";
      err.classList.add("show");
    }}
  }})
  .catch(function(fetchErr) {{
    console.error("Login error:", fetchErr);
    err.textContent = "Connection error. Please check your internet and try again.";
    err.classList.add("show");
  }})
  .finally(function() {{ btn.disabled = false; btn.textContent = "Sign In →"; }});
}}

function doLogout() {{
  var token = localStorage.getItem(TKEY);
  if (token) {{
    fetch("/api/clinic-auth/logout", {{ method: "POST", headers: {{ "X-Clinic-Token": token }} }});
    localStorage.removeItem(TKEY);
  }}
  document.getElementById("dash-screen").style.display  = "none";
  document.getElementById("login-screen").style.display = "flex";
}}

(function() {{
  var token = localStorage.getItem(TKEY);
  if (!token) return;
  fetch("/api/clinic-auth/verify", {{ headers: {{ "X-Clinic-Token": token }} }})
    .then(function(r) {{
      if (r.ok) {{ try {{ showDash(); }} catch(e) {{ localStorage.removeItem(TKEY); }} }}
      else {{ localStorage.removeItem(TKEY); }}
    }})
    .catch(function() {{ localStorage.removeItem(TKEY); }});
}})();
</script>
</body>
</html>""")


@app.get("/chat/{clinic_slug}", response_class=HTMLResponse)
async def patient_chat_page(clinic_slug: str, db: Session = Depends(get_db)):
    """Public patient-facing chat page — no login required."""
    clinic = get_clinic(db, clinic_slug)
    if not clinic:
        return HTMLResponse("<h1>Clinic not found</h1>", status_code=404)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Chat with {clinic.agent_name} — {clinic.name}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #F0F7FF; min-height: 100vh; color: #1F2937; }}
    .topbar {{
      background: #1E40AF; color: #fff; padding: 0 20px; height: 54px;
      display: flex; align-items: center; justify-content: space-between;
    }}
    .topbar-brand {{ font-weight: 700; font-size: 15px; }}
    .topbar-sub {{ font-size: 12px; opacity: .75; }}
    .body {{
      display: flex; align-items: center; justify-content: center;
      min-height: calc(100vh - 54px); flex-direction: column;
      gap: 16px; padding: 32px 20px; text-align: center;
    }}
    .welcome-card {{
      background: #fff; border-radius: 16px; padding: 32px 28px;
      max-width: 460px; width: 100%;
      box-shadow: 0 4px 24px rgba(0,0,0,.08);
    }}
    .avatar {{ font-size: 52px; margin-bottom: 12px; }}
    .welcome-card h1 {{ font-size: 20px; font-weight: 800; color: #1E3A5F; margin-bottom: 6px; }}
    .welcome-card p {{ font-size: 14px; color: #6B7280; line-height: 1.65; margin-bottom: 20px; }}
    .feature-pills {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }}
    .pill {{
      background: #EFF6FF; border: 1px solid #BFDBFE;
      color: #1D4ED8; border-radius: 20px; padding: 4px 14px;
      font-size: 12px; font-weight: 600;
    }}
    .hint {{
      background: #D1FAE5; border: 1px solid #6EE7B7; border-radius: 10px;
      padding: 12px 20px; font-size: 13px; color: #065F46;
    }}
    .footer {{ font-size: 11px; color: #9CA3AF; margin-top: 8px; }}
    .footer a {{ color: #6B7280; }}
  </style>
</head>
<body>
<div class="topbar">
  <div>
    <div class="topbar-brand">{_specialty_icon(clinic.specialty)} {clinic.name}</div>
    <div class="topbar-sub">{clinic.specialty}</div>
  </div>
</div>
<div class="body">
  <div class="welcome-card">
    <div class="avatar">{_specialty_icon(clinic.specialty)}</div>
    <h1>Hi, I'm {clinic.agent_name}!</h1>
    <p>I'm the AI front desk assistant for <strong>{clinic.name}</strong>. I can help you book appointments, check insurance, answer billing questions, and more — 24 hours a day.</p>
    <div class="feature-pills">
      <span class="pill">📅 Book Appointments</span>
      <span class="pill">🔍 Insurance Check</span>
      <span class="pill">💳 Billing Help</span>
      <span class="pill">📋 New Patient Intake</span>
      <span class="pill">🔄 Reschedule</span>
      <span class="pill">🚨 Emergency Info</span>
    </div>
  </div>
  <div class="hint">💬 Click the chat bubble in the bottom-right corner to start talking to {clinic.agent_name}</div>
  <div class="footer">Powered by <a href="/">Tabor Synergy</a> · HIPAA-compliant AI front desk</div>
</div>
<script>
  window.ARIA_CLINIC_SLUG = "{clinic_slug}";
</script>
<script src="/widget.js?clinic={clinic_slug}" data-clinic="{clinic_slug}" async></script>
</body>
</html>""")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    import logging as _log
    _logger = _log.getLogger(__name__)
    try:
        init_db()
    except Exception:
        _logger.exception("init_db failed — continuing anyway")
    try:
        from backend.db.database import migrate_db
        migrate_db()
    except Exception:
        _logger.exception("migrate_db failed — continuing anyway")

    # Schedule background jobs (trial expiry checks, etc.)
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from backend.jobs.trial_jobs import check_trial_expiry_and_remind
        from backend.db.database import SessionLocal

        scheduler = BackgroundScheduler()

        def _trial_job_wrapper():
            """Wrapper to create session and call job."""
            db = SessionLocal()
            try:
                result = check_trial_expiry_and_remind(db)
                _logger.info(f"Trial job completed: {result}")
            except Exception as e:
                _logger.error(f"Trial job failed: {e}")
            finally:
                db.close()

        # Schedule daily at 1 AM UTC
        scheduler.add_job(
            _trial_job_wrapper,
            CronTrigger(hour=1, minute=0),
            id="trial_expiry_check",
            name="Trial Expiry Check",
            replace_existing=True
        )
        scheduler.start()
        _logger.info("Background scheduler started (trial expiry checks scheduled for 1 AM UTC daily)")
    except ImportError:
        _logger.warning("APScheduler not installed — background jobs disabled. Install with: pip install apscheduler")
    except Exception as e:
        _logger.error(f"Failed to start background scheduler: {e}")


# ── Static files ──────────────────────────────────────────────────────────────
frontend_dir = Path(__file__).parent.parent / "frontend"
admin_dir    = frontend_dir / "admin"


_admin_panel_path = settings.admin_panel_path.rstrip("/")


# ── Admin panel — explicit routes (reliable at any path) ─────────────────────

@app.get(_admin_panel_path, include_in_schema=False)
@app.get(_admin_panel_path + "/", include_in_schema=False)
async def serve_admin_html(request: Request):
    # Block scanners probing common admin paths — only allow the configured secret path
    user_agent = request.headers.get("user-agent", "")
    # Reject obvious automated scanners (no User-Agent or known scanner signatures)
    if not user_agent or any(s in user_agent.lower() for s in ("sqlmap", "nikto", "nmap", "masscan", "zgrab")):
        return HTMLResponse("", status_code=404)
    return FileResponse(str(admin_dir / "index.html"), media_type="text/html")


@app.get(_admin_panel_path + "/admin.css", include_in_schema=False)
async def serve_admin_css():
    css_path = admin_dir / "admin.css"
    if css_path.exists():
        content = css_path.read_text(encoding="utf-8")
    else:
        content = "/* admin.css not found */"
    from fastapi.responses import Response as _R
    return _R(content=content, media_type="text/css")


@app.get(_admin_panel_path + "/admin.js", include_in_schema=False)
async def serve_admin_js():
    js_path = admin_dir / "admin.js"
    if js_path.exists():
        content = js_path.read_text(encoding="utf-8")
    else:
        content = "/* admin.js not found */"
    from fastapi.responses import Response as _R
    return _R(content=content, media_type="application/javascript")


# Block the default /admin path — returns blank 404 so it looks non-existent
@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def block_admin_path():
    return HTMLResponse("", status_code=404)


# ── Dynamic branded widget.js ─────────────────────────────────────────────────
@app.get("/widget.js", include_in_schema=False)
async def serve_widget_js(clinic: str = "", db=Depends(get_db)):
    """
    Serve widget.js with optional clinic branding injected as CSS variables.
    Usage:
      <script src="/widget.js?clinic=your-slug" data-clinic="your-slug" async></script>
    Falls back to default colors when no clinic slug is provided or config not found.
    """
    from fastapi.responses import Response as FastAPIResponse
    from backend.db.crud import get_clinic, get_or_create_widget_config

    # Default branding
    primary_color = "#007ACC"
    button_color  = "#007ACC"
    font_family   = "'Segoe UI', sans-serif"
    widget_title  = "Book an Appointment"
    widget_subtitle = "Quick and easy scheduling"
    cta_button_text = "Schedule Now"
    logo_url      = ""
    show_logo     = True

    if clinic:
        clinic_obj = get_clinic(db, clinic)
        if clinic_obj:
            cfg = get_or_create_widget_config(db, clinic_obj.id)
            if cfg:
                primary_color   = cfg.primary_color   or primary_color
                button_color    = cfg.button_color    or button_color
                font_family     = cfg.font_family     or font_family
                widget_title    = cfg.widget_title    or widget_title
                widget_subtitle = cfg.widget_subtitle or widget_subtitle
                cta_button_text = cfg.cta_button_text or cta_button_text
                logo_url        = cfg.logo_url        or ""
                show_logo       = cfg.show_logo if cfg.show_logo is not None else True

    # Read base widget.js
    widget_js_path = frontend_dir / "widget.js"
    if not widget_js_path.exists():
        return FastAPIResponse("/* widget.js not found */", media_type="application/javascript")

    base_js = widget_js_path.read_text(encoding="utf-8")

    # Inject branding block at the top of the IIFE — replaces injectCSS call
    branding_injection = f"""
  // ── Injected branding (server-side, clinic={clinic!r}) ──────────────
  (function applyBranding() {{
    var style = document.createElement("style");
    style.id  = "aria-widget-branding";
    style.textContent = [
      ":root {{",
      "  --aria-primary: {primary_color};",
      "  --aria-button:  {button_color};",
      "  --aria-font:    {font_family};",
      "}}"
    ].join("\\n");
    document.head.appendChild(style);
  }})();
  window._ARIA_WIDGET_TITLE    = {repr(widget_title)};
  window._ARIA_WIDGET_SUBTITLE = {repr(widget_subtitle)};
  window._ARIA_CTA_TEXT        = {repr(cta_button_text)};
  window._ARIA_LOGO_URL        = {repr(logo_url)};
  window._ARIA_SHOW_LOGO       = {'true' if show_logo else 'false'};
  // ── End injected branding ─────────────────────────────────────────
"""
    # Insert after the opening IIFE line
    branded_js = base_js.replace(
        '(function () {\n  "use strict";\n',
        '(function () {\n  "use strict";\n' + branding_injection,
        1,
    )

    return FastAPIResponse(
        content=branded_js,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=300",  # 5-min cache; branding changes are rare
            "X-Clinic": clinic or "default",
        },
    )


if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
