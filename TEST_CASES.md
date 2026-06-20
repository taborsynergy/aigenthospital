# Master Test Case Catalog — Aria AI Front Desk

Single source of truth for the automated test suite. Regenerate the authoritative
list anytime with:

```bash
python -m pytest backend/tests --collect-only -q
```

| Track | Location | Count | Runner |
|---|---|---:|---|
| **Core suite** (unit/integration/security) | `backend/tests/` | **376** (374 pass + 2 skip*) | `pytest` |
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
| test_frontend_a11y.py | 4 | Static a11y guards (lang, contrast, widget aria, 911 banner) | L-1/L-2 |

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
| REG-007 — Appointments "Session expired": cross-clinic token not rejected by `/verify`; portal init IIFE now compares d.slug vs SLUG | 2 | +2 | **376** |
| Wave D — Security (SEC-CSRF + SEC-LOGMON + SEC-MFA) | 3 | pending | — |
| Wave E — A11y/Real-device (A11Y-KEYB + XBR-REAL) | 2 | pending | — |
