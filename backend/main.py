import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db, init_db
from backend.db.crud import get_clinic
from backend.routers.chat import router as chat_router
from backend.routers.admin import router as admin_router
from backend.routers.sms import router as sms_router
from backend.routers.billing import router as billing_router
from backend.routers.signup import router as signup_router
from backend.routers.clinic_auth import router as clinic_auth_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title="Tabor Synergy — Universal Medical Front Desk Agent",
    version="2.0.0",
)

origins = ["*"] if settings.allowed_origins == "*" else settings.allowed_origins.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],  # wildcard + credentials is invalid per CORS spec
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
    .login-err {{ color: #DC2626; font-size: 13px; margin-top: 10px; min-height: 18px; }}
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
      <button class="tab-btn" onclick="switchTab('try', this)">💬 Try Aria</button>
      <button class="tab-btn" onclick="switchTab('embed', this)">🔧 Embed on Website</button>
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

    <!-- ── TAB 2: Try Aria ── -->
    <div id="tab-try" class="tab-panel">
      <div class="aria-hint">
        <strong>💬 Test Your AI Front Desk</strong>
        Try everything your patients will experience — appointment booking, insurance questions,
        billing, rescheduling, and more. The chat bubble is in the bottom-right corner.
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
  if (ecEl) ecEl.textContent =
    "<!-- Tabor Synergy — " + NAME + " AI Chat -->\n" +
    "<script>\n" +
    "  window.ARIA_CLINIC_SLUG = \\"" + SLUG + "\\";\n" +
    "<\\/script>\n" +
    "<script src=\\"" + window.location.origin + "/widget.js\\" async><\\/script>";

  var imEl = document.getElementById("invite-msg");
  if (imEl) imEl.textContent =
    "Hi! 👋\n\n" +
    "You can now chat with our AI front desk assistant " + AGENT + " at " + NAME + ".\n\n" +
    "Book appointments, check insurance, ask billing questions, and more — anytime, 24/7.\n\n" +
    "💬 Start chatting: " + patientUrl + "\n\n" +
    "Reply STOP to opt out.";

  if (!window._widgetLoaded) {{
    window.ARIA_CLINIC_SLUG = SLUG;
    var s = document.createElement("script");
    s.src = "/widget.js";
    document.body.appendChild(s);
    window._widgetLoaded = true;
  }}
}}

