# SOFTWARE DESIGN DOCUMENT
## Tabor Synergy — AI Medical Front Desk Platform

---

| Field | Value |
|-------|-------|
| **Document Title** | Software Design Document (SDD) |
| **Product** | Tabor Synergy — AI Medical Front Desk |
| **Version** | 2.0.0 |
| **Date** | June 5, 2026 |
| **Status** | Production |
| **Live URL** | https://aifrontdesk.taborsynergy.com |
| **API URL** | https://taborsynergy-agent.onrender.com |
| **Repository** | https://github.com/taborsynergy/aigenthospital |
| **Authors** | Reverse-engineered from source code |

---

## TABLE OF CONTENTS

1. [Executive Summary](#1-executive-summary)
2. [Product Requirements Document (PRD)](#2-product-requirements-document-prd)
3. [System Architecture](#3-system-architecture)
4. [Module Breakdown](#4-module-breakdown)
5. [API Specification](#5-api-specification)
6. [Database Design Document](#6-database-design-document)
7. [Security Design Document](#7-security-design-document)
8. [Subscription & Billing Design](#8-subscription--billing-design)
9. [UI Screen Inventory](#9-ui-screen-inventory)
10. [Infrastructure & Deployment](#10-infrastructure--deployment)
11. [Operations Runbook](#11-operations-runbook)
12. [QA Test Strategy](#12-qa-test-strategy)
13. [Technical Debt Report](#13-technical-debt-report)
14. [Admin Guide](#14-admin-guide)
15. [Patient & Clinic User Guide](#15-patient--clinic-user-guide)

---

# 1. EXECUTIVE SUMMARY

## 1.1 Product Overview

**Tabor Synergy** is a multi-tenant SaaS platform that provides medical clinics with an AI-powered virtual front desk agent named **"Aria."** The platform handles patient inquiries, appointment booking, insurance verification, billing assistance, and human escalation — 24 hours a day, 7 days a week, without requiring staff involvement.

## 1.2 Business Model

| Item | Detail |
|------|--------|
| **Revenue Model** | Monthly recurring subscription per clinic |
| **Price Range** | $297 – $997/month |
| **Trial Period** | 14-day free trial |
| **Activation** | Manual (PayPal confirmation) + automated (Stripe webhooks) |
| **Target Market** | Medical clinics across all specialties (30+ supported) |

## 1.3 Technology Summary

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + FastAPI 0.115+ |
| AI Engine | Anthropic Claude API (claude-sonnet-4-6) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Frontend | Vanilla JS + HTML (no build step) |
| Hosting | Render.com |
| CDN/Proxy | Cloudflare |
| Monitoring | Sentry SDK |
| SMS | Twilio |
| Email | SMTP (Gmail App Password) |
| Payments | PayPal.me (manual) + Stripe (configured) |

## 1.4 Key Metrics (from landing page)

- **500+** clinics served
- **2M+** patient conversations handled
- **30+** medical specialties supported
- **24/7** availability

---

# 2. PRODUCT REQUIREMENTS DOCUMENT (PRD)

## 2.1 Problem Statement

Medical front desks are overwhelmed with repetitive patient inquiries. Clinics spend $3,000–$8,000/month on reception staff to handle routine tasks such as appointment scheduling, insurance queries, and billing questions. After-hours calls go unanswered, leading to lost patients and poor satisfaction scores.

**Tabor Synergy replaces this with a conversational AI agent available 24/7 at a fraction of the cost.**

## 2.2 User Roles

### Role 1 — Patient / End User

| Attribute | Detail |
|-----------|--------|
| **Who** | Any patient of a clinic using the platform |
| **Access** | Public — no registration required |
| **Entry points** | Clinic chat link, website embed widget, SMS text message |
| **Capabilities** | Chat with Aria, book/reschedule/cancel appointments, check insurance, get billing info, receive intake forms |

### Role 2 — Clinic Owner / Manager

| Attribute | Detail |
|-----------|--------|
| **Who** | Doctor, practice manager, or front desk supervisor |
| **Access** | Email + password authentication |
| **Entry points** | `/c/{clinic_slug}` |
| **Capabilities** | View appointments, check usage, manage plan, request upgrade, share patient link, embed widget |

### Role 3 — Platform Admin (Tabor Synergy Staff)

| Attribute | Detail |
|-----------|--------|
| **Who** | Tabor Synergy internal team |
| **Access** | Admin password header |
| **Entry points** | `/{ADMIN_PANEL_PATH}` (default: `/ts-mgmt`) |
| **Capabilities** | Full CRUD on all clinics, activate subscriptions, view revenue stats, reset passwords, send SMS |

## 2.3 User Permissions Matrix

| Permission | Patient | Clinic User | Platform Admin |
|-----------|:-------:|:-----------:|:--------------:|
| Chat with Aria | ✅ | ✅ | ✅ |
| View own appointments | ❌ | ✅ | ✅ |
| View usage statistics | ❌ | ✅ (own only) | ✅ (all clinics) |
| View / change plan | ❌ | ✅ (own only) | ✅ (all clinics) |
| Request plan upgrade | ❌ | ✅ | ✅ |
| Create clinic | ❌ | ❌ | ✅ |
| Update clinic config | ❌ | ❌ | ✅ |
| Activate subscription | ❌ | ❌ | ✅ |
| Send SMS to patient | ❌ | ❌ | ✅ |
| Reset clinic password | ❌ | ❌ | ✅ |
| View platform revenue | ❌ | ❌ | ✅ |
| Write internal notes | ❌ | ❌ | ✅ |

## 2.4 Complete Feature Matrix

| ID | Feature | Module | Roles | Description |
|----|---------|--------|-------|-------------|
| F-01 | Self-service signup | `signup.py` | Anyone | 14-day trial registration via web form |
| F-02 | AI chat — WebSocket | `chat.py`, `aria.py` | Patient | Real-time streaming chat with token-by-token delivery |
| F-03 | AI chat — REST | `chat.py` | Patient | HTTP fallback for non-WebSocket clients |
| F-04 | Appointment booking | `tools.py`, `pms.py` | Patient via Aria | Aria books appointment, persists to DB with confirmation # |
| F-05 | Appointment rescheduling | `tools.py`, `pms.py` | Patient via Aria | Aria reschedules with identity verification |
| F-06 | Appointment cancellation | `tools.py`, `pms.py` | Patient via Aria | Aria cancels with policy reminder |
| F-07 | Insurance verification | `tools.py`, `insurance.py` | Patient via Aria | Coverage check with copay/deductible estimates |
| F-08 | Billing balance inquiry | `tools.py`, `pms.py` | Patient via Aria | HIPAA-verified balance lookup |
| F-09 | Payment link sending | `tools.py`, `payments.py` | Patient via Aria | Secure payment link via SMS or email |
| F-10 | Intake form sending | `tools.py`, `payments.py` | Patient via Aria | Digital new patient form delivery |
| F-11 | Waitlist management | `tools.py`, `pms.py` | Patient via Aria | Captures next-available slot requests |
| F-12 | Human escalation | `tools.py`, `email_svc.py` | Patient via Aria | Live staff alert via email with conversation summary |
| F-13 | SMS inbound channel | `sms.py`, `twilio_svc.py` | Patient | Text message interface (Professional/Enterprise plans) |
| F-14 | Website embed widget | `widget.js` | Patient | Floating chat bubble for any website |
| F-15 | Clinic portal dashboard | `main.py` | Clinic User | Multi-tab management interface |
| F-16 | Plan & billing view | `chat.py` | Clinic User | Usage visualization + plan comparison |
| F-17 | Plan upgrade request | `chat.py` | Clinic User | PayPal-linked upgrade initiation with admin notification |
| F-18 | Admin clinic CRUD | `admin.py` | Platform Admin | Create, read, update, delete all clinics |
| F-19 | Admin stats dashboard | `admin.py` | Platform Admin | MRR, pipeline, usage across all clinics |
| F-20 | Subscription activation | `admin.py` | Platform Admin | Manual 30-day subscription activation |
| F-21 | White Label quote | `signup.py` | Prospective | Enterprise inquiry form submission |
| F-22 | Plan feature gating | `plans.py` | System | Enforces SMS/widget/custom-name by plan |
| F-23 | Monthly conversation limits | `chat.py`, `crud.py` | System | Blocks chat when monthly cap exceeded |
| F-24 | Keep-alive cron | `render.yaml` | System | Pings `/api/health` every 10 min to prevent sleep |
| F-25 | Appointment persistence | `pms.py`, `crud.py` | System | Stores all Aria-booked appointments in `appointments` table |
| F-26 | Multi-specialty prompting | `prompts.py` | System | Adapts Aria's behavior to 30+ medical specialties |
| F-27 | Model fallback | `aria.py` | System | Falls back from `claude-sonnet-4-6` to `claude-3-5-sonnet-20241022` on API errors |
| F-28 | Audit logging | `crud.py`, `models.py` | System | Immutable trail of all admin/clinic mutations |

---

# 3. SYSTEM ARCHITECTURE

## 3.1 Context Diagram

```
╔══════════════════════════════════════════════════════════════════════╗
║                        EXTERNAL ACTORS                              ║
║                                                                      ║
║  [Patient Browser]  [Clinic Browser]  [Admin Browser]  [Twilio SMS] ║
╚══════════════════════╤══════════════════════════════════════════════╝
                       │ HTTPS / WSS / TwiML
╔══════════════════════▼══════════════════════════════════════════════╗
║                    CLOUDFLARE (CDN + DDoS + SSL)                   ║
╚══════════════════════╤══════════════════════════════════════════════╝
                       │
╔══════════════════════▼══════════════════════════════════════════════╗
║                   RENDER.COM WEB SERVICE                           ║
║                                                                     ║
║  ┌─────────────────────────────────────────────────────────────┐   ║
║  │              FastAPI Application (Python 3.12)              │   ║
║  │                                                             │   ║
║  │  ┌──────────────┐  ┌────────────────┐  ┌───────────────┐  │   ║
║  │  │  Chat Router  │  │  Admin Router  │  │  Auth Router  │  │   ║
║  │  │  REST + WS   │  │  /admin/api/*  │  │/clinic-auth/* │  │   ║
║  │  └──────┬───────┘  └───────┬────────┘  └───────┬───────┘  │   ║
║  │         │                  │                    │          │   ║
║  │  ┌──────▼──────────────────▼────────────────────▼───────┐  │   ║
║  │  │               Aria Agent Engine                      │  │   ║
║  │  │     aria.py  ·  tools.py  ·  prompts.py              │  │   ║
║  │  └──────────────────────┬────────────────────────────────┘  │   ║
║  │                         │                                    │   ║
║  │  ┌──────────────────────▼────────────────────────────────┐  │   ║
║  │  │           SQLAlchemy ORM (pool_size=20)               │  │   ║
║  │  └──────────────────────┬────────────────────────────────┘  │   ║
║  │                         │                                    │   ║
║  │  ┌──────────────────────▼────────────────────────────────┐  │   ║
║  │  │     PostgreSQL (prod) / SQLite + WAL (dev)            │  │   ║
║  │  │  clinics · appointments · usage_logs ·                │  │   ║
║  │  │  sms_conversations · chat_sessions · audit_logs       │  │   ║
║  │  └───────────────────────────────────────────────────────┘  │   ║
║  └─────────────────────────────────────────────────────────────┘   ║
║                                                                     ║
╚══════════════════════════════════════════════════════════════════════╝

EXTERNAL SERVICES
  ├── Anthropic Claude API ────── AI response generation
  ├── Twilio ─────────────────── SMS inbound/outbound
  ├── SMTP / Gmail ─────────────── Email notifications
  ├── PayPal.me ─────────────── Payment links (manual)
  ├── Stripe ──────────────────── Webhook automation (configured)
  ├── Sentry ──────────────────── Error tracking
  └── QR Server API ──────────── QR code generation for clinic portal
```

## 3.2 Component Diagram

```
backend/
├── main.py                ← FastAPI app, middleware, static routing
├── config.py              ← Pydantic Settings (env var loading)
├── plans.py               ← Plan definitions + feature gate helpers
├── limiter.py             ← slowapi rate limiter instance
│
├── routers/
│   ├── chat.py            ← POST /api/{slug}/chat, WS /ws/{slug}/{id}
│   ├── admin.py           ← /admin/api/* (CRUD + stats + billing)
│   ├── signup.py          ← POST /api/signup, POST /api/quote
│   ├── clinic_auth.py     ← POST/GET /api/clinic-auth/*
│   ├── billing.py         ← POST /billing/webhook (Stripe)
│   └── sms.py             ← POST /sms/inbound (Twilio)
│
├── agent/
│   ├── aria.py            ← Conversation engine (LRU + DB sessions)
│   ├── tools.py           ← 10 Claude tool definitions + dispatch
│   ├── prompts.py         ← System prompt builder (sanitized)
│   └── mock_responses.py  ← Keyword-based responses for MOCK_MODE=1
│
├── db/
│   ├── models.py          ← SQLAlchemy models (6 tables)
│   ├── crud.py            ← All DB operations
│   └── database.py        ← Engine, session, init_db, migrate_db
│
├── mocks/
│   ├── pms.py             ← Mock PMS (Athenahealth substitute)
│   ├── insurance.py       ← Mock insurance verification
│   └── payments.py        ← Mock payment link + intake form
│
├── models/
│   └── schemas.py         ← Pydantic request/response models
│
└── services/
    ├── email_svc.py       ← SMTP email (trial, upgrade, quote, escalation)
    ├── stripe_svc.py      ← Stripe checkout + webhook handler
    └── twilio_svc.py      ← SMS send + TwiML builder

frontend/
├── index.html             ← Landing page (1,379 lines, Vanilla JS)
├── widget.js              ← Chat widget (366 lines, WebSocket client)
├── widget.css             ← Widget styles (279 lines)
└── admin/
    ├── index.html         ← Admin panel SPA shell
    ├── admin.js           ← Admin dashboard logic
    └── admin.css          ← Admin styles
```

## 3.3 Request Flow — Patient WebSocket Chat

```
Step  Actor              Action
────  ─────────────────  ──────────────────────────────────────────────
 1    Browser            GET /chat/{slug} → HTML page loaded
 2    widget.js          GET /api/{slug}/config → clinic name, agent name
 3    widget.js          WebSocket CONNECT → wss://.../ws/{slug}/{session_id}
 4    Server             Validate clinic exists + check subscription status
 5    Server → Client    {"type":"message","content":"Hi! I'm Aria..."}
 6    Patient            Types message → WebSocket send
 7    Server → Client    {"type":"typing","active":true}
 8    aria.chat_stream() Load history from LRU cache or chat_sessions DB
 9    aria.chat_stream() Build sanitized system prompt for clinic
10    aria.chat_stream() Call Anthropic Claude API (streaming mode)
11    Server → Client    {"type":"chunk","text":"I'd be "} (per token)
12    [if tool_use]       dispatch_tool() → pms/insurance/payments mock
13    [if tool_use]       Tool result fed back to Claude → continue stream
14    Server → Client    {"type":"typing","active":false}
15    Server → Client    {"type":"message","content":"...","escalated":false}
16    aria.py            Save history to LRU cache + chat_sessions table
17    aria.py            Log usage tokens to usage_logs table
```

## 3.4 Request Flow — Clinic Signup to Activation

```
Step  Actor              Action
────  ─────────────────  ──────────────────────────────────────────────
 1    Clinic Owner       POST /api/signup {name, email, password, specialty, plan}
 2    signup.py          Validate: EmailStr, plan in PLAN_RATES, password ≥6 chars
 3    signup.py          Generate slug: kebab-case + 5-char hex suffix
 4    signup.py          Hash password: PBKDF2-HMAC-SHA256, 260,000 iterations
 5    crud.py            INSERT INTO clinics: status=trial, trial_ends_at=+14 days
 6    Background task    send_trial_signup_email() → admin@tabor.taborsynergy.com
 7    Clinic Owner       Receives email with chat URL
 8    Clinic Owner       GET /c/{slug} → Login form
 9    clinic_auth.py     Verify PBKDF2 hash → Return session token (30-day TTL)
10    Clinic Owner       Uses portal: views appointments, shares link with patients
11    [14 days later]    trial_ends_at passed → chat blocked for patients
12    Clinic Owner       POST /api/{slug}/upgrade-request → selects plan
13    Background task    send_upgrade_request_email() with PayPal link
14    Platform Admin     Reviews email → confirms PayPal payment received
15    Platform Admin     POST /admin/api/clinics/{slug}/activate
16    crud.py            UPDATE clinics: status=active, ends_at=now+30 days
```

## 3.5 Sequence Diagram — Human Escalation

```
Patient     Aria Agent    dispatch_tool()   email_svc.py    Staff
  │              │               │               │            │
  │──"I want to ─►              │               │            │
  │  speak to a  │              │               │            │
  │  human"      │              │               │            │
  │              │──tool_use: ──►               │            │
  │              │  escalate_to │               │            │
  │              │  _human      │               │            │
  │              │  {reason,    │               │            │
  │              │  urgency,    │               │            │
  │              │  summary}    │               │            │
  │              │              │──_notify_────►             │
  │              │              │  escalation() │            │
  │              │              │               │──Email:────►
  │              │              │               │  URGENT    │
  │              │              │               │  Escalation│
  │              │              │               │  + summary │
  │              │◄─{staff_────-│               │            │
  │              │  alerted:    │               │            │
  │              │  true}       │               │            │
  │◄─"Connecting │              │               │            │
  │  you now..." │              │               │            │
```

---

# 4. MODULE BREAKDOWN

## 4.1 Agent Engine — `backend/agent/`

### Purpose
Core AI conversation engine. Manages all interactions between patients and the Anthropic Claude API.

### Components

#### `aria.py` — Conversation Orchestrator

| Aspect | Detail |
|--------|--------|
| **Session store** | LRU cache (max 500, 30-min TTL) + `ChatSession` DB table |
| **Persistence** | Every exchange written to `chat_sessions` via `save_chat_history()` |
| **Model** | `claude-sonnet-4-6` with fallback to `claude-3-5-sonnet-20241022` |
| **Interfaces** | `chat()` — non-streaming; `chat_stream()` — async generator yielding `("chunk", text)` tokens |
| **Prompt caching** | System prompts cached in `_prompts` dict, invalidated on clinic config change |

**Session lifecycle:**
```
load_history(clinic_id, session_id)
  → check _LRUCache → miss → query chat_sessions table
  → append user message
  → call Anthropic (streaming or non-streaming)
  → append assistant response
  → save_history() → write to LRU + DB
```

#### `tools.py` — Tool Definitions & Dispatch

10 Claude tool definitions with JSON Schema input validation. `dispatch_tool()` routes by tool name to mock services. All tool implementations are **mock** — real EHR/PMS integrations are a future milestone.

| Tool | Required Inputs | Returns |
|------|----------------|---------|
| `check_appointment_availability` | appointment_type | 5 available slots |
| `book_appointment` | patient_name, appointment_type, datetime | Confirmation # (persisted to DB) |
| `reschedule_appointment` | patient_name, new_datetime | Rescheduled confirmation |
| `cancel_appointment` | patient_name, appointment_date | Cancellation confirmation |
| `verify_insurance` | insurance_company, member_id | Coverage %, copay, deductible |
| `get_patient_balance` | patient_name, patient_dob | Dollar balance |
| `send_payment_link` | patient_name, amount, channel, contact | Link sent confirmation |
| `send_intake_form` | patient_name, channel | Form link confirmation |
| `add_to_waitlist` | patient_name, patient_phone, appointment_type | Waitlist position |
| `escalate_to_human` | reason, urgency | Email sent, staff_alerted: true |

#### `prompts.py` — System Prompt Builder

Builds a 3,000+ character system prompt from clinic config. All 13 clinic fields are sanitized against prompt injection patterns before interpolation.

**Sanitization regex:**
```
ignore .* (instructions|prompts|rules) |
system: | </?system> | disregard | override | jailbreak |
you are now | act as | new persona | forget everything
```

**Prompt sections:** Identity Rules, Practice Information, 11 Capabilities (scheduling, rescheduling, cancellation, insurance, billing, intake, follow-up, reminders, FAQs, multi-specialty, admin analytics), Security rules, Escalation rules, Hard limits, Conversation style.

### Dependencies
`anthropic`, `httpx`, `backend.db.crud`, `backend.db.models`

---

## 4.2 Chat Router — `backend/routers/chat.py`

### Purpose
HTTP and WebSocket entry points for patient chat. Enforces subscription and conversation limits.

### Access Control Logic (`_access_blocked`)

```
1. subscription_status == "trial"
   → trial_ends_at passed? → BLOCK "Trial has ended"

2. subscription_status == "active"
   → subscription_ends_at passed? → BLOCK "Subscription expired"

3. subscription_status in ("past_due", "cancelled")
   → BLOCK "{status}. Contact us to restore access"

4. Monthly conversation limit:
   → get_usage_this_month(db, clinic_id) >= limit? → BLOCK "Limit reached"
```

### Key Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `WS /ws/{slug}/{session_id}` | None | Streaming WebSocket chat |
| `POST /api/{slug}/chat` | None | REST chat fallback |
| `GET /api/{slug}/config` | None | Widget initialization data |
| `GET /api/{slug}/appointments` | Clinic token | All appointments for this clinic |
| `GET /api/{slug}/plan` | Clinic token | Plan details + usage stats |
| `POST /api/{slug}/upgrade-request` | Clinic token | Initiate PayPal upgrade |
| `GET /api/health` | None | Service health check |
| `GET /api/health/ai` | None | Claude API connectivity test |

---

## 4.3 Admin Module — `backend/routers/admin.py`

### Purpose
Platform management API for Tabor Synergy internal staff.

### Authentication
Every endpoint uses `Depends(require_admin)`:
```python
def require_admin(x_admin_password: Optional[str] = Header(None)):
    if x_admin_password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid admin password")
```

### Clinic CRUD Schema

**Create (`ClinicIn`):** slug, name, specialty, agent_name, city_state, timezone, address, phone, email, website, office_hours, after_hours_protocol, providers, services_offered, insurance_accepted, pms_system, cancellation_policy, escalation_contact, hipaa_verify_method, twilio_phone, monthly_rate, initial_password

**Update (`ClinicPatch`):** Same fields but all Optional; `subscription_status` additionally accepts `trial|active|past_due|cancelled`

---

## 4.4 Authentication Module — `backend/routers/clinic_auth.py`

### Password Hashing

```python
# Hash
salt = base64.b64encode(os.urandom(16)).decode()
h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
stored = f"{salt}${base64.b64encode(h).decode()}"

# Verify
salt, hashed = stored.split("$", 1)
h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
return base64.b64encode(h).decode() == hashed
```

### Session Token Lifecycle

```
Login → uuid4().hex token → stored in clinics.session_token
      → clinics.token_expires_at = utcnow + 30 days
      → returned to client

Verify → get_clinic_by_token(token)
       → check token_expires_at > utcnow
       → if expired: clear token, return None → 401

Logout → set session_token = "", token_expires_at = None
```

### Rate Limiting & Lockout

```
Rate limit:  5 requests / hour / IP (via slowapi)
Lockout:     10 consecutive failures → locked_until = utcnow + 30 minutes
Same error:  "Invalid credentials." for both not-found + wrong-password
             (prevents user enumeration)
```

---

## 4.5 Signup Module — `backend/routers/signup.py`

### Validation Chain

```
1. practice_name   → non-empty string
2. contact_email   → pydantic.EmailStr (RFC 5322)
3. password        → len ≥ 6 characters
4. specialty       → non-empty string
5. plan            → must be in PLAN_RATES: {starter, professional, enterprise}
```

### Slug Generation Algorithm

```python
base   = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")[:30]
suffix = uuid.uuid4().hex[:5]
slug   = f"{base}-{suffix}"
# Loop until unique (DB check)
```

### Trial Setup

```python
{
    "subscription_status":    "trial",
    "plan":                   plan_key,        # validated, lowercase
    "monthly_rate":           PLAN_RATES[plan_key],
    "trial_ends_at":          utcnow + 14 days,
    "customer_password_hash": hash_password(body.password),
}
```

---

## 4.6 Plans Module — `backend/plans.py`

**Single source of truth** for all plan definitions. Import from here everywhere — never hardcode plan data.

```python
PLANS = {
    "starter": {
        "name": "Starter", "price": 297,
        "conversations_limit": 300,
        "sms": False, "widget_embed": False,
        "custom_agent_name": False, "white_label": False,
        "max_locations": 1, "support": "Email support"
    },
    "professional": {
        "name": "Professional", "price": 597,
        "conversations_limit": 1000,
        "sms": True, "widget_embed": True,
        "custom_agent_name": True, "white_label": False,
        "max_locations": 3, "support": "Priority email support"
    },
    "enterprise": {
        "name": "Enterprise", "price": 997,
        "conversations_limit": None,    # unlimited
        "sms": True, "widget_embed": True,
        "custom_agent_name": True, "white_label": True,
        "max_locations": None,          # unlimited
        "support": "Dedicated account manager + 24/7 priority"
    }
}
```

**Feature gate functions:**
- `can_use_sms(clinic)` — SMS channel access
- `can_embed_widget(clinic)` — Website embed widget
- `can_customize_agent_name(clinic)` — Custom AI name
- `is_white_label(clinic)` — White-label branding
- `monthly_conversation_limit(clinic)` — Returns int or None

---

# 5. API SPECIFICATION

## 5.1 Base Information

| Field | Value |
|-------|-------|
| **Base URL** | `https://taborsynergy-agent.onrender.com` |
| **Protocol** | HTTPS + WSS |
| **Format** | JSON (request + response) |
| **Auth — Clinic** | `X-Clinic-Token: <uuid4_hex>` header |
| **Auth — Admin** | `X-Admin-Password: <password>` header |
| **Rate limiting** | 5 login attempts/hour/IP |

---

## 5.2 Public Endpoints

---

### POST `/api/signup`

Register a new clinic for a 14-day free trial.

**Request Body:**

```json
{
  "practice_name": "Sunshine Dermatology",
  "contact_email": "dr.smith@sunshine.com",
  "password": "securepass123",
  "specialty": "Dermatology",
  "phone": "5551234567",
  "plan": "starter"
}
```

**Field Validation:**

| Field | Rules |
|-------|-------|
| practice_name | Non-empty string |
| contact_email | Valid RFC 5322 email (Pydantic EmailStr) |
| password | Minimum 6 characters |
| specialty | Non-empty string |
| plan | One of: `starter`, `professional`, `enterprise` |

**Response 200 OK:**

```json
{
  "slug": "sunshine-dermatology-a1b2c",
  "chat_url": "https://aifrontdesk.taborsynergy.com/c/sunshine-dermatology-a1b2c",
  "plan": "starter",
  "monthly_rate": 297.0,
  "trial_ends_at": "June 19, 2026"
}
```

**Error Responses:**

| Code | Body | Cause |
|------|------|-------|
| 400 | `{"error": "Practice name is required."}` | Empty practice_name |
| 400 | `{"error": "Password must be at least 6 characters."}` | Short password |
| 400 | `{"error": "Invalid plan 'X'. Valid plans: starter, professional, enterprise."}` | Unknown plan |
| 422 | Pydantic detail array | Invalid email format |

---

### POST `/api/clinic-auth/login`

Authenticate a clinic user. Returns session token.

**Request Body:**

```json
{ "email": "dr.smith@sunshine.com", "password": "securepass123" }
```
*OR*
```json
{ "slug": "sunshine-dermatology-a1b2c", "password": "securepass123" }
```

**Response 200 OK:**

```json
{
  "token": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "slug": "sunshine-dermatology-a1b2c",
  "name": "Sunshine Dermatology"
}
```

**Error Responses:**

| Code | Body | Cause |
|------|------|-------|
| 400 | `{"error": "Provide email or clinic ID to log in."}` | Neither email nor slug |
| 401 | `{"error": "Invalid credentials."}` | Not found or wrong password |
| 429 | `{"error": "Account temporarily locked..."}` | 10+ failures or rate limit |

---

### GET `/api/clinic-auth/verify`

Validate an existing session token.

**Headers:** `X-Clinic-Token: <token>`

**Response 200 OK:**

```json
{
  "slug": "sunshine-dermatology-a1b2c",
  "name": "Sunshine Dermatology",
  "specialty": "Dermatology",
  "agent_name": "Aria",
  "status": "trial"
}
```

**Response 401:** `{"error": "Invalid or expired session."}`

---

### POST `/api/clinic-auth/logout`

Invalidate session token.

**Headers:** `X-Clinic-Token: <token>`

**Response 200 OK:** `{"ok": true}`

---

### GET `/api/{clinic_slug}/config`

Public configuration for widget initialization.

**Response 200 OK:**

```json
{
  "agent_name": "Aria",
  "clinic_name": "Sunshine Dermatology",
  "specialty": "Dermatology",
  "phone": "5551234567",
  "white_label": false
}
```

---

### POST `/api/{clinic_slug}/chat`

REST chat endpoint (non-WebSocket fallback).

**Request Body:**

```json
{
  "message": "I need to book an appointment for next Tuesday",
  "session_id": "optional-uuid-string"
}
```

**Response 200 OK:**

```json
{
  "content": "I'd be happy to help you schedule an appointment...",
  "session_id": "generated-or-provided-uuid",
  "escalated": false
}
```

**Error Responses:**

| Code | Body | Cause |
|------|------|-------|
| 400 | `{"error": "Message cannot be empty."}` | Empty or whitespace-only message |
| 403 | `{"error": "Trial has ended..."}` | Subscription blocked |
| 404 | `{"error": "Clinic not found."}` | Unknown slug |
| 500 | `{"error": "Internal error. Please try again."}` | Agent failure |

---

### WS `/ws/{clinic_slug}/{session_id}`

Streaming WebSocket chat. Delivers tokens in real time.

**Connection:** `wss://taborsynergy-agent.onrender.com/ws/{slug}/{session_id}`

**Client → Server (JSON):**
```json
{ "message": "Book me an appointment for Tuesday morning" }
```
*Or plain text string*

**Server → Client event types:**

| Type | Payload | Meaning |
|------|---------|---------|
| `message` | `content`, `session_id`, `escalated` | Complete bot message |
| `typing` | `active: true/false` | Typing indicator |
| `chunk` | `text: "token..."` | Streaming text token |
| `error` | `content`, `error_type` | Agent error |

**WebSocket close codes:**

| Code | Meaning |
|------|---------|
| 4003 | Subscription blocked |
| 4004 | Clinic not found |

---

## 5.3 Clinic-Authenticated Endpoints

> All require: `X-Clinic-Token: <token>` header

---

### GET `/api/{slug}/appointments`

Returns all appointments booked by Aria.

**Response 200 OK:** Array of appointment objects:

```json
[
  {
    "id": 1,
    "confirmation_number": "TA-AB1234",
    "patient_name": "Jane Smith",
    "patient_phone": "5551234567",
    "patient_email": "jane@example.com",
    "patient_dob": "1985-03-15",
    "appointment_type": "Annual Physical",
    "appointment_datetime": "Tuesday, June 10 at 10:00 AM",
    "provider": "Dr. Sarah Chen",
    "is_new_patient": false,
    "chief_complaint": "Annual checkup",
    "status": "scheduled",
    "channel": "web",
    "booked_at": "2026-06-05 14:30 UTC"
  }
]
```

---

### GET `/api/{slug}/plan`

Returns plan details, usage, and feature flags.

**Response 200 OK:**

```json
{
  "plan_key": "starter",
  "plan_name": "Starter",
  "price": 297,
  "conversations_used": 47,
  "conversations_limit": 300,
  "features": {
    "sms": false,
    "widget_embed": false,
    "custom_agent_name": false,
    "white_label": false,
    "max_locations": 1,
    "support": "Email support"
  },
  "subscription_status": "trial",
  "trial_ends_at": "June 19, 2026",
  "subscription_ends_at": null
}
```

---

### POST `/api/{slug}/upgrade-request`

Initiates an upgrade — returns PayPal link and emails admin.

**Request Body:** `{ "plan": "professional" }`

**Business Rules:**
- New plan must be higher than current plan by price
- Valid plans: `starter`, `professional`, `enterprise`

**Response 200 OK:**

```json
{
  "ok": true,
  "paypal_url": "https://www.paypal.com/paypalme/write2dinakar/597",
  "new_plan": "professional",
  "new_price": 597
}
```

**Error Responses:**

| Code | Body | Cause |
|------|------|-------|
| 400 | `{"error": "Invalid plan."}` | Unknown plan |
| 400 | `{"error": "Select a higher plan to upgrade."}` | Downgrade attempt |
| 403 | `{"error": "Unauthorized"}` | Invalid/expired token |

---

## 5.4 Admin Endpoints

> All require: `X-Admin-Password: <password>` header

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/api/clinics` | List all active clinics |
| `POST` | `/admin/api/clinics` | Create a clinic |
| `GET` | `/admin/api/clinics/{slug}` | Get one clinic |
| `PATCH` | `/admin/api/clinics/{slug}` | Update clinic fields |
| `DELETE` | `/admin/api/clinics/{slug}` | Soft-delete clinic |
| `POST` | `/admin/api/clinics/{slug}/activate` | Activate 30-day subscription |
| `POST` | `/admin/api/clinics/{slug}/checkout` | Generate PayPal payment link |
| `PATCH` | `/admin/api/clinics/{slug}/notes` | Update internal CRM notes |
| `POST` | `/admin/api/clinics/{slug}/reset-password` | Reset clinic portal password |
| `POST` | `/admin/api/clinics/{slug}/sms` | Send SMS to patient |
| `GET` | `/admin/api/clinics/{slug}/sms` | List SMS conversations |
| `GET` | `/admin/api/clinics/{slug}/usage` | Get usage summary |
| `GET` | `/admin/api/stats` | Platform-wide stats |

### GET `/admin/api/stats` Response

```json
{
  "total_clinics": 42,
  "active_clinics": 28,
  "trial_clinics": 14,
  "mrr": 8316.0,
  "clinics": [ { ...clinic_object, "usage": {...}, "sessions_this_month": 142 } ]
}
```

---

## 5.5 Webhook Endpoints

### POST `/billing/webhook`

Stripe event handler.

**Headers:** `stripe-signature: t=...,v1=...`

**Behavior:** If `STRIPE_WEBHOOK_SECRET` is set, rejects invalid signatures with `400`. If not set, accepts all (PayPal/dev mode).

**Handled events:**

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Activate clinic subscription (30 days) |
| `customer.subscription.updated` | Update subscription status |
| `customer.subscription.deleted` | Set status to cancelled |

---

### POST `/sms/inbound`

Twilio inbound SMS handler.

**Form fields:** `From` (patient phone), `To` (clinic Twilio number), `Body` (message text)
**Headers:** `X-Twilio-Signature: <hmac>` (validated when `TWILIO_AUTH_TOKEN` set)

**Response:** TwiML XML
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>I'd be happy to help you schedule an appointment...</Message>
</Response>
```

---

# 6. DATABASE DESIGN DOCUMENT

## 6.1 Entity Relationship Diagram

```
clinics
  │ id (PK)
  │ slug (UNIQUE)
  │ ...
  │
  ├──── appointments (clinic_id FK)
  │       id, confirmation_number (UNIQUE)
  │       patient_name, patient_phone, patient_email
  │       appointment_type, appointment_datetime, status
  │
  ├──── usage_logs (clinic_id FK)
  │       id, session_id, channel
  │       input_tokens, output_tokens, created_at
  │
  ├──── sms_conversations (clinic_id FK)
  │       id, patient_phone, session_id (UNIQUE)
  │       last_message_at
  │
  └──── chat_sessions (clinic_id FK)
          id, session_id
          history (JSON TEXT)
          channel, last_active

audit_logs (standalone)
  id, actor, action, target, detail, ip_address, created_at
```

## 6.2 Table: `clinics`

**Primary key:** `id` (auto-increment)
**Unique indexes:** `slug`, `session_token`

| Column | Type | Null | Default | Description |
|--------|------|------|---------|-------------|
| id | INTEGER | NO | PK | Auto-increment |
| slug | VARCHAR | NO | — | URL-safe unique ID (`sunshine-derm-a1b2c`) |
| name | VARCHAR | NO | — | Practice name |
| specialty | VARCHAR | NO | — | Medical specialty |
| agent_name | VARCHAR | YES | `"Aria"` | AI agent display name |
| city_state | VARCHAR | YES | `""` | Location |
| timezone | VARCHAR | YES | `"Central Time (CT)"` | Clinic timezone |
| address | VARCHAR | YES | `""` | Physical address |
| phone | VARCHAR | YES | `""` | Contact phone |
| email | VARCHAR | YES | `""` | Contact email (used for login) |
| website | VARCHAR | YES | `""` | Website URL |
| office_hours | VARCHAR | YES | `"Mon–Fri 8am–5pm"` | Office hours |
| after_hours_protocol | TEXT | YES | `"For emergencies call 911."` | After-hours message |
| providers | TEXT | YES | `""` | Provider list |
| services_offered | TEXT | YES | `""` | Services list |
| insurance_accepted | VARCHAR | YES | `""` | Accepted insurances |
| pms_system | VARCHAR | YES | `"Athenahealth"` | EHR/PMS name |
| cancellation_policy | VARCHAR | YES | `"24-hour notice required."` | Policy text |
| escalation_contact | VARCHAR | YES | `""` | Human escalation contact |
| hipaa_verify_method | VARCHAR | YES | `"Full name + DOB + SSN last 4"` | Identity verification |
| twilio_phone | VARCHAR | YES | `""` | Twilio phone number |
| stripe_customer_id | VARCHAR | YES | `""` | Stripe customer ID |
| stripe_subscription_id | VARCHAR | YES | `""` | Stripe subscription ID |
| subscription_status | VARCHAR | YES | `"trial"` | `trial\|active\|past_due\|cancelled` |
| plan | VARCHAR | YES | `"professional"` | `starter\|professional\|enterprise` |
| monthly_rate | FLOAT | YES | `299.0` | Monthly billing amount ($) |
| trial_ends_at | TIMESTAMP | YES | NULL | Trial expiry |
| subscription_ends_at | TIMESTAMP | YES | NULL | Paid subscription expiry |
| customer_password_hash | VARCHAR | YES | `""` | PBKDF2: `{salt}${hash}` |
| session_token | VARCHAR | YES | `""` | Current portal session token |
| token_expires_at | TIMESTAMP | YES | NULL | Token TTL |
| failed_login_attempts | INTEGER | YES | `0` | Consecutive failures |
| locked_until | TIMESTAMP | YES | NULL | Account lockout expiry |
| activated_at | TIMESTAMP | YES | NULL | First payment date |
| admin_notes | TEXT | YES | `""` | Internal CRM notes |
| is_active | BOOLEAN | YES | `true` | Soft delete flag |
| created_at | TIMESTAMP | YES | `utcnow` | Created |
| updated_at | TIMESTAMP | YES | `utcnow` | Last updated |

---

## 6.3 Table: `appointments`

| Column | Type | Null | Description |
|--------|------|------|-------------|
| id | INTEGER | NO | PK |
| clinic_id | INTEGER | NO | FK → clinics.id |
| confirmation_number | VARCHAR | NO | UNIQUE, format: `TA-XXXXXX` |
| patient_name | VARCHAR | NO | Full name |
| patient_phone | VARCHAR | YES | Contact phone |
| patient_email | VARCHAR | YES | Contact email |
| patient_dob | VARCHAR | YES | Date of birth |
| appointment_type | VARCHAR | NO | Visit type (free text) |
| appointment_datetime | VARCHAR | NO | Human-readable datetime |
| provider | VARCHAR | YES | Provider name |
| is_new_patient | BOOLEAN | YES | New vs. established patient |
| chief_complaint | VARCHAR | YES | Reason for visit |
| status | VARCHAR | YES | `scheduled\|cancelled\|rescheduled` |
| channel | VARCHAR | YES | `web\|sms` |
| session_id | VARCHAR | YES | Source session |
| created_at | TIMESTAMP | YES | Booking timestamp |

**Indexes:** `id`, `clinic_id`, `confirmation_number` (UNIQUE), `(clinic_id, created_at)` composite

---

## 6.4 Table: `usage_logs`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | PK |
| clinic_id | INTEGER | FK → clinics.id |
| session_id | VARCHAR | Unique conversation identifier |
| channel | VARCHAR | `web\|sms` |
| input_tokens | INTEGER | Claude input tokens |
| output_tokens | INTEGER | Claude output tokens |
| created_at | TIMESTAMP | Log entry time |

**Monthly count query:**
```sql
SELECT COUNT(DISTINCT session_id)
FROM usage_logs
WHERE clinic_id = ? AND YEAR(created_at) = ? AND MONTH(created_at) = ?
```

---

## 6.5 Table: `sms_conversations`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | PK |
| clinic_id | INTEGER | FK → clinics.id |
| patient_phone | VARCHAR | Patient phone number |
| session_id | VARCHAR | UNIQUE, format: `sms_{12hex}` |
| last_message_at | TIMESTAMP | Last SMS time |
| created_at | TIMESTAMP | Conversation start |

**Behavior:** One row per patient phone per clinic. `session_id` persists across SMS messages from the same number.

---

## 6.6 Table: `chat_sessions`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | PK |
| clinic_id | INTEGER | FK → clinics.id |
| session_id | VARCHAR | Client session UUID |
| history | TEXT | JSON array: `[{"role":"user","content":"..."},...]` |
| channel | VARCHAR | `web\|sms` |
| last_active | TIMESTAMP | Updated on every message |
| created_at | TIMESTAMP | Session start |

**Unique index:** `(clinic_id, session_id)`
**TTL purge:** `purge_old_chat_sessions(db, older_than_hours=48)` — removes sessions inactive >48h

---

## 6.7 Table: `audit_logs`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | PK |
| actor | VARCHAR | `"admin"` or `"clinic:<slug>"` |
| action | VARCHAR | `"clinic.create"`, `"clinic.update"`, etc. |
| target | VARCHAR | Affected resource slug/ID |
| detail | TEXT | JSON diff or description |
| ip_address | VARCHAR | Request IP address |
| created_at | TIMESTAMP | Immutable, indexed |

---

# 7. SECURITY DESIGN DOCUMENT

## 7.1 Authentication Summary

| System | Method | Storage | Expiry |
|--------|--------|---------|--------|
| Clinic Portal | PBKDF2-HMAC-SHA256 | DB: `customer_password_hash` | N/A |
| Clinic Session | UUID4 hex token | DB: `session_token` | 30 days |
| Admin Panel | Shared secret | Env var: `ADMIN_PASSWORD` | No expiry |
| Twilio Webhook | HMAC-SHA1 signature | Env var: `TWILIO_AUTH_TOKEN` | N/A |
| Stripe Webhook | HMAC-SHA256 signature | Env var: `STRIPE_WEBHOOK_SECRET` | N/A |
| Claude API | Bearer token | Env var: `ANTHROPIC_API_KEY` | N/A |

## 7.2 Security Controls

| Control | Status | Implementation File |
|---------|:------:|---------------------|
| HTTPS enforcement | ✅ | Cloudflare + HSTS header |
| `X-Content-Type-Options: nosniff` | ✅ | `SecurityHeadersMiddleware` in `main.py` |
| `X-Frame-Options: DENY` | ✅ | `SecurityHeadersMiddleware` in `main.py` |
| `X-XSS-Protection: 1; mode=block` | ✅ | `SecurityHeadersMiddleware` in `main.py` |
| `Strict-Transport-Security` (2yr) | ✅ | `SecurityHeadersMiddleware` in `main.py` |
| `Referrer-Policy` | ✅ | `SecurityHeadersMiddleware` in `main.py` |
| `Content-Security-Policy` | ✅ | `SecurityHeadersMiddleware` in `main.py` |
| CORS restriction | ✅ | `ALLOWED_ORIGINS` env var |
| Rate limiting (login) | ✅ | slowapi `5/hour` in `clinic_auth.py` |
| Account lockout | ✅ | 10 failures → 30min lock in `crud.py` |
| SQL injection prevention | ✅ | SQLAlchemy ORM (parameterized) |
| Input validation | ✅ | Pydantic models on all endpoints |
| PHI log redaction | ✅ | `_PhiRedactFilter` in `main.py` |
| API docs hidden in production | ✅ | `docs_url=None` when `DEBUG_MODE=false` |
| Prompt injection sanitization | ✅ | Regex in `prompts.py` |
| Session token expiry (30 days) | ✅ | `token_expires_at` in `clinic_auth.py` |
| Admin scanner blocking | ✅ | User-agent check in `main.py` |
| Twilio signature validation | ✅ | `RequestValidator` in `sms.py` |
| Stripe signature validation | ✅ | `Webhook.construct_event` in `billing.py` |
| Audit logging | ✅ | `AuditLog` table via `crud.write_audit_log()` |
| Error monitoring | ✅ | Sentry SDK with `send_default_pii=False` |
| Admin password not in localStorage | ✅ | `sessionStorage` in `admin.js` |
| Enumeration prevention | ✅ | Same error for not-found + wrong password |

## 7.3 Known Security Gaps

| Gap | Severity | Risk | Effort |
|-----|:--------:|------|--------|
| No MFA for admin panel | 🔴 High | Single password = full access | 1 week |
| No CSRF tokens | 🟡 Medium | Mitigated by CORS; still exploitable | 1 day |
| PHI stored unencrypted | 🔴 High | HIPAA risk | 2 weeks |
| No HIPAA BAA signed | 🔴 Critical | Legal liability | External |
| No IP allowlist for admin | 🟡 Medium | Exposed to internet | 1 day |
| Agent tool integrations are mocks | 🟡 Medium | Patients get fake confirmations | 3–8 weeks |

---

# 8. SUBSCRIPTION & BILLING DESIGN

## 8.1 Plan Comparison Matrix

| Feature | Starter | Professional | Enterprise |
|---------|:-------:|:------------:|:----------:|
| **Price / month** | **$297** | **$597** | **$997** |
| **Conversations / month** | 300 | 1,000 | Unlimited |
| Web AI chat | ✅ | ✅ | ✅ |
| Appointment booking | ✅ | ✅ | ✅ |
| Insurance verification | ✅ | ✅ | ✅ |
| Billing assistance | ✅ | ✅ | ✅ |
| Appointments dashboard | ✅ | ✅ | ✅ |
| SMS / WhatsApp channel | ❌ | ✅ | ✅ |
| Website embed widget | ❌ | ✅ | ✅ |
| Custom agent name | ❌ | ✅ | ✅ |
| White-label branding | ❌ | ❌ | ✅ |
| Max clinic locations | 1 | 3 | Unlimited |
| Support | Email | Priority email | Dedicated + 24/7 |

## 8.2 Subscription State Machine

```
                    ┌──────────────────────────────┐
                    │         [SIGNUP]              │
                    │   status: trial               │
                    │   trial_ends_at: +14 days     │
                    └──────────────┬───────────────-┘
                                   │
              ┌────────────────────┼──────────────────────┐
              │                    │                      │
         before expiry         after expiry          admin activates
              │                    │                      │
     ┌────────▼────────┐  ┌───────▼───────────┐  ┌──────▼──────────────┐
     │  TRIAL ACTIVE   │  │  TRIAL EXPIRED    │  │   ACTIVE (paid)     │
     │  chat: ✅       │  │  chat: ❌          │  │  ends_at: +30 days  │
     └─────────────────┘  │  "Trial ended.    │  └──────┬──────────────-┘
                          │   Contact us."    │         │
                          └───────────────────┘    ┌────┴──────────────┐
                                                   │  before ends_at   │
                                             ┌─────▼──────┐   ┌────────▼──────────┐
                                             │   ACTIVE   │   │  SUBSCRIPTION     │
                                             │  chat: ✅  │   │     EXPIRED       │
                                             └────────────┘   │  chat: ❌         │
                                                              └───────────────────┘

Stripe events:
  past_due  → status: past_due  → chat: ❌ "Subscription past_due"
  cancelled → status: cancelled → chat: ❌ "Subscription cancelled"
```

## 8.3 Upgrade Flow — Current (Manual PayPal)

```
1. Clinic User   → GET /api/{slug}/plan → Views current plan
2. Clinic User   → Clicks "Upgrade Plan" button
3. Clinic Portal → Shows upgrade modal with higher plans
4. Clinic User   → Selects plan (e.g., Professional $597)
5. Clinic Portal → POST /api/{slug}/upgrade-request {"plan":"professional"}
6. Server        → Validates: new plan must be > current plan by price
7. Server        → Returns: {"paypal_url":"https://paypal.me/.../597"}
8. Background    → send_upgrade_request_email() → admin@tabor.taborsynergy.com
9. Browser       → window.open(paypal_url) — patient completes PayPal payment
10. Admin        → Receives email notification with PayPal link
11. Admin        → Confirms payment in PayPal dashboard
12. Admin        → POST /admin/api/clinics/{slug}/activate
13. Server       → subscription_status = "active", ends_at = now + 30 days
14. Admin        → PATCH /admin/api/clinics/{slug} {"plan":"professional","monthly_rate":597}
```

## 8.4 Upgrade Flow — Automated (Stripe, configured)

```
1. Admin creates Stripe checkout → POST /admin/api/clinics/{slug}/checkout
2. Server returns Stripe checkout URL
3. Patient completes payment at stripe.com
4. Stripe fires POST /billing/webhook with event: checkout.session.completed
5. Server validates stripe-signature header
6. Server extracts clinic_slug from metadata
7. Server: subscription_status = "active", ends_at = now + 30 days
8. Monthly: customer.subscription.updated → status updated
9. Cancellation: customer.subscription.deleted → status = "cancelled"
```

---

# 9. UI SCREEN INVENTORY

## Screen 1 — Landing Page (`/`)

**File:** `frontend/index.html` (1,379 lines)
**Purpose:** Marketing and conversion page

| Section | Content |
|---------|---------|
| Navigation | Logo, nav links, "Start Free Trial" CTA button |
| Hero | Headline, sub-headline, two CTA buttons (trial + quote) |
| Metrics strip | 500+ clinics, 2M+ conversations, 30+ specialties |
| Specialty tags | 30+ specialty icons (dental, derm, pediatrics, etc.) |
| Features grid | 6 capability cards (scheduling, insurance, billing, intake, reminders, escalation) |
| Pricing | 3 plan cards (Starter $297, Professional $597, Enterprise $997) + White Label $2,999 |
| Contact | Quote request form |
| Footer | Copyright, compliance badges (HIPAA, SOC 2) |

**Modals:**
- **Signup Modal:** practice_name, contact_email, password, specialty, phone, plan selector → `POST /api/signup`
- **Quote Modal:** full_name, email, company, phone, locations, pms, message → `POST /api/quote`
- **Success Modal:** Shows generated chat URL after signup

---

## Screen 2 — Patient Chat Page (`/chat/{slug}`)

**File:** Generated in `main.py:patient_chat_page()`
**Purpose:** Public-facing chat entry point

| Component | Detail |
|-----------|--------|
| Top bar | Clinic specialty icon + name + specialty |
| Welcome card | Agent emoji, "Hi, I'm {agent_name}!", feature pills |
| Feature pills | Book Appointments, Insurance Check, Billing Help, New Patient Intake, Reschedule, Emergency Info |
| Chat hint | "Click the chat bubble in the bottom-right corner" |
| Footer | "Powered by Tabor Synergy · HIPAA-compliant AI front desk" |
| Widget | `widget.js` chat bubble (bottom-right) |

**Widget behavior:**
1. Fetches clinic config from `/api/{slug}/config`
2. Connects via WebSocket to `/ws/{slug}/{session_id}`
3. Shows typing indicator, renders streaming chunks
4. Quick-reply chips for common actions
5. Auto-reconnects on disconnect with exponential backoff

---

## Screen 3 — Clinic Portal (`/c/{slug}`)

**File:** Generated in `main.py:clinic_page()`
**Purpose:** Clinic management dashboard

### Login State

| Component | Detail |
|-----------|--------|
| Login card | Clinic logo (🏥), clinic name, specialty, email + password fields |
| Error handling | Inline error messages on failed login |
| Auto-login | Token verified on page load via `/api/clinic-auth/verify` |

### Dashboard State (5 Tabs)

**Tab 1 — Share with Patients**

| Component | Detail |
|-----------|--------|
| Patient URL | Chat link with copy button |
| QR Code | Auto-generated via `api.qrserver.com` |
| How to share | Step-by-step guide (SMS, WhatsApp, email, Instagram, print QR) |

**Tab 2 — Appointments**

| Component | Detail |
|-----------|--------|
| Search bar | Filter by patient name, type, provider, confirmation #, datetime |
| Refresh button | Re-fetches from `/api/{slug}/appointments` |
| Table columns | Confirmation #, Patient (name + phone + email + DOB), Appointment type, Date/Time, Provider, Channel, Status badge, Booked at |
| Status badges | `scheduled` (green), `cancelled` (red), `rescheduled` (yellow) |
| Empty state | "No appointments yet. Share the patient link..." |

**Tab 3 — Plan & Billing**

| Component | Detail |
|-----------|--------|
| Plan summary card | Plan name, price badge, subscription status + expiry, usage bar (conversations used/limit) |
| Feature grid | 6 feature tiles (SMS, widget, custom name, white-label, locations, support) |
| Plan comparison table | Starter vs Professional vs Enterprise feature matrix |
| Upgrade button | Opens upgrade modal (hidden for Enterprise) |
| Upgrade modal | Shows only higher plans, radio selection, "Pay with PayPal →" button |

**Tab 4 — Try Aria**

| Component | Detail |
|-----------|--------|
| Open chat button | Links to `/chat/{slug}` in new tab |
| Test scenarios | 7 suggested test prompts (booking, insurance, emergency, etc.) |
| Embedded widget | Chat bubble auto-loads in this page |

**Tab 5 — Embed on Website**

| Component | Detail |
|-----------|--------|
| Embed code box | `<script>` snippet to paste before `</body>` |
| Patient invite template | Pre-written SMS/email message with chat link |
| Copy buttons | One-click copy for both snippets |

---

## Screen 4 — Admin Panel (`/{ADMIN_PANEL_PATH}`)

**File:** `frontend/admin/index.html` + `admin.js`
**Purpose:** Platform management for Tabor Synergy staff

### Login State
Password input → validates via `GET /admin/api/stats` → stores in `sessionStorage`

### Dashboard (5 Sidebar Tabs)

**Tab 1 — Sales Pipeline**

| Component | Detail |
|-----------|--------|
| Stats cards | Total clinics, Active, Trials, MRR |
| Hot leads table | Trials expiring in ≤7 days — for sales follow-up |
| Paid customers table | All active subscriptions with renewal dates |
| Expiry alert | Warning banner when clinics expire soon |

**Tab 2 — All Clinics**

| Component | Detail |
|-----------|--------|
| Full clinic table | All clinics with plan badge, status badge, created date |
| Add Clinic button | Opens create modal with all fields |
| Edit | Opens edit modal (same fields) |
| Delete | Soft-delete with confirmation |
| Activate button | `POST /admin/api/clinics/{slug}/activate` |
| Notes | Internal CRM notes field |

**Tab 3 — Usage**

| Component | Detail |
|-----------|--------|
| Usage table | Per-clinic: total messages, input tokens, output tokens |

**Tab 4 — Billing**

| Component | Detail |
|-----------|--------|
| Payment link generator | `POST /admin/api/clinics/{slug}/checkout` → opens PayPal URL |
| Subscription status | Current status per clinic |

**Tab 5 — SMS**

| Component | Detail |
|-----------|--------|
| Clinic selector | Dropdown of all clinics |
| SMS conversations | List of patient phone numbers + last message time |
| Send SMS | Free-form message sender |

---

# 10. INFRASTRUCTURE & DEPLOYMENT

## 10.1 Full Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| Language | Python | 3.12 | Backend runtime |
| Web Framework | FastAPI | ≥0.115.0 | API + WebSocket server |
| ASGI Server | Uvicorn | ≥0.32.0 | HTTP server |
| AI | Anthropic Claude | claude-sonnet-4-6 | Conversation AI |
| AI Fallback | Claude | claude-3-5-sonnet-20241022 | Model fallback |
| ORM | SQLAlchemy | ≥2.0.0 | Database abstraction |
| DB Driver | psycopg2-binary | ≥2.9.0 | PostgreSQL driver |
| Validation | Pydantic | ≥2.0.0 | Request/response models |
| Email validation | email-validator | ≥2.0.0 | EmailStr support |
| Settings | pydantic-settings | ≥2.0.0 | Env var loading |
| Rate limiting | slowapi | ≥0.1.9 | Login rate limits |
| Error monitoring | sentry-sdk | ≥1.45.0 | Error + performance tracking |
| SMS | twilio | ≥9.0.0 | SMS send/receive |
| Payments | stripe | ≥11.0.0 | Subscription automation |
| SSL (Windows) | truststore | ≥0.9.0 | Corporate CA support |
| HTTP client | httpx | ≥0.27.0 | Async HTTP + Claude |
| WebSockets | websockets | ≥13.0 | WS protocol support |
| Frontend | Vanilla JS + HTML | — | No build step required |
| CDN | Cloudflare | — | DDoS, SSL, CDN |
| Hosting | Render.com | — | Web service + cron |
| DB (prod) | PostgreSQL | — | Production database |
| DB (dev) | SQLite + WAL | — | Development database |

## 10.2 Environment Variables Reference

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `ADMIN_PASSWORD` | ✅ | — | Admin panel password |
| `ANTHROPIC_API_KEY` | ✅ | `"dummy-api-key"` | Claude API key |
| `DATABASE_URL` | ✅ | `sqlite:///./tabor_agent.db` | DB connection string |
| `BASE_URL` | ✅ | `https://aifrontdesk.taborsynergy.com` | Public URL |
| `ALLOWED_ORIGINS` | ✅ | Production domains | CORS allowlist (comma-separated) |
| `DEBUG_MODE` | ❌ | `false` | Enable /docs and /openapi.json |
| `SENTRY_DSN` | ❌ | `""` | Sentry DSN for error tracking |
| `STRIPE_SECRET_KEY` | ❌ | `""` | Stripe API secret key |
| `STRIPE_WEBHOOK_SECRET` | ❌ | `""` | Stripe webhook signature secret |
| `STRIPE_PRICE_ID` | ❌ | `""` | Stripe recurring price ID |
| `TWILIO_ACCOUNT_SID` | ❌ | `""` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | ❌ | `""` | Twilio auth token |
| `TWILIO_DEFAULT_NUMBER` | ❌ | `""` | Default Twilio phone number |
| `SMTP_HOST` | ❌ | `""` | Email server hostname |
| `SMTP_PORT` | ❌ | `587` | Email server port |
| `SMTP_USER` | ❌ | `""` | SMTP username / Gmail address |
| `SMTP_PASS` | ❌ | `""` | Gmail App Password (16-char) |
| `NOTIFY_EMAIL` | ❌ | `admin@tabor.taborsynergy.com` | Admin notification email |
| `MOCK_MODE` | ❌ | `0` | Set to `1` for demo/test mode |
| `ADMIN_PANEL_PATH` | ❌ | `/ts-mgmt` | Admin panel URL path |
| `MODEL` | ❌ | `claude-sonnet-4-6` | Claude model identifier |
| `MAX_TOKENS` | ❌ | `1024` | Max response tokens |
| `TESTING` | ❌ | `0` | Set to `1` in test suite |

## 10.3 CI/CD Pipeline

**File:** `.github/workflows/ci.yml`

```
Push to main
       │
       ▼
GitHub Actions
       │
       ├─► Job: test
       │        ├── Setup Python 3.12
       │        ├── pip install -r requirements.txt + pytest
       │        ├── ruff check backend/ (E, F, W rules)
       │        └── pytest tests/ -v --tb=short
       │
       └─► Job: deploy  (only if test passes + push to main)
                └── curl -X POST $RENDER_DEPLOY_HOOK
```

**GitHub Secrets required:**
- `RENDER_DEPLOY_HOOK` — Render deploy webhook URL

## 10.4 Render.com Service Configuration

```yaml
services:
  - type: web
    name: taborsynergy-agent
    runtime: python
    buildCommand: pip install --upgrade pip setuptools wheel && pip install --prefer-binary -r requirements.txt
    startCommand: uvicorn backend.main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 30
    healthCheckPath: /api/health

cronJobs:
  - name: keep-alive
    schedule: "*/10 * * * *"
    startCommand: "python -c \"import urllib.request; urllib.request.urlopen('https://taborsynergy-agent.onrender.com/api/health')\""
```

---

# 11. OPERATIONS RUNBOOK

## 11.1 Service Health Checks

```bash
# Basic health
curl https://taborsynergy-agent.onrender.com/api/health
# Expected: {"status":"ok","service":"Tabor Synergy Agent"}

# AI connectivity
curl https://taborsynergy-agent.onrender.com/api/health/ai
# Expected: {"status":"ok","model":"claude-sonnet-4-6","reply":"..."}
```

## 11.2 Clinic Management Commands

```bash
BASE="https://taborsynergy-agent.onrender.com"
ADMIN_PW="your-admin-password"

# List all clinics
curl -H "X-Admin-Password: $ADMIN_PW" "$BASE/admin/api/clinics"

# Create clinic
curl -X POST -H "X-Admin-Password: $ADMIN_PW" -H "Content-Type: application/json" \
  -d '{"slug":"clinic-slug","name":"Clinic Name","specialty":"General","email":"dr@clinic.com","initial_password":"temppass123"}' \
  "$BASE/admin/api/clinics"

# Activate subscription (30 days)
curl -X POST -H "X-Admin-Password: $ADMIN_PW" "$BASE/admin/api/clinics/{slug}/activate"

# Update clinic plan + rate
curl -X PATCH -H "X-Admin-Password: $ADMIN_PW" -H "Content-Type: application/json" \
  -d '{"plan":"professional","monthly_rate":597}' \
  "$BASE/admin/api/clinics/{slug}"

# Reset portal password
curl -X POST -H "X-Admin-Password: $ADMIN_PW" -H "Content-Type: application/json" \
  -d '{"new_password":"newpassword123"}' \
  "$BASE/admin/api/clinics/{slug}/reset-password"

# View usage stats
curl -H "X-Admin-Password: $ADMIN_PW" "$BASE/admin/api/clinics/{slug}/usage"

# Platform-wide stats
curl -H "X-Admin-Password: $ADMIN_PW" "$BASE/admin/api/stats"
```

## 11.3 Database Schema Migrations

To add a new column to an existing table:

1. Add column to the model in `backend/db/models.py`
2. Add entry to `migrate_db()` in `backend/db/database.py`:
```python
("table_name", "column_name", "SQL_TYPE", "DEFAULT 'value'"),
```
3. Deploy — `migrate_db()` runs automatically at startup
4. Verify in Sentry / logs: `migrate_db: added table_name.column_name`

## 11.4 Common Issues & Resolutions

| Issue | Symptom | Resolution |
|-------|---------|------------|
| Cold start delay | First request takes 30–60s | Keep-alive cron prevents this; or upgrade Render plan |
| Claude API down | `ai` health returns `error` | Check https://status.anthropic.com; model fallback triggers automatically |
| Email not sending | Signups succeed but no email | Check SMTP_HOST, SMTP_USER, SMTP_PASS in Render env vars |
| Twilio SMS failing | SMS messages not processed | Check TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN; verify webhook URL in Twilio console |
| Login always 401 | Clinic can't log in | Check if password was set — use admin reset-password endpoint |
| Trial expired prematurely | Clinic locked out early | Check `trial_ends_at` in DB; use admin activate to extend |

---

# 12. QA TEST STRATEGY

## 12.1 Test Execution

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
TESTING=1 python -m pytest tests/ -v --tb=short

# Run specific suite
python -m pytest tests/test_production_readiness.py::TestAuth -v
```

## 12.2 Test Coverage Summary

| Suite | Tests | Coverage Area |
|-------|:-----:|---------------|
| Health | 2 | Service availability, docs visibility |
| Signup | 6 | Valid, invalid email, invalid plan, plan correctness, short password, missing fields |
| Auth | 8 | Login by email, login by slug, wrong password, enumeration, token verify, invalid token, no token, logout |
| Admin Auth | 4 | No password, wrong password, correct password, SQL injection |
| Chat | 5 | Valid response, empty message, whitespace, nonexistent clinic, config endpoint |
| Plan Gating | 4 | Appointments protected, plan protected, upgrade protected, invalid plan rejected |
| Security | 4 | IDOR blocked, path traversal, webhook, SMS endpoint |
| Token Expiry | 1 | Expired token correctly rejected |
| **Total** | **34** | **All passing** |

## 12.3 Critical Security Test Cases

| ID | Test | Method | Expected |
|----|------|--------|---------|
| SEC-01 | SQL injection in admin password | `X-Admin-Password: ' OR 1=1--` | 401 |
| SEC-02 | IDOR — access another clinic's appointments | Valid token, wrong slug | 403 |
| SEC-03 | Forged billing webhook | POST without valid signature | 400 (if STRIPE_WEBHOOK_SECRET set) |
| SEC-04 | Path traversal | GET `/api/../admin/api/clinics` | 401/403/404 |
| SEC-05 | Empty session token | GET /verify, no header | 401 |
| SEC-06 | Expired session token | Token with past `token_expires_at` | 401 |
| SEC-07 | User enumeration | Login with nonexistent email | Same 401 as wrong password |
| SEC-08 | Invalid plan injection | signup with plan="free_unlimited" | 400 |

---

# 13. TECHNICAL DEBT REPORT

## 13.1 Critical (Block Paid Launch)

| ID | Issue | Root Cause | Risk | Effort |
|----|-------|-----------|------|--------|
| TD-01 | All 10 agent tools are mocks | Real PMS/EHR integration not built | Patients receive fake appointment confirmations and insurance estimates | 3–8 weeks |
| TD-02 | No HIPAA Business Associate Agreement | Legal/compliance not engaged | Platform is technically in violation of HIPAA when handling PHI | External legal |
| TD-03 | Patient data not encrypted at rest | No DB-level encryption | PHI (names, DOBs, phones) stored in plaintext | 2 weeks |

## 13.2 High Priority (Fix Within 30 Days)

| ID | Issue | Root Cause | Risk | Effort |
|----|-------|-----------|------|--------|
| TD-04 | Admin auth is a single shared password | No user accounts for admin panel | Credential leak = full platform compromise | 1 week |
| TD-05 | Test coverage ~40% | Tests written late in development | Regressions ship undetected | 2 weeks |
| TD-06 | Inline HTML in `main.py` | Quick-start architecture choice | Pages are 1,000+ line Python strings; unmaintainable | 1 week |
| TD-07 | No database backup strategy | Render ephemeral disk for SQLite | Data loss on infrastructure restart | 1 day |

## 13.3 Medium Priority (90-Day Window)

| ID | Issue | Root Cause | Risk | Effort |
|----|-------|-----------|------|--------|
| TD-08 | Mock admin analytics in prompts | Hardcoded fake data (lines 113–141 in prompts.py) | Clinics asking "show today's appointments" get fake numbers | 1 week |
| TD-09 | No CSRF protection | Not implemented | CSRF on login/upgrade requests | 1 day |
| TD-10 | No appointment pagination | Hard limit of 200 rows | Clinics with 200+ appointments hit a wall | 2 hours |
| TD-11 | Stripe integration inactive | PayPal manual flow chosen | Revenue ops manual bottleneck; doesn't scale | 1 week |
| TD-12 | `datetime.utcnow()` deprecated | Python 3.12 warning | Will break on Python 3.14+ | 4 hours |
| TD-13 | Chat history stored as TEXT JSON | Schema design | Not queryable; can't search conversation content | 1 week |

---

# 14. ADMIN GUIDE

## 14.1 Accessing the Admin Panel

1. Navigate to `https://aifrontdesk.taborsynergy.com/ts-mgmt`
   *(Or your configured `ADMIN_PANEL_PATH` value)*
2. Enter the `ADMIN_PASSWORD` from your Render environment
3. Password is stored in `sessionStorage` — cleared when tab closes

> ⚠️ **Security:** Do not share the admin URL or password. The admin path should be kept secret and changed from the default `/ts-mgmt` via the `ADMIN_PANEL_PATH` environment variable.

## 14.2 Onboarding a New Clinic

**Step 1 — Create the clinic:**
```
Admin Panel → All Clinics → "+ Add Clinic"
Fill all required fields:
  - Slug: unique URL identifier (e.g., "sunshine-derm")
  - Name, Specialty, Email, Phone
  - Providers, Services, Insurance accepted
  - Office hours, After-hours protocol
  - Cancellation policy, Escalation contact
  - Initial password: temporary login password for clinic (min 6 chars)
```

**Step 2 — Send credentials to clinic:**
```
Email to clinic owner:
  - Chat URL: https://aifrontdesk.taborsynergy.com/c/{slug}
  - Login email: their contact email
  - Temporary password: what you set as initial_password
```

**Step 3 — After payment confirmed:**
```
Admin Panel → All Clinics → Find clinic → Click "Activate 30d"
  OR
PATCH /admin/api/clinics/{slug} → set plan + monthly_rate
POST /admin/api/clinics/{slug}/activate → extends subscription 30 days
```

## 14.3 Managing the Sales Pipeline

**Hot Leads Tab:**
- Clinics with trials expiring in ≤7 days appear here
- Recommended action: personal phone call or personalized email
- Conversion goal: get them to upgrade before trial ends

**MRR Calculation:**
- Sum of `monthly_rate` for all clinics where `subscription_status = "active"`
- Displayed in Stats Cards at top of Pipeline tab

## 14.4 Handling Support Requests

| Request | Admin Action |
|---------|-------------|
| "I can't log in" | Admin Panel → Reset Password → Set new password → Share with clinic |
| "My trial expired" | Admin Panel → Activate 30d (after confirming payment intent) |
| "Wrong plan activated" | PATCH clinic → update plan + monthly_rate → Activate |
| "Need to cancel" | PATCH clinic → subscription_status = "cancelled" |
| "Change agent name" | PATCH clinic → update agent_name field |

---

# 15. PATIENT & CLINIC USER GUIDE

## 15.1 For Patients — Chatting with Aria

**How to start a conversation:**
1. Open the link your clinic shared with you
   *(e.g., `https://aifrontdesk.taborsynergy.com/chat/sunshine-derm`)*
2. Click the blue chat bubble in the bottom-right corner
3. Type your question or choose a quick reply

**What Aria can help with:**

| Need | What to say |
|------|------------|
| Book an appointment | "I'd like to schedule an appointment" |
| Reschedule | "I need to move my appointment to next week" |
| Cancel | "Please cancel my appointment on Tuesday" |
| Check insurance | "Does my Aetna PPO cover a skin check?" |
| Account balance | "What do I owe from my last visit?" |
| Pay a bill | "Can you send me a payment link?" |
| New patient intake | "I'm a new patient, what do I need to fill out?" |
| Office hours | "When are you open?" |
| Talk to a person | "I'd like to speak with someone" |

> **Privacy:** Aria verifies your identity (name, date of birth, and last 4 digits of SSN) before accessing any account information.

---

## 15.2 For Clinic Owners — Using Your Portal

**Login:** Go to `https://aifrontdesk.taborsynergy.com/c/{your-clinic-id}`

### Sharing Aria with Your Patients

1. Log in → **Share with Patients** tab
2. Copy the **Patient Chat Link** and share via:
   - SMS: "Hi! Chat with our AI front desk at [link]"
   - Email signature
   - Google Business profile
   - Instagram/Facebook bio
   - Print the **QR code** for your waiting room

### Viewing Appointments

1. Log in → **Appointments** tab
2. All appointments booked by Aria appear here automatically
3. Use the search bar to filter by patient name or date
4. Click **↻ Refresh** to see latest bookings

### Upgrading Your Plan

1. Log in → **Plan & Billing** tab
2. Review your current usage (conversations used vs. limit)
3. Click **Upgrade Plan →**
4. Select the plan you want
5. Click **Pay with PayPal →** — complete payment
6. Our team will activate your new plan within 24 hours

### Embedding Aria on Your Website

1. Log in → **Embed on Website** tab
2. Copy the `<script>` code snippet
3. Paste it just before the `</body>` tag on any page of your website
4. The Aria chat bubble will appear automatically for all visitors

---

## 15.3 Supported Medical Specialties

| Icon | Specialty |
|------|-----------|
| 🦷 | Dental, Dentistry, Orthodontics, Endodontics, Periodontics, Oral Surgery |
| 🔬 | Dermatology |
| 👶 | Pediatrics |
| 🦴 | Orthopedics, Sports Medicine, Chiropractic |
| 👁️ | Ophthalmology, Optometry, Eye Care |
| 🤰 | OB-GYN, Obstetrics, Gynecology, Prenatal |
| 👂 | ENT (Ear, Nose, Throat) |
| ❤️ | Cardiology |
| 🎗️ | Oncology |
| 🏠 | Family Medicine, Primary Care |
| 🚑 | Urgent Care, Emergency |
| 🧠 | Neurology, Psychiatry, Psychology |
| 🫁 | Pulmonology, Respiratory |
| 🫘 | Nephrology |
| 🏥 | Gastroenterology, Urology, Rheumatology, Surgery, General Practice |
| 💉 | Endocrinology, Diabetes |
| 🩻 | Radiology |
| 🏃 | Physical Therapy, Rehabilitation |

---

*End of Document*

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | June 5, 2026 | Claude Code (reverse-engineered) | Initial generation from source code |

> *This document was generated by reverse-engineering the complete source code of commit `08bf9c0`. It serves as the authoritative reference for developers, architects, QA engineers, DevOps teams, product managers, and future maintenance teams. The codebase is the source of truth; this document reflects the application as-built.*
