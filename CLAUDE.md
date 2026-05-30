# Tabor Synergy — AI Medical Front Desk Agent

## Project Overview
Multi-tenant medical AI front desk platform. Clinics sign up, get their own AI agent (Aria) for patient chat, appointment booking, insurance verification, and billing. Three plans: Starter ($297), Professional ($597), Enterprise ($997).

## Live URL
https://aifrontdesk.taborsynergy.com

## Tech Stack
- **Backend:** Python FastAPI, SQLAlchemy, SQLite (dev) / PostgreSQL (prod)
- **AI:** Anthropic Claude API (`claude-sonnet-4-6`) via AsyncAnthropic
- **SMS:** Twilio webhook at `/sms/inbound`
- **Email:** SMTP (Gmail app password) via `backend/services/email_svc.py`
- **Payments:** PayPal.me links (manual activation flow)
- **Deployment:** Render.com (auto-deploys on push to `main`)
- **Frontend:** Vanilla JS/HTML — no build step needed

## Key Architecture Decisions
- All clinic config is stored in the `clinics` DB table — no per-clinic config files
- System prompt is built dynamically per clinic from DB: `backend/agent/prompts.py`
- Session history is in-memory (dict keyed by `clinic_id:session_id`) — not persisted
- Usage is tracked per-message in `usage_logs` table; conversations counted as distinct sessions
- Plan feature gating is enforced in `backend/plans.py` and checked at WebSocket connect time
- Emails are always sent as `BackgroundTasks` — never block the HTTP response

## Admin Panel
- URL: `/ts-mgmt` (keep secret — do not expose)
- Auth: `X-Admin-Password` header → must match `ADMIN_PASSWORD` env var
- Managed via `backend/routers/admin.py`

## Clinic Portal
- URL: `/c/{clinic_slug}`
- Auth: email + password → UUID session token stored in `clinics.session_token`
- Token passed as `X-Clinic-Token` header on all protected API calls

## Critical Rules — Do Not Break
1. `require_admin()` in `admin.py` MUST use `settings.admin_password` — NOT `os.environ.get()`
2. `mock_responses.py` returns human-readable TEXT strings — not JSON tool codes
3. Emails are sent via `background_tasks.add_task()` — never call synchronously in a request handler
4. `get_usage_this_month()` counts DISTINCT session_ids — not total log rows
5. `_access_blocked()` in `chat.py` must receive `db` param to check conversation limits
6. The upgrade modal in `main.py` calls `POST /api/{slug}/upgrade-request` — do not revert to mailto link

## Plans (backend/plans.py)
| Plan | Price | Conversations/mo | SMS | Widget | Custom Name | White Label |
|------|-------|-----------------|-----|--------|-------------|-------------|
| starter | $297 | 300 | ❌ | ❌ | ❌ | ❌ |
| professional | $597 | 1,000 | ✅ | ✅ | ✅ | ❌ |
| enterprise | $997 | Unlimited | ✅ | ✅ | ✅ | ✅ |

## Agent Tools (backend/agent/tools.py)
10 tools: `check_appointment_availability`, `book_appointment`, `reschedule_appointment`,
`cancel_appointment`, `verify_insurance`, `get_patient_balance`, `send_payment_link`,
`send_intake_form`, `add_to_waitlist`, `escalate_to_human`

## Database Tables
- `clinics` — all clinic config, auth, subscription state
- `appointments` — booked via Aria, shown in clinic portal Appointments tab
- `usage_logs` — every Claude API call logged with tokens and session_id
- `sms_conversations` — SMS session tracking per patient phone number

## Deployment Notes
- Push to `main` → Render auto-deploys (takes ~3-5 min)
- New DB columns must be added to `migrate_db()` in `backend/db/database.py`
- SQLAlchemy `create_all()` only creates new tables, not new columns on existing tables
- Model fallback: if `claude-sonnet-4-6` fails, retries with `claude-3-5-sonnet-20241022`

## Agent Coordination (Claude VSCode + Hermes VPS)
Both agents work on the same GitHub repo: https://github.com/taborsynergy/aigenthospital
- Always `git pull origin main` before starting work
- Always `git push origin main` after changes
- Check this file for current state before making changes
- Do not overwrite each other's fixes without reviewing first

## What's Done (as of 2026-05-20)
- ✅ Aria chat (WebSocket + REST)
- ✅ Appointment booking → DB persistence → clinic portal view
- ✅ Plan-based feature gating (SMS, widget, conversation limits)
- ✅ Clinic portal: Share, Appointments, Plan & Billing, Try Aria, Embed tabs
- ✅ Upgrade modal (Plan tab → PayPal → admin email notification)
- ✅ Specialty-appropriate icons (30+ specialties)
- ✅ Admin panel: clinic CRUD, usage stats, plan labels, monthly session bars
- ✅ Signup: instant response (email sent in background)
- ✅ SMS via Twilio (Professional/Enterprise plans only)

## Known Intentional Design Choices
- No Stripe integration active — PayPal.me + manual activation is intentional
- Mock PMS/insurance/payments — real EHR integration is a future milestone
- Inline HTML in `main.py` for clinic portal — known tech debt, not priority to change now
