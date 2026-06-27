# Master Test Case Catalog — Aria AI Front Desk

Single source of truth for the automated test suite. Regenerate the authoritative
list anytime with:

```bash
python -m pytest backend/tests --collect-only -q
```

| Track | Location | Count | Runner |
|---|---|---:|---|
| **Core suite** (unit/integration/security) | `backend/tests/` | **670** (668 pass + 2 skip*) | `pytest` |
| **Live smoke tests** (positive + negative + corner + security + perf + DB + EMR + URL regression) | `e2e/test_live_smoke.py` | **142** (36 positive + 48 negative/corner + 15 security + 11 perf + 15 DB + 17 EMR + 4 URL) | `pytest` + `httpx` |
| Accessibility + cross-browser | `e2e/` | matrix | Playwright + axe-core |
| Performance (load/stress/spike/soak) | `perf/k6_load.js` + `.github/workflows/perf-k6.yml` | 4 scenarios | k6 (CI) |

\*Skipped unless env provided: `test_supabase_rls_blocks_anonymous_reads` (live
Supabase anon creds) and `test_pool_pre_ping_configured_for_postgres` (Postgres-only,
skipped on SQLite).

Run the core suite: `python -m pytest backend/tests -q`

---

## Coverage by module

| File | Cases | Area | Gap-IDs |
|---|---:|---|---|
| test_chat.py | 33 | Chat/agent REST, config, analytics, profile, multi-turn regression + conversation flows + date awareness | REG-001/MT/REG-003 |
| test_whitelabel.py | 21 | Branding, custom domain, reseller, source-code access | — |
| test_appointments.py | 24 | Appointment list/update, status transitions, isolation, portal visibility regression | REG-002 |
| test_edge_cases.py | 19 | Invalid dates, neg/garbage IDs, IDN domains, volume, indexes | L-3/L-4/L-5 |
| test_providers.py | 18 | Provider CRUD, per-plan provider limits | — |
| test_trial.py | 17 | Signup, trial lifecycle, convert-to-paid, login | — |
| test_input_validation.py | 14 | XSS/SQLi, oversized/malformed payloads, traversal, unicode | NEG |
| test_cross_tenant_idempotency.py | 14 | Cross-tenant matrix (10 routes) + recall/reminder dedup | SEC-008/API |
| test_renewal_reminders.py | 14 | Trial reminder dedup + paid renewal reminders | H-1 area |
| test_high_gaps.py | 13 | Activation idempotency, tz reminders, reset token, roles, concurrency, RLS | H-1..H-8 |
| test_security.py | 12 | Admin auth (timing-safe), RBAC, plan gating, tenant isolation | SEC |
| test_onboarding.py | 11 | Onboarding sessions (Pro+) | — |
| test_auth_hardening.py | 11 | Lockout, rate-limit, JWT expiry/tamper/alg-none, logout | SEC-001..010 |
| test_pagination.py | 10 | Appt + admin pagination, limit/offset/status/sort, BVA extremes | GAP2-API-PAGE/BVA-PAGE |
| test_api_contract.py | 10 | /api/plans schema, JSON errors, SendGrid failure handling | API |
| test_db_integrity.py | 9 | Purge cascade, soft-delete, unique constraints, defaults | DB |
| test_resilience_billing.py | 8 | Payment reconciliation, DB-restart 503, scheduler gate, perf harness | GAP2 H-PERF/PAY/REL |
| test_safety.py | 8 | 911/988 emergency + mental-health crisis tripwire | SAFE |
| test_headers_cors_boundary.py | 8 | Security headers, CORS, input boundaries, reliability | SEC-011/012/BVA/REL |
| test_audit_migrate.py | 7 | Audit trail on create/activate/plan-change/purge/deactivate; migrate idempotency | GAP2-DB-AUDIT/DB-MIGRATE |
| test_change_plan.py | 7 | Plan upgrade/downgrade transitions | — |
| test_email.py | 7 | Email reminders (72h/24h), plan gating | — |
| test_resilience_integration.py | 7 | SendGrid retry/backoff, reminder catch-up, recall batch isolation | GAP2-API-RETRY/REL-SCHED/REL-BATCH |
| test_clinic_profile.py | 6 | Per-clinic profile capture + edit-anytime + isolation | — |
| test_conversation_limits.py | 6 | Conversation tracking + limit enforcement | — |
| test_email_branding.py | 6 | Per-clinic From-name / Reply-To branding | — |
| test_unsubscribe.py | 5 | CAN-SPAM recall unsubscribe (signed token) | — |
| test_phase2_setup.py | 22 | Appointment Types CRUD, Clinic Holidays CRUD, Notification Preferences, system prompt injection | P2 |
| test_portal_render.py | 12 | Portal page GET /c/{slug}: 200 status, all UI landmarks, CSS injection, 404 on missing slug, UTF-8, JS escape guards (toggleDayRow, deleteProvider, deleteAptType) | REG-004/REG-006 |
| test_login_flow.py | 13 | Signup→token, portal_url with ?token=, token verify, login correct/wrong creds (JSON errors), rate-limit JSON, E2E flow, cross-clinic token mismatch guard | REG-005/REG-007 |
| test_clinic_setup_tab.py | 34 | Clinic Setup Tab PATCH /api/{slug}/profile: all fields save + appear in system prompt (phone→Aria prompt), cache invalidation, auth/tenant isolation, input validation (SQL injection, XSS, oversized, plan-gated agent_name) | REG-008 |
| test_frontend_a11y.py | 4 | Static a11y guards (lang, contrast, widget aria, 911 banner) | L-1/L-2 |
| test_landing_cta.py | 21 | Landing page CTA wiring: demo buttons open dedicated demo-request modal (not signup/quote), white-label entry points open quote form, pricing plan buttons, signup/quote/demo modal presence | REG-009 |
| test_landing_links.py | 83 | Landing page link integrity: section anchors, nav/footer hrefs, announcement bar, specialty tabs (6 IDs × 2), all 4 modals + close buttons, 10 JS functions defined, mailto correctness, bare-# onclick guard, external resource https, onclick→function coverage, 17 form element IDs | LNK-001..012 |
| test_demo_request.py | 29 | Demo request feature: POST /api/demo-request happy path + validation, send_demo_request_email (SendGrid recipient, reply-to, subject, unconfigured graceful, HTML slot), frontend modal presence + form wiring + button wiring | DMO-001..004 |
| test_e2e_journeys.py | 71 | End-to-end journeys: Doctor onboarding (signup→login→portal), clinic setup (profile/providers/apt-types), patient chat+booking, information queries (insurance/hours/location/cancellation), appointment management (confirm/complete/cancel/isolation), safety (911/988/crisis), visitor/lead (demo/trial/quote), complete 10-step flow, multi-patient concurrent booking, plan gating | E2E-001..010 |
| test_emr_integration.py | 49 | EMR/EHR Phase 1-3: plan gating, config CRUD, sync-log, patient cache, slot fetch, cross-tenant, secret masking, SQL injection, HIPAA audit, perf SLAs + Phase 2: intake pre-population, Cerner/Athena adapter contract, field-skip logic, Athena slot normalizer + Phase 3: appt type resolver (Epic/Athena/Cerner), slot conflict check, mark-slot-booked, provider NPI token-match, auto-routing fallback, EHR system-prompt injection | EMR-FUNC / EMR-SEC / EMR-PERF / EMR-P2 / EMR-P3-001..015 |
| test_live_smoke.py | 142 | Live smoke tests against https://aifrontdesk.taborsynergy.com — positive journeys (SMOKE-001..007, 36 tests) + negative validation (SMOKE-008..011, 27 tests) + corner/boundary (SMOKE-012..013, 21 tests) + security (SMOKE-014, 15 tests) + performance/SLA (SMOKE-015, 11 tests) + DB persistence/CRUD/isolation (SMOKE-016, 15 tests) + EMR integration (SMOKE-017, 17 tests) + upgrade/email URL regression (SMOKE-018, 4 tests) | SMOKE-001..018 |

