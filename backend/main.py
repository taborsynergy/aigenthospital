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
  <title>{clinic.name}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #F0F7FF; display: flex; align-items: center; justify-content: center;
           min-height: 100vh; flex-direction: column; gap: 16px; color: #1F2937; }}
    h1   {{ font-size: 28px; font-weight: 800; color: #1E3A5F; }}
    p    {{ color: #6B7280; }}
    .hint {{ background:#DBEAFE; border:1px solid #BFDBFE; border-radius:8px;
             padding:10px 18px; font-size:13px; color:#1D4ED8; }}
  </style>
</head>
<body>
  <h1>🏥 {clinic.name}</h1>
  <p>{clinic.specialty} · {clinic.city_state}</p>
  <div class="hint">💬 Click the chat bubble in the bottom-right to talk to {clinic.agent_name}</div>
  <script>window.ARIA_CLINIC_SLUG = "{clinic_slug}";</script>
  <script src="/widget.js" defer></script>
</body>
</html>""")


# ── Startup: init DB + seed demo clinic ──────────────────────────────────────
@app.on_event("startup")
def on_startup():
    init_db()
    _seed_demo_clinic()


def _seed_demo_clinic():
    from backend.db.database import SessionLocal
    from backend.db.crud import get_clinic as _get, create_clinic
    db = SessionLocal()
    try:
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
    finally:
        db.close()


# ── Static files ──────────────────────────────────────────────────────────────
frontend_dir = Path(__file__).parent.parent / "frontend"
admin_dir    = frontend_dir / "admin"

if admin_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin")

if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
