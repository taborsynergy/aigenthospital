# Growth Plan ($597/mo) — Feature Guide & Onboarding
**Verified against the codebase on 2026-06-17.** Each feature lists: what it does, whether the code exists, where it lives, how to onboard a clinic, and any dependency/caveat.

**Legend:** ✅ Working · ⚠️ Working but needs external config · ❌ Gap (advertised but not functional)

> Growth = **all Starter features** + the Growth-specific additions below.

---

## Quick status table

| # | Feature | Code | Notes |
|---|---------|------|-------|
| 1 | AI Front Desk Agent (Aria) | ✅ | Core booking via chat |
| 2 | Hosted patient chat link | ✅ | `/c/{slug}` |
| 3 | Appointment booking + dashboard | ✅ | |
| 4 | Email confirmations | ⚠️ | Needs SMTP env vars |
| 5 | 1,000 conversations/month | ✅ | Enforced |
| 6 | Instant-911 emergency escalation | ✅ | Client tripwire + server escalation |
| 7 | 2–5 providers (group practice) | ✅ | Enforced (max 5) |
| 8 | SMS channel (booking + reminders) | ⚠️ | Needs Twilio creds + per-clinic number |
| 9 | Up to 3 locations | ✅ | Enforced (max 3) |
| 10 | Custom insurance knowledge | ✅ | |
| 11 | Monthly performance report | ✅ | |
| 12 | Website embed widget | ✅ | Now plan-gated to Growth+ |
| 13 | Appointment reminders (72h/24h) | ⚠️ | Needs Twilio + hourly cron trigger |
| 14 | Patient recall campaigns | ⚠️ | Needs Twilio + trigger |
| 15 | Real-time analytics dashboard | ✅ | |
| 16 | Custom agent name | ✅ | Now editable self-serve (Growth+) |
| 17 | Priority email support | n/a | Operational |

---

## CORE FEATURES (inherited from Starter, included in Growth)

### 1. AI Front Desk Agent — "Aria" ✅
**What it does:** A 24/7 AI receptionist that greets patients, answers questions (hours, insurance, services), books appointments, declines to diagnose, and escalates emergencies.
**Code:** `backend/agent/aria.py`, `backend/routers/chat.py` (`POST /api/{slug}/chat`, `WS /ws/{slug}/{session_id}`).
**Onboarding steps:**
1. After signup, the agent is live immediately at the clinic's chat link.
2. Tune behavior by completing the clinic profile (hours, services, insurance, cancellation policy) — the agent reads these.
3. Test: open the chat link and ask "What are your hours?" and "I'd like to book an appointment."
**Caveat:** Quality of answers depends on the profile being filled in.

### 2. Hosted Patient Chat Link ✅
**What it does:** A no-login, mobile-friendly page patients open in any browser to chat/book. Shareable by SMS, email, QR.
**Code:** `backend/main.py` → `/c/{slug}` route + QR generation + "How to Share" panel.
**Onboarding steps:**
1. In the clinic portal, open the **Share** panel → copy the patient link.
2. Print the QR code for the waiting room; add the link to the clinic website/Google profile.

### 3. Appointment Booking + Dashboard ✅
**What it does:** Patients book through Aria; staff see every appointment (name, phone, DOB, reason, provider, status) in the portal.
**Code:** `backend/routers/chat.py` → `GET /api/{slug}/appointments` (auth via `x-clinic-token`); booking tools in `backend/agent/tools.py`.
**Onboarding steps:**
1. Log into the clinic portal → **Appointments** tab.
2. Confirm a test booking made via the chat link appears here.

### 4. Email Confirmations ⚠️
**What it does:** Sends booking confirmations / notifications by email.
**Code:** `backend/services/email_svc.py`, `backend/services/appointment_svc.py`.
**Dependency:** Requires **SMTP env vars** (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `NOTIFY_EMAIL`) in Render. Currently **not configured** → emails are skipped (logged, no crash).
**Onboarding steps:**
1. Set the SMTP vars in Render (Gmail App Password or transactional provider).
2. Send a test from the onboarding checklist's "Validate SMTP" step.

