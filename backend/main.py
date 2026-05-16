import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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
    allow_credentials=True,
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
  <title>{clinic.name} — Aria</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #F0F7FF; min-height: 100vh; color: #1F2937; }}

    /* ── Login screen ── */
    #login-screen {{
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; padding: 16px;
    }}
    .login-card {{
      background: #fff; border-radius: 16px; padding: 40px 36px;
      max-width: 400px; width: 100%;
      box-shadow: 0 8px 40px rgba(0,0,0,.12);
      text-align: center;
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

    /* ── Chat screen ── */
    #chat-screen {{ display: none; }}
    .topbar {{
      background: #1E40AF; color: #fff;
      padding: 0 20px; height: 54px;
      display: flex; align-items: center; justify-content: space-between;
    }}
    .topbar-brand {{ font-weight: 700; font-size: 15px; }}
    .topbar-sub {{ font-size: 12px; opacity: .75; }}
    .btn-logout {{
      background: rgba(255,255,255,.15); border: none; color: #fff;
      border-radius: 6px; padding: 5px 12px; font-size: 12px;
      cursor: pointer; transition: background .15s;
    }}
    .btn-logout:hover {{ background: rgba(255,255,255,.25); }}
    .chat-body {{
      display: flex; align-items: center; justify-content: center;
      min-height: calc(100vh - 54px); flex-direction: column;
      gap: 12px; padding: 24px;
    }}
    .chat-hint {{
      background: #DBEAFE; border: 1px solid #BFDBFE; border-radius: 10px;
      padding: 12px 20px; font-size: 13px; color: #1D4ED8; text-align: center;
    }}
  </style>
</head>
<body>

<!-- ── Login screen ───────────────────────────────────────── -->
<div id="login-screen">
  <div class="login-card">
    <div class="login-logo">🏥</div>
    <h1>{clinic.name}</h1>
    <p class="sub">{clinic.specialty} · Sign in to access your AI front desk</p>
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

<!-- ── Chat screen (shown after login) ───────────────────── -->
<div id="chat-screen">
  <div class="topbar">
    <div>
      <div class="topbar-brand">🏥 {clinic.name}</div>
      <div class="topbar-sub">{clinic.specialty} · Powered by Aria</div>
    </div>
    <button class="btn-logout" onclick="doLogout()">Sign Out</button>
  </div>
  <div class="chat-body">
    <div class="chat-hint">
      💬 Click the chat bubble in the bottom-right corner to talk to {clinic.agent_name}
    </div>
  </div>
</div>

<script>
var SLUG  = "{clinic_slug}";
var TKEY  = "aria_token_" + SLUG;

function showChat() {{
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("chat-screen").style.display  = "block";
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
  btn.disabled = true;
  btn.textContent = "Signing in…";
  err.textContent = "";

  fetch("/api/clinic-auth/login", {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{
      email:    document.getElementById("l-email").value.trim(),
      password: document.getElementById("l-pass").value,
    }}),
  }})
  .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
  .then(function(res) {{
    if (!res.ok) {{
      err.textContent = res.data.error || "Login failed.";
      return;
    }}
    localStorage.setItem(TKEY, res.data.token);
    showChat();
  }})
  .finally(function() {{
    btn.disabled = false;
    btn.textContent = "Sign In →";
  }});
}}

function doLogout() {{
  var token = localStorage.getItem(TKEY);
  if (token) {{
    fetch("/api/clinic-auth/logout", {{ method: "POST", headers: {{ "X-Clinic-Token": token }} }});
    localStorage.removeItem(TKEY);
  }}
  document.getElementById("chat-screen").style.display  = "none";
  document.getElementById("login-screen").style.display = "flex";
}}

// Auto-login if valid token in storage
(function() {{
  var token = localStorage.getItem(TKEY);
  if (!token) return;
  fetch("/api/clinic-auth/verify", {{ headers: {{ "X-Clinic-Token": token }} }})
    .then(function(r) {{ if (r.ok) showChat(); else localStorage.removeItem(TKEY); }})
    .catch(function() {{}});
}})();
</script>
</body>
</html>""")


# ── Startup: init DB + seed demo clinics ─────────────────────────────────────
@app.on_event("startup")
def on_startup():
    init_db()
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

    finally:
        db.close()


# ── Static files ──────────────────────────────────────────────────────────────
frontend_dir = Path(__file__).parent.parent / "frontend"
admin_dir    = frontend_dir / "admin"

if admin_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin")

if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
