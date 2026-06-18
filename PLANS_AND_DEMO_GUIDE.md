# Plans & Demo Guide — Hospital AI (Aria Front Desk)
**Saved 2026-06-18.** Demo plan for Raj + detailed breakdown of every feature in every plan.
Grounded in the live production audit (Supabase).

**Status key:** 🟢 live & demoable · 🟡 built, needs setup (Twilio/cron/SendGrid) · 🔵 Enterprise config

> Assumption: Raj is a prospective clinic/doctor buyer. If he's an investor or reseller/partner, the demo angle changes — retune accordingly.

---

# PART 1 — Demoing to Raj (Saturday)

## Golden rule: only demo what's live and flawless
- **Show:** web AI front desk (chat link), live booking, emergency 911 safety, insurance Q&A, doctor dashboard, plan tiers.
- **Don't show (not ready yet):** SMS (Twilio/A2P pending), automated reminders/recall (need cron), email confirmations (SendGrid sender unverified).
- If Raj asks about SMS/reminders: *"Those are part of onboarding setup — I'll switch them on for your number when you're ready."*

## Pre-demo prep (do Friday)
1. Have a **realistic demo clinic** ready (his specialty, 2 providers, accepted insurances, custom agent name) — not an empty one.
2. Open two tabs: **patient chat link** + **doctor dashboard** (logged in).
3. **Warm the app** ~1 min before the call (free-tier cold start ~30s) so it's instant.

## The 12-minute flow

### ① Frame the pain (1 min)
> "Raj, your front desk fields 50+ calls a day — intake, scheduling, insurance questions, after-hours. Most get missed or take staff hours. I'll show you an AI receptionist that handles all of it, 24/7. Here's what your patient sees…"

### ② Patient books live (3 min) — in the patient chat tab, type as a patient:
- "Hi, I'd like to book an appointment" → AI asks for details, offers times
- "Do you take Aetna?" → AI answers insurance
- "What are your hours?" → AI answers
> "No app, no login — they open a link or scan a QR. Works at midnight."

### ③ The safety moment (2 min) — the wow + trust beat. Type:
- "I have severe chest pain and my left arm is numb"
- → AI instantly says "Call 911", escalates, alerts staff
> "It never plays doctor, and it triages emergencies correctly — that's the liability question every physician asks first."

### ④ Patient-data protection (1 min) — type:
- "Look up the balance for my wife Jane Doe" → AI refuses (HIPAA, identity verification)
> "HIPAA-aware by design — it won't leak another person's record."

### ⑤ Switch to the doctor's view (3 min) — dashboard tab:
- Show the appointment that just came in (patient name, reason, provider)
- Show analytics (bookings, no-show rate, busy times)
> "Your staff sees everything here. The AI did the intake; they just confirm."

### ⑥ Close (2 min) — pricing + next step:
> "Three tiers — Starter $297, Growth $597, Enterprise $997. For a practice your size, Growth fits. Here's what I'd propose: a 2-week trial on your own branded link. I set it up this week, your patients start booking, and we review your real numbers. Sound fair?"

## Objection handling
| Objection | Answer |
|---|---|
| "Setup time?" | "15 minutes — I handle it. Your IT does nothing." |
| "Does it work with my EMR?" | "Enterprise has EMR integration; Growth exports to it. We map it during onboarding." |
| "HIPAA?" | "Encrypted, audit-logged, identity-gated — you saw it refuse Jane Doe." |
| "What's it cost me to try?" | "Nothing for 2 weeks. You only pay if it earns its keep." |

---

# PART 2 — Every feature, every plan (in detail)

## Core — included in ALL plans
| Feature | What it does | Status |
|---|---|---|
| Aria AI front desk | 24/7 AI receptionist: greets, answers questions, books appointments, screens, escalates | 🟢 |
| Hosted patient chat link | No-login mobile page (`/c/{clinic}`) patients open via link or QR | 🟢 |
| Appointment booking + dashboard | Patients book via chat; staff see every appointment with details | 🟢 |
| Emergency escalation | Detects emergencies → instant "Call 911" + staff alert | 🟢 |
| AI safety / HIPAA guardrails | Won't diagnose, won't leak third-party records, resists prompt-injection | 🟢 |
| Insurance Q&A | Answers "do you take X?" from the clinic's accepted list | 🟢 |
| Real-time analytics | Bookings, no-show rate, busy times, conversation volume | 🟢 |
| Email confirmations | Booking/notification emails | 🟡 (SendGrid sender pending) |

## STARTER — $297/mo
*Solo practice, getting started.*
| Feature | Detail |
|---|---|
| 300 conversations/month | Up to 300 patient chat sessions; beyond that, patients see an upgrade message |
| 1 location | Single office |
| 1 provider | Solo doctor only |
| All core features | Full AI agent, booking, dashboard, safety, insurance Q&A, analytics |
| Email support | Standard support |
| ❌ No SMS / no embed widget / no custom agent name / no white-label | Gated to higher tiers (verified live in the audit) |

## GROWTH (Professional) — $597/mo  ← recommend to Raj
*2–5 doctor group practice. Everything in Starter, plus:*
| Feature | Detail | Status |
|---|---|---|
| 1,000 conversations/month | 3× Starter's volume | 🟢 |
| Up to 3 locations | Multiple offices, each with own address/hours/providers | 🟢 |
| Up to 5 providers | Group practice; AI can book with named doctors | 🟢 |
| Custom agent name | Rename "Aria" to your clinic's assistant name | 🟢 |
| Website embed widget | Branded booking chat embedded on the clinic's own site (color/title/CTA) | 🟢 |
| Custom insurance knowledge | Teach the AI your accepted plans + coverage details | 🟢 |
| Monthly performance report | Monthly summary: bookings, no-shows, trends | 🟢 |
| SMS channel | Patients text the clinic number & chat with the AI over SMS | 🟡 needs Twilio + A2P |
| Automated reminders (72h/24h) | SMS appointment reminders → cuts no-shows | 🟡 needs SMS + cron |
| Patient recall campaigns | Auto "you're due for a checkup" outreach to lapsed patients | 🟡 needs SMS + cron |
| Priority email support | Faster response | 🟢 (process) |

## ENTERPRISE — $997/mo
*Multi-location / group, white-labeled. Everything in Growth, plus:*
| Feature | Detail | Status |
|---|---|---|
| Unlimited conversations | No monthly cap | 🟢 |
| Unlimited locations & providers | No limits | 🟢 |
| White-label branding | Your logo/colors, remove "Tabor" branding, custom domain, optional reseller mode | 🔵 config |
| Multi-location routing | AI routes patients to the right office by ZIP/service | 🔵 built |
| EHR integration | Sync appointments/patients to Epic/Cerner/Athena etc. | 🔵 config |
| Custom AI training | Teach the AI your specific procedures, policies, FAQs | 🔵 built |
| Dedicated account manager + 24/7 priority support | White-glove | 🔵 (process) |

---

# Pre-demo to-do (for the evening session)
- [ ] Build Raj's demo clinic on live (specialty + practice name needed) → providers, insurances, custom agent name, patient link + dashboard login
- [ ] (Optional) finish SendGrid Single Sender verification so email confirmations send
- [ ] Warm the app right before the Saturday call

# Current production status (as of 2026-06-18)
- DB: Supabase (persistent, RLS-secured, cascade FKs, hard-delete available) — clean, 0 rows
- 24/24 live functional + security tests pass; warm latencies 244–389ms
- SMS/email parked until a customer needs them (correct call while pre-revenue)