function doLogin(e) {{
  e.preventDefault();
  var btn = document.getElementById("login-btn");
  var err = document.getElementById("login-err");
  btn.disabled = true; btn.textContent = "Signing in…"; err.textContent = "";
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
      err.textContent = msg;
      return;
    }}
    localStorage.setItem(TKEY, res.data.token);
    try {{
      showDash();
    }} catch (dashErr) {{
      console.error("Dashboard init error:", dashErr);
      err.textContent = "Login succeeded but dashboard failed to load — please refresh the page.";
    }}
  }})
  .catch(function(fetchErr) {{
    console.error("Login error:", fetchErr);
    err.textContent = "Connection error. Please check your internet and try again.";
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
    <div class="topbar-brand">🏥 {clinic.name}</div>
    <div class="topbar-sub">{clinic.specialty}</div>
  </div>
</div>
<div class="body">
  <div class="welcome-card">
    <div class="avatar">🤖</div>
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
<script src="/widget.js" async></script>
</body>
</html>""")


# ── Startup: init DB + seed demo clinics ─────────────────────────────────────
@app.on_event("startup")
def on_startup():
    from backend.db.database import migrate_db
    init_db()
    migrate_db()
    _seed_all_demo_clinics()


def _seed_all_demo_clinics():
    from backend.db.database import SessionLocal
    from backend.db.crud import get_clinic as _get, create_clinic
    from backend.routers.clinic_auth import hash_password

    db = SessionLocal()
    try:
        # ── Original demo clinic ──────────────────────────────────────────────
        if not _get(db, "demo-clinic"):
            create_clinic(db, {
                "slug":                 "demo-clinic",
                "name":                 "Sunshine Medical Group",
                "specialty":            "Family Medicine",
                "agent_name":           "Aria",
                "city_state":           "Austin, TX",
                "timezone":             "Central Time (CT)",
                "address":              "123 Main St, Austin, TX 78701",
                "phone":                "(512) 555-0100",
                "email":                "hello@sunshinemedical.com",
                "office_hours":         "Mon–Fri 8am–5pm, Sat 9am–1pm",
                "after_hours_protocol": "For emergencies call 911.",
                "providers":            "Dr. Sarah Chen (MD), Dr. Marcus Rivera (PA)",
                "services_offered":     "Annual physicals, sick visits, chronic disease management, vaccinations, lab work",
                "insurance_accepted":   "Aetna, BCBS, Cigna, United Healthcare, Medicare, Medicaid",
                "pms_system":           "Athenahealth",
                "cancellation_policy":  "24-hour notice required to avoid a $50 fee.",
                "escalation_contact":   "Office manager — text (512) 555-0101",
                "hipaa_verify_method":  "Full name + date of birth + last 4 digits of SSN",
                "subscription_status":  "trial",
                "monthly_rate":         299.0,
            })

        # ── STARTER — Smile Dental Care ───────────────────────────────────────
        if not _get(db, "smile-dental-care"):
            create_clinic(db, {
                "slug":                 "smile-dental-care",
                "name":                 "Smile Dental Care",
                "specialty":            "Dentistry",
                "agent_name":           "Aria",
                "city_state":           "Dallas, TX",
                "timezone":             "Central Time (CT)",
                "address":              "450 Oak Avenue, Dallas, TX 75201",
                "phone":                "(214) 555-0210",
                "email":                "starter@trialhospital.com",
                "office_hours":         "Mon–Fri 8am–6pm, Sat 9am–2pm",
                "after_hours_protocol": "For dental emergencies call (214) 555-0211 or go to nearest urgent care.",
                "providers":            "Dr. Emily Watson (DDS), Dr. James Nguyen (DMD)",
                "services_offered":     "Cleanings, fillings, root canals, crowns, extractions, whitening, Invisalign, dentures, pediatric dentistry",
                "insurance_accepted":   "Delta Dental, Cigna Dental, Aetna, MetLife, Guardian, United Healthcare",
                "pms_system":           "Dentrix",
                "cancellation_policy":  "48-hour notice required to avoid a $75 fee.",
                "escalation_contact":   "Office manager — call (214) 555-0210",
                "hipaa_verify_method":  "Full name + date of birth + last 4 digits of SSN",
                "subscription_status":  "trial",
                "monthly_rate":         199.0,
                "customer_password_hash": hash_password("Starter@123"),
            })

        # ── PROFESSIONAL — City Family Clinic ─────────────────────────────────
        if not _get(db, "city-family-clinic"):
            create_clinic(db, {
                "slug":                 "city-family-clinic",
                "name":                 "City Family Clinic",
                "specialty":            "Family Medicine",
                "agent_name":           "Aria",
                "city_state":           "Houston, TX",
                "timezone":             "Central Time (CT)",
                "address":              "780 Westheimer Rd, Houston, TX 77057",
                "phone":                "(713) 555-0320",
                "email":                "pro@trialhospital.com",
                "office_hours":         "Mon–Sat 7am–7pm, Sun 9am–3pm",
                "after_hours_protocol": "After-hours nurse line: (713) 555-0321. For emergencies call 911.",
                "providers":            "Dr. Priya Sharma (MD), Dr. Kevin O'Brien (DO), NP Lisa Tran",
                "services_offered":     "Annual physicals, sick visits, chronic disease management, vaccinations, lab work, pediatric care, women's health, telehealth",
                "insurance_accepted":   "Aetna, BCBS, Cigna, United Healthcare, Humana, Medicare, Medicaid, Tricare",
                "pms_system":           "Epic",
                "cancellation_policy":  "24-hour notice required to avoid a $50 fee.",
                "escalation_contact":   "Office supervisor — text (713) 555-0322",
                "hipaa_verify_method":  "Full name + date of birth + last 4 digits of SSN",
                "subscription_status":  "trial",
                "monthly_rate":         299.0,
                "customer_password_hash": hash_password("Pro@123"),
            })

        # ── ENTERPRISE — Global Care Hospital ────────────────────────────────
        if not _get(db, "global-care-hospital"):
            create_clinic(db, {
                "slug":                 "global-care-hospital",
                "name":                 "Global Care Hospital",
                "specialty":            "Multi-Specialty Hospital",
                "agent_name":           "Aria",
                "city_state":           "New York, NY",
                "timezone":             "Eastern Time (ET)",
                "address":              "1 Hospital Plaza, New York, NY 10001",
                "phone":                "(212) 555-0400",
                "email":                "enterprise@trialhospital.com",
                "office_hours":         "24 hours / 7 days a week",
                "after_hours_protocol": "Emergency department open 24/7 at main entrance. Call 911 for life-threatening emergencies.",
                "providers":            "Dr. Michael Torres (Chief of Medicine), Dr. Aisha Patel (Cardiology), Dr. Robert Kim (Orthopedics), Dr. Sandra Lee (OB-GYN), Dr. David Park (Oncology), Dr. Rachel Goldstein (Pediatrics), 40+ Specialists",
                "services_offered":     "Emergency medicine, cardiology, orthopedics, oncology, OB-GYN, pediatrics, neurology, dermatology, ENT, ophthalmology, radiology, ICU, surgical suites, lab, pharmacy, physical therapy",
                "insurance_accepted":   "All major insurance plans accepted — Aetna, BCBS, Cigna, United Healthcare, Humana, Medicare, Medicaid, Tricare, Oscar, Molina, Anthem, and self-pay options available",
                "pms_system":           "Epic (Enterprise)",
                "cancellation_policy":  "24-hour notice required. Emergency cancellations waived.",
                "escalation_contact":   "Patient Relations — call (212) 555-0401 | Emergency: dial 911",
                "hipaa_verify_method":  "Full name + date of birth + medical record number (MRN) or last 4 SSN",
                "subscription_status":  "trial",
                "monthly_rate":         499.0,
                "customer_password_hash": hash_password("Enterprise@123"),
            })

        # ── WHITE LABEL — MedTech Solutions ──────────────────────────────────
        if not _get(db, "medtech-solutions"):
            create_clinic(db, {
                "slug":                 "medtech-solutions",
                "name":                 "MedTech Solutions",
                "specialty":            "Healthcare Technology Platform",
                "agent_name":           "Aria",
                "city_state":           "San Francisco, CA",
                "timezone":             "Pacific Time (PT)",
                "address":              "500 Tech Boulevard, San Francisco, CA 94105",
                "phone":                "(415) 555-0500",
                "email":                "whitelabel@trialhospital.com",
                "office_hours":         "Mon–Fri 8am–6pm PT | API available 24/7",
                "after_hours_protocol": "For technical emergencies contact support@medtechsolutions.com or call (415) 555-0501.",
                "providers":            "Platform supports unlimited provider configurations | Demo: Dr. Alex Morgan (Chief Medical Officer)",
                "services_offered":     "White-label AI front desk platform, custom branding, API integrations, EHR connectors, multi-location management, analytics dashboard, SMS/email automation, custom workflow builder",
                "insurance_accepted":   "Configurable per client — all major payers supported via API",
                "pms_system":           "Custom API (Supports Epic, Cerner, Athenahealth, Dentrix, eClinicalWorks)",
                "cancellation_policy":  "Per client SLA configuration. Default: 24-hour notice.",
                "escalation_contact":   "Technical Account Manager — support@medtechsolutions.com | (415) 555-0501",
                "hipaa_verify_method":  "Configurable per client. Default: Full name + date of birth + last 4 SSN",
                "subscription_status":  "trial",
                "monthly_rate":         499.0,
                "customer_password_hash": hash_password("White@123"),
            })

        # ── DEMO RECORDING CLINIC — Tabor Demo Hospital ───────────────────────
        if not _get(db, "tabor-demo"):
            create_clinic(db, {
                "slug":                 "tabor-demo",
                "name":                 "Tabor Demo Hospital",
                "specialty":            "Multi-Specialty Hospital",
                "agent_name":           "Aria",
                "city_state":           "Austin, TX",
                "timezone":             "Central Time (CT)",
                "address":              "500 Healthcare Blvd, Austin, TX 78701",
                "phone":                "(512) 555-0100",
                "email":                "demo@taborsynergy.com",
                "office_hours":         "24 hours / 7 days a week",
                "after_hours_protocol": "Emergency department open 24/7. For life-threatening emergencies call 911.",
                "providers":            "Dr. Sarah Chen (Chief of Medicine), Dr. James Rivera (Cardiology), Dr. Priya Patel (Dermatology), Dr. Michael Torres (Orthopedics), Dr. Emily Watson (OB-GYN), Dr. Robert Kim (Pediatrics)",
                "services_offered":     "Emergency medicine, cardiology, dermatology, orthopedics, OB-GYN, pediatrics, family medicine, urgent care, radiology, lab work, surgery, ICU, pharmacy",
                "insurance_accepted":   "Blue Cross Blue Shield, Aetna, Cigna, United Healthcare, Humana, Medicare, Medicaid, and most major insurance plans",
                "pms_system":           "Epic",
                "cancellation_policy":  "24-hour notice required. Emergency cancellations always waived.",
                "escalation_contact":   "Nurse station — dial 0 | Emergency: dial 911",
                "hipaa_verify_method":  "Full name + date of birth + last 4 digits of SSN",
                "subscription_status":  "trial",
                "monthly_rate":         997.0,
                "customer_password_hash": hash_password("Demo@2024"),
            })

    finally:
        db.close()


# ── Static files ──────────────────────────────────────────────────────────────
frontend_dir = Path(__file__).parent.parent / "frontend"
admin_dir    = frontend_dir / "admin"


_admin_panel_path = settings.admin_panel_path.rstrip("/")


# ── Admin panel — explicit routes (reliable at any path) ─────────────────────

@app.get(_admin_panel_path, include_in_schema=False)
@app.get(_admin_panel_path + "/", include_in_schema=False)
async def serve_admin_html():
    return FileResponse(str(admin_dir / "index.html"), media_type="text/html")


@app.get(_admin_panel_path + "/admin.css", include_in_schema=False)
async def serve_admin_css():
    return FileResponse(str(admin_dir / "admin.css"), media_type="text/css")


@app.get(_admin_panel_path + "/admin.js", include_in_schema=False)
async def serve_admin_js():
    return FileResponse(str(admin_dir / "admin.js"), media_type="application/javascript")


# Block the default /admin path — returns blank 404 so it looks non-existent
@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def block_admin_path():
    return HTMLResponse("", status_code=404)


if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