---

## Gap-analysis traceability

Test IDs from the QA gap analysis and where they live:

- **SAFE-001..004** (clinical safety) → `test_safety.py`
- **SEC-001..014** (auth hardening, headers, CORS, RBAC, timing-safe) → `test_auth_hardening.py`, `test_security.py`, `test_headers_cors_boundary.py`
- **NEG-001..016** (injection, malformed, oversized, traversal, unicode) → `test_input_validation.py`
- **BVA** (boundary values) → `test_headers_cors_boundary.py`, `test_edge_cases.py`
- **DB-001..013** (integrity, cascade, constraints) → `test_db_integrity.py`
- **API-001..012** (contract, idempotency, provider-failure) → `test_api_contract.py`, `test_cross_tenant_idempotency.py`
- **REL** (reliability) → `test_headers_cors_boundary.py`, `test_cross_tenant_idempotency.py`
- **H-1..H-8** (HIGH) → `test_high_gaps.py` (+ `test_renewal_reminders.py`)
- **L-1..L-5** (LOW) → `test_edge_cases.py`, `test_frontend_a11y.py`, `e2e/`, `perf/`
- **REG-001** (multi-turn chat regression: SDK model_dump() citations:null) → `test_chat.py::TestMultiTurnChatRegression`
- **REG-002** (portal appointments not showing after Aria books: is_active NULL + r.ok unchecked) → `test_appointments.py::TestAppointmentPortalVisibility`
- **REG-003** (Aria date reasoning error: "July 1st already passed" on June 20) → `test_chat.py::TestDateAwarenessRegression`
- **REG-004** (Portal page 500: unescaped `{`/`}` in f-string CSS → NameError at render time) → `test_portal_render.py::TestPortalPageRender`
- **REG-005** (Login "nothing happening": signup returned no token; rate-limit 429 returned plain-text not JSON) → `test_login_flow.py`
- **REG-006** (Portal JS SyntaxError: Python f-string `\'` collapsed to `'`, producing adjacent JS string literals `''` that halt ALL script execution) → `test_portal_render.py`
  - **REG-006a** `toggleDayRow` onclick — hours grid (line 1318) → `test_portal_js_no_adjacent_string_literals_in_onchnage`
  - **REG-006b** `deleteProvider` onclick — provider Remove button (line 1428) → `test_portal_js_no_adjacent_string_literals_in_delete_provider`
  - **REG-006c** `deleteAptType` onclick — appointment type Remove button (line 1569) → `test_portal_js_no_adjacent_string_literals_in_delete_apt_type`