### 5. 1,000 Conversations / Month ✅
**What it does:** Growth allows 1,000 patient conversations/month (Starter = 300). Beyond the cap, patients see an upgrade message.
**Code:** `backend/plans.py` (`conversations_limit`), enforced in `chat.py` `_access_blocked` via `monthly_conversation_limit`.
**Onboarding:** Nothing to configure; usage shows in analytics.

### 6. Instant-911 Emergency Escalation ✅
**What it does:** If a patient types an emergency phrase (chest pain, can't breathe, stroke, overdose, suicidal…), the widget shows an immediate "Call 911" banner, and the server flags the conversation + alerts staff.
**Code:** Client tripwire in `frontend/widget.js`; server escalation in `backend/agent/aria.py` (`escalated` flag).
**Onboarding:** Automatic. Optionally set the clinic's `escalation_contact` so staff alerts route correctly.

---

## GROWTH-SPECIFIC FEATURES

### 7. 2–5 Doctor Group Practice (Providers) ✅
**What it does:** Add up to 5 providers; the agent can reference/book with named doctors.
**Code:** `backend/routers/providers.py` (full CRUD); limit enforced by `plans.can_add_provider` (max 5).
**Onboarding steps:**
1. Portal → **Providers** → Add each doctor (name, specialty, optional bio/NPI).
2. Verify the agent offers them: ask the chat "Which doctors do you have?"
**Caveat:** 6th provider is blocked with an upgrade prompt.

### 8. SMS Channel (booking + reminders) ⚠️
**What it does:** Patients text the clinic's number and chat with Aria over SMS; outbound confirmations/reminders/recalls go by SMS.
**Code:** `backend/routers/sms.py` (`POST /sms/inbound`), `backend/services/twilio_svc.py` (`send_sms`).
**Dependencies (must be set up per clinic):**
1. Valid **Twilio account** (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`).
2. A **dedicated Twilio number** per clinic, saved in the clinic's `twilio_phone`.
3. That number's **Messaging webhook** → `https://aifrontdesk.taborsynergy.com/sms/inbound`.
**Onboarding steps:**
1. Buy a Twilio number → set its inbound webhook to `/sms/inbound`.
2. Save the number on the clinic (`twilio_phone`).
3. Test: text the number "book an appointment" → Aria replies.
**Caveat:** Trial Twilio accounts only send to verified numbers.

### 9. Up to 3 Locations ✅
**What it does:** Multiple offices per clinic, each with its own address/hours/providers; the agent can route by location.
**Code:** `backend/routers/locations.py` (CRUD + routing + set-primary); max 3 enforced by plan.
**Onboarding steps:**
1. Portal → **Locations** → add each office (name, address, hours).
2. Mark one **primary**; optionally set ZIP/service routing.

### 10. Custom Insurance Knowledge ✅
**What it does:** Teach the agent which insurances the clinic accepts and plan-specific details, so it answers coverage questions accurately.
**Code:** `backend/routers/insurance.py` (`GET/PATCH /api/{slug}/insurance-knowledge`); gated by `can_use_custom_insurance`.
**Onboarding steps:**
1. Portal → **Insurance** → enter accepted carriers + notes.
2. Test: ask the chat "Do you take Aetna?"

### 11. Monthly Performance Report ✅
**What it does:** A monthly summary (bookings, conversations, no-shows, trends) for the clinic.
**Code:** `backend/services/monthly_report_svc.py` (`generate_monthly_report`, `get_last_month_report`); endpoint `GET /api/{slug}/report/monthly`.
**Onboarding steps:**
1. Portal → **Reports / Analytics** → "Monthly report."
**Caveat:** Meaningful once a month of data exists.

### 12. Website Embed Widget ✅
**What it does:** A copy-paste snippet that embeds the booking chat on the clinic's own website; brandable (color, title, CTA).
**Code:** `backend/routers/widget.py` (`GET/PATCH /api/{slug}/widget/config`), `frontend/widget.js`, embed-code panel in `backend/main.py`.
**Plan-gated:** `can_embed_widget` is now enforced on both endpoints — Starter clinics get a 403 upgrade message; Growth/Enterprise can use it.
**Onboarding steps:**
1. Portal → **Embed on Website** → customize colors/title → copy the snippet.
2. Paste before `</body>` on the clinic site.

### 13. Automated Appointment Reminders (72h + 24h) ⚠️
**What it does:** Sends SMS reminders 72h and 24h before each appointment; patients reply to confirm/cancel — reduces no-shows.
**Code:** `backend/services/reminders_svc.py` (`send_due_reminders`); trigger endpoint `POST /reminders/trigger` (admin-gated).
**Dependencies:**
1. SMS working (feature #8 / Twilio).
2. **An hourly cron** calling `/reminders/trigger`. The app's internal scheduler only runs trial-expiry + onboarding emails — reminders are **not** auto-scheduled in-app.
**Onboarding steps:**
1. Ensure Twilio is configured.
2. Create a **Render Cron Job** (hourly) that POSTs to `/reminders/trigger` with the admin password header.
3. Test via the admin panel's manual trigger.
**⚠️ Without the cron, reminders won't fire automatically.**

### 14. Patient Recall Campaigns ⚠️
**What it does:** Automatically re-engages lapsed patients ("you're due for your annual physical") by SMS — wins back revenue.
**Code:** `backend/routers/recall.py` (campaign CRUD + preview + run), `backend/services/recall_svc.py` (`send_sms`); trigger `POST /api/recall/trigger`.
**Dependencies:** SMS/Twilio + a scheduled trigger (same pattern as reminders).
**Onboarding steps:**
1. Portal → **Recall Campaigns** → create a campaign (visit type, interval months, message).
2. Preview recipients → run (or schedule the trigger).
**Compliance:** Patients can reply `STOP`/`OPTOUT` to unsubscribe (handled).

### 15. Real-Time Analytics Dashboard ✅
**What it does:** Live metrics — bookings, conversations, no-show rate, busy times, provider load.
**Code:** `backend/services/analytics_svc.py`; `GET /api/{slug}/analytics` (`report=full|today|weekly|monthly|...`).
**Onboarding steps:**
1. Portal → **Analytics** tab. No setup needed.

### 16. Custom Agent Name ✅
**What it does:** Rename the AI from "Aria" to a clinic-specific name (e.g., "Bella").
**Code:** `agent_name` is now part of `ClinicProfileUpdate` (validated 2–40 chars), and `PATCH /api/{slug}/profile` writes it. It's **plan-gated**: Growth/Enterprise can change it; Starter gets a 403 upgrade message.
**Onboarding steps:**
1. Portal → **Profile** → set the assistant name.
2. Verify: open the chat — the agent introduces itself with the new name.

### 17. Priority Email Support ✅ (operational)
**What it does:** Faster support response for Growth clinics.
**Code:** n/a — operational/process. Surface your support email in the portal.

---

## Onboarding checklist for a new Growth clinic

1. ☐ Create clinic + admin account (Day-1 kickoff)
2. ☐ Fill clinic profile (hours, services, insurance, cancellation policy)
3. ☐ Add providers (up to 5)
4. ☐ Add locations (up to 3), set primary
5. ☐ Enter custom insurance knowledge
6. ☐ Configure **SMTP** (email confirmations) and validate
7. ☐ Configure **Twilio**: buy number → set `/sms/inbound` webhook → save `twilio_phone`
8. ☐ Set up **hourly cron** → `/reminders/trigger` (and recall trigger) — required for automated reminders/recall
9. ☐ Customize + embed the **website widget**
10. ☐ Create first **recall campaign**
11. ☐ Walk staff through **Appointments** + **Analytics** tabs
12. ☐ Go live → share patient link + QR

---

## Action items to make the plan 100% truthful
- ✅ **Embed widget gated** to Growth+ (`can_embed_widget`) — done.
- ✅ **Custom agent name editable** self-serve, plan-gated — done.
- ⚠️ **Document/automate the reminder + recall cron** — features exist but need an hourly trigger to fire.
- ⚠️ **Configure SMTP + Twilio** — both required for email + SMS features to actually deliver.
