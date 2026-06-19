# Master Test Case Catalog — Aria AI Front Desk

Single source of truth for the automated test suite. Regenerate the authoritative
list anytime with:

```bash
python -m pytest backend/tests --collect-only -q
```

| Track | Location | Count | Runner |
|---|---|---:|---|
| **Core suite** (unit/integration/security) | `backend/tests/` | **289** (287 pass + 2 skip*) | `pytest` |
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
| test_chat.py | 21 | Chat/agent REST, config, analytics, profile | — |
| test_whitelabel.py | 21 | Branding, custom domain, reseller, source-code access | — |
| test_appointments.py | 20 | Appointment list/update, status transitions, isolation | — |
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
| test_api_contract.py | 10 | /api/plans schema, JSON errors, SendGrid failure handling | API |
| test_db_integrity.py | 9 | Purge cascade, soft-delete, unique constraints, defaults | DB |
| test_resilience_billing.py | 8 | Payment reconciliation, DB-restart 503, scheduler gate, perf harness | GAP2 H-PERF/PAY/REL |
| test_safety.py | 8 | 911/988 emergency + mental-health crisis tripwire | SAFE |
| test_headers_cors_boundary.py | 8 | Security headers, CORS, input boundaries, reliability | SEC-011/012/BVA/REL |
| test_change_plan.py | 7 | Plan upgrade/downgrade transitions | — |
| test_email.py | 7 | Email reminders (72h/24h), plan gating | — |
| test_clinic_profile.py | 6 | Per-clinic profile capture + edit-anytime + isolation | — |
| test_conversation_limits.py | 6 | Conversation tracking + limit enforcement | — |
| test_email_branding.py | 6 | Per-clinic From-name / Reply-To branding | — |
| test_unsubscribe.py | 5 | CAN-SPAM recall unsubscribe (signed token) | — |
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