- **REG-007** (Appointments "Session expired": `/verify` accepts any valid token (no slug check), so stale token from clinic-A stored under key for clinic-B passes verify → `showDash()` runs → `/appointments` enforces slug match → 403 → "Session expired") → `test_login_flow.py::TestCrossClinicTokenMismatch`
  - **REG-007a** Portal HTML must contain `d.slug !== SLUG` guard in verify callback → `test_portal_html_contains_slug_mismatch_guard`
  - **REG-007b** `/verify` must return `slug` in JSON response → `test_verify_returns_slug_in_response`
- **REG-008** (Aria shows wrong phone number: `PATCH /api/{slug}/profile` updated the DB but never called `invalidate_prompt()` → cached system prompt kept old phone → Aria told patients the clinic's old/personal number instead of the clinic office number set in Setup tab) → `test_clinic_setup_tab.py`
  - **REG-008a** Phone update must bust prompt cache → `test_phone_update_invalidates_prompt_cache`
  - **REG-008b–z** All 33 additional setup tab tests (field persistence, auth, tenant isolation, input validation)
- **REG-009** ("Book a Demo" / "Book a Live Demo" buttons originally opened the white-label quote modal; then briefly opened the trial signup; now correctly open a dedicated demo-request modal that captures lead details and emails them to the owner) → `test_landing_cta.py`, `test_demo_request.py`
  - **REG-009a** Nav "Book a Demo" must call `openDemoForm()` not `openSignup()`/`openQuoteForm()` → `test_nav_book_a_demo_calls_open_demo_form`
  - **REG-009b** Hero "Book a Live Demo" must call `openDemoForm()` → `test_hero_book_a_live_demo_calls_open_demo_form`
  - **REG-009c** `demo-modal` overlay div must exist → `test_demo_modal_exists`
  - **REG-009d** `demo-success-modal` div must exist → `test_demo_success_modal_exists`
  - **REG-009e** `openDemoForm()` JS function must be defined → `test_open_demo_form_js_defined`
  - **REG-009f** `submitDemoRequest()` JS function must be defined → `test_submit_demo_request_js_defined`
  - **REG-009g** `submitDemoRequest` must POST to `/api/demo-request` → `test_demo_form_posts_to_correct_endpoint`
  - **REG-009h–k** White-label entry points, pricing buttons, and signup modal presence (11 additional checks)
- **DMO-001** (`POST /api/demo-request` happy path) → `test_demo_request.py::TestDemoRequestEndpointHappyPath`
  - **DMO-001a** Valid payload returns 200 `ok=true`
  - **DMO-001b** Response message mentions demo / 24-hour confirmation
  - **DMO-001c** `send_demo_request_email` invoked with correct lead data
  - **DMO-001d** Optional fields (phone, num_providers, message) are accepted
- **DMO-002** (Validation errors) → `test_demo_request.py::TestDemoRequestValidation`
  - **DMO-002a** Missing required fields (full_name, practice_name, specialty, preferred_slot) → 400/422
  - **DMO-002b** Whitespace-only full_name → 400 with "name" in error
  - **DMO-002c** Malformed email → 422
- **DMO-003** (`send_demo_request_email` unit tests) → `test_demo_request.py::TestSendDemoRequestEmail`
  - **DMO-003a** SendGrid path sends to `write2dinakar10@gmail.com` (not `notify_email`)
  - **DMO-003b** Reply-To is set to the lead's email for direct owner reply
  - **DMO-003c** Subject contains practice name for inbox triage
  - **DMO-003d** Returns False gracefully when no transport configured
  - **DMO-003e** HTML body includes the preferred time slot
- **DMO-004** (Frontend modal completeness) → `test_demo_request.py::TestDemoModalFrontend` (14 checks)
- **LNK-001..012** (Landing page link integrity — every href, anchor, tab, modal, JS function, mailto, form element ID) → `test_landing_links.py` (83 tests)
  - **LNK-001** Section anchor IDs exist (features, how-it-works, specialties, pricing, main-nav)
  - **LNK-002** Nav link hrefs all point to existing section IDs + Enterprise has onclick
  - **LNK-003** Footer link hrefs all point to existing section IDs + White Label has onclick
  - **LNK-004** Announcement bar exists and references #pricing
  - **LNK-005** All 6 specialty tab content divs + pills exist and are wired to switchTab()
  - **LNK-006** All 4 modal overlays present, each has close button + overlay-click dismiss
  - **LNK-007** All 10 JS functions defined + PLAN_LABELS/PLAN_AMOUNTS/PAYPAL_ME constants + IntersectionObserver + scroll listener
  - **LNK-008** All mailto links use correct support address
  - **LNK-009** No bare href="#" without onclick (JS-filled success modal links exempted)
  - **LNK-010** Google Fonts preconnect, PayPal logo https, no insecure http:// links
  - **LNK-011** Every onclick function call resolves to a defined function (no dangling references)
  - **LNK-012** All 17 form element IDs referenced in JS exist in HTML
- **E2E-001** (Doctor full onboarding: signup → portal URL → login → token → access) → `test_e2e_journeys.py::TestDoctorOnboardingJourney` (7 tests)
  - E2E-001a Signup creates clinic with slug, portal_url, chat_url, trial_ends_at
  - E2E-001b portal_url contains ?token= for auto-login
  - E2E-001c GET /c/{slug} returns 200 after signup
  - E2E-001d Login with correct credentials returns JWT
  - E2E-001e Wrong password returns 401
  - E2E-001f Token grants access to /appointments
  - E2E-001g No token returns 403
- **E2E-002** (Doctor clinic setup: profile, providers, appointment types, config) → `test_e2e_journeys.py::TestDoctorClinicSetupJourney` (7 tests)
  - E2E-002a Doctor updates phone, address, insurance, office_hours, cancellation_policy
  - E2E-002b Updated fields persist in subsequent GET /profile
  - E2E-002c Doctor adds provider — appears in GET /providers list
  - E2E-002d Doctor adds 3 appointment types — all appear in GET /appointment-types
  - E2E-002e Fresh clinic has empty appointment list
  - E2E-002f Professional plan clinic can set custom agent name
  - E2E-002g GET /config returns clinic_name for widget branding
- **E2E-003** (Patient books via Aria chat) → `test_e2e_journeys.py::TestPatientBookingJourney` (7 tests)
  - E2E-003a Patient sends first message — Aria replies
  - E2E-003b "I need an appointment" triggers booking flow
  - E2E-003c Two messages in same session — both get replies (context maintained)
  - E2E-003d Appointment created appears in doctor's portal list
  - E2E-003e Every appointment has a unique confirmation number
  - E2E-003f Three patients' appointments all appear in list
  - E2E-003g New appointment status defaults to "scheduled"
- **E2E-004** (Patient information queries) → `test_e2e_journeys.py::TestPatientInformationQueries` (18 tests)
  - E2E-004a Insurance queries (3 variants) — Aria always replies
  - E2E-004b Hours queries (3 variants) — Aria always replies
  - E2E-004c Location queries (3 variants) — Aria always replies
  - E2E-004d Cancellation policy queries (3 variants) — Aria always replies
  - E2E-004e "What can you help me with?" — Aria replies
  - E2E-004f Chat always returns JSON not HTML
- **E2E-005** (Doctor manages appointments) → `test_e2e_journeys.py::TestDoctorManagesAppointments` (8 tests)
  - E2E-005a Doctor sees appointment list
  - E2E-005b Appointment has patient_name, type, datetime, status, confirmation_number
  - E2E-005c Doctor confirms an appointment (PATCH → 200)
  - E2E-005d Confirmed status persists in subsequent GET
  - E2E-005e Doctor marks appointment completed
  - E2E-005f Doctor cancels an appointment
  - E2E-005g Doctor cannot PATCH another clinic's appointment (403/404)
  - E2E-005h Appointment list is clinic-isolated (no cross-tenant leakage)
- **E2E-006** (Safety scenarios) → `test_e2e_journeys.py::TestSafetyScenarios` (11 tests)
  - E2E-006a Medical emergencies (5 messages) — Aria always replies, never crashes
  - E2E-006b Mental health crisis (3 messages) — Aria always replies
  - E2E-006c Child swallowed pills — Aria replies
  - E2E-006d Very long input (200× repeat) — never returns 500
  - E2E-006e Empty message — 200/400/422 (not crash)
- **E2E-007** (Visitor/lead journey) → `test_e2e_journeys.py::TestVisitorLeadJourney` (7 tests)
  - E2E-007a GET / returns landing page (200, text/html)
  - E2E-007b Landing page has "Book a Demo" and "Start Free Trial" CTAs
  - E2E-007c Demo form POST → 200 ok
  - E2E-007d Demo form missing required field → 400/422
  - E2E-007e Trial signup POST → clinic with slug + chat_url
  - E2E-007f White-label quote POST → 200 ok
  - E2E-007g GET /api/plans returns all plan tiers
- **E2E-008** (Complete 10-step journey: signup → setup → patient books → doctor confirms) → `test_e2e_journeys.py::TestCompleteEndToEndJourney` (1 test, 10 assertions)
- **E2E-009** (Multi-patient concurrent booking) → `test_e2e_journeys.py::TestMultiPatientJourney` (4 tests)
  - E2E-009a Two patients get different confirmation numbers
  - E2E-009b Both patients appear in doctor portal
  - E2E-009c Two patients chat on same clinic with independent sessions
  - E2E-009d Doctor updates each patient's status independently
- **E2E-010** (Plan gating) → `test_e2e_journeys.py::TestPlanGatingJourney` (5 tests)
  - E2E-010a Starter clinic patients can chat
  - E2E-010b Professional clinic patients can chat
  - E2E-010c Expired trial clinic portal still renders
  - E2E-010d Non-existent clinic slug returns 404
  - E2E-010e Visitor can sign up for the free starter plan
- **GAP2-API-PAGE** (pagination limit/offset/status/sort) → `test_pagination.py`
- **GAP2-BVA-PAGE** (boundary extremes: 0/huge/neg/garbage params) → `test_pagination.py`
- **GAP2-DB-AUDIT** (audit trail on create/activate/plan-change/purge/deactivate) → `test_audit_migrate.py`
- **GAP2-DB-MIGRATE** (migrate_db idempotent on re-run) → `test_audit_migrate.py`
- **GAP2-API-RETRY** (SendGrid 5xx/429 retry, permanent 4xx no retry, max-retry give-up) → `test_resilience_integration.py`
- **GAP2-REL-SCHED** (missed cron run caught up within 6h window) → `test_resilience_integration.py`
- **GAP2-REL-BATCH** (recall batch continues past single failing recipient) → `test_resilience_integration.py`

---

## Full case list

> Generated from `pytest --collect-only`. Parametrized cases (e.g. domain matrix,
> cross-tenant routes, crisis phrases) expand to multiple runs under one name.

For the live, exact list run:

```bash
python -m pytest backend/tests --collect-only -q | grep ::
```

### Separate harnesses (not pytest-counted)

**e2e/ — Accessibility (L-1) + Cross-browser/device (L-2)**
- `landing page has no serious a11y violations` (axe-core WCAG 2.1 A/AA)
- `renders primary CTA on mobile|tablet|desktop`
- Browser matrix: Chromium, Firefox, WebKit, Pixel 7, iPhone 14

**perf/k6_load.js — Performance (H-7 / GAP-PERF)**
- `load` (50 VUs), `stress` (→500 VUs), `spike` (0→200/10s), `soak` (50 VUs × 2h)
- Thresholds: error rate <1%, p95 < 3s

---

## GAP2 Medium-priority closure status

| ID | Description | Status | Test file |
|---|---|---|---|
| GAP2-API-PAGE | Pagination: limit/offset/status/sort + X-Total-Count | ✅ Fixed + tested | test_pagination.py |
| GAP2-BVA-PAGE | Boundary extremes: 0/huge/negative/garbage params → no 422/500 | ✅ Fixed + tested | test_pagination.py |
| GAP2-DB-AUDIT | Audit trail on create/activate/plan-change/purge/deactivate | ✅ Fixed + tested | test_audit_migrate.py |
| GAP2-DB-MIGRATE | migrate_db idempotent (runs twice, no duplicate-column errors) | ✅ Fixed + tested | test_audit_migrate.py |
| GAP2-API-RETRY | SendGrid 5xx/429 retry with backoff; permanent 4xx fails fast | ✅ Fixed + tested | test_resilience_integration.py |
| GAP2-REL-SCHED | Missed hourly cron self-heals within 6h catch-up window | ✅ Fixed + tested | test_resilience_integration.py |
| GAP2-REL-BATCH | Recall batch continues past single failing recipient (per-try/except) | ✅ Fixed + tested | test_resilience_integration.py |
| GAP2-SEC-CSRF | CSRF posture — header-only auth, no Set-Cookie on login | 🔲 Pending (Wave D) | test_security_medium.py |
| GAP2-SEC-LOGMON | Sentry PII scrub — _scrub_sentry_event redacts PHI keys | 🔲 Pending (Wave D) | test_security_medium.py |
| GAP2-SEC-MFA | TOTP 2FA: correct code → 200, wrong → 401; setup flow | 🔲 Pending (Wave D) | test_security_medium.py |
| GAP2-A11Y-KEYB | Keyboard nav + focus trap in booking flow (Tab/Enter/Esc) | 🔲 Pending (Wave E) | e2e/a11y.spec.js |
| GAP2-XBR-REAL | Real-device Playwright: Safari iOS / Android Chrome | 🔲 Pending (Wave E) | playwright.config.js |

**Wave totals added to core suite:**

| Wave | Items | Tests added | New total |
|---|---:|---:|---:|
| Baseline (Waves 1-9, H, L, GAP2-H) | — | 289 | 289 |
| Wave A — Pagination (API-PAGE + BVA-PAGE) | 2 | +10 | 299 |
| Wave B — Audit + Migrate (DB-AUDIT + DB-MIGRATE) | 2 | +7 | 306 |
| Wave C — Resilience (API-RETRY + REL-SCHED + REL-BATCH) | 3 | +7 | 313 |
| REG-001 — Multi-turn chat serialization regression | 1 | +3 | 316 |
| MT — Multi-turn conversation flows (SMS removal + 5 flow tests) | 1 | +6 | 322 |
| REG-002 — Portal appointments visibility (is_active fix + r.ok check) | 1 | +4 | 326 |
| REG-003 — Aria date reasoning (today's date injected into system prompt) | 1 | +3 | 329 |
| Phase 2 — Appointment Types + Holidays + Notification Prefs | 3 | +22 | 351 |
| REG-004 — Portal render regression (GET /c/{slug} must return 200) | 1 | +9 | 360 |
| REG-005 — Login flow regression (signup→token, login JSON errors, rate-limit JSON) | 1 | +11 | 371 |
| REG-006 — Portal JS SyntaxError (Python f-string `\'` → `''` adjacent string literals) | 3 | +3 | 374 |
| REG-007 — Appointments "Session expired": cross-clinic token not rejected by `/verify`; portal init IIFE now compares d.slug vs SLUG | 2 | +2 | 376 |
| REG-008 — Aria uses wrong phone: `update_profile` didn't call `invalidate_prompt()`; clinic Setup tab fields not reflected in Aria's answers | 34 | +34 | 412 |
| REG-009 — Demo buttons wired to white-label quote form instead of trial signup; landing page CTA audit | 17 | +17 | 429 |
| LNK-001..012 — Landing page link integrity (anchors, tabs, modals, JS fns, footer behavior, form IDs, security) | 88 | +88 | **517** |
| Wave D — Security (SEC-CSRF + SEC-LOGMON + SEC-MFA) | 3 | pending | — |
| Wave E — A11y/Real-device (A11Y-KEYB + XBR-REAL) | 2 | pending | — |
