# Session Handoff — 2026-06-27
## aigenthospital · aifrontdesk.taborsynergy.com

> **Purpose:** Full record of this session so we can pick up exactly here tomorrow.
> **Project:** AI Front Desk SaaS for medical practices — FastAPI backend on Render, Claude Sonnet via OpenRouter.

---

## 🔑 Key Credentials (never commit these)

| Item | Value |
|------|-------|
| Production URL | https://aifrontdesk.taborsynergy.com |
| Smoke test clinic | smoketest@taborsynergy.com / SmokeTest2026! |
| Smoke test slug | smoke-test-clinic-do-not-delet-024dc |
| GitHub repo | taborsynergy/aigenthospital |
| Render service | taborsynergy-agent.onrender.com |

---

## ✅ Everything Completed This Session

### 1. EMR Phase 1 — Epic FHIR R4 (commit `959b0f7`)
- `plans.py` — EHR gate moved from Enterprise-only → **Pro + Enterprise**
- 3 new DB tables: `emr_patients` (24h TTL), `emr_sync_log` (HIPAA audit), `emr_appointments` (15min TTL)
- Epic FHIR R4 adapter: OAuth2 token, `POST /Appointment`, `GET /Patient`, `GET /Slot`
- 2 Aria tools: `lookup_patient_in_ehr`, `get_available_slots_from_ehr`
- `can_use_ehr_integration()` gate in plans.py

### 2. EMR UI + API endpoints (commit `44ab696`)
- Clinic portal: **🏥 EHR Integration tab** added (hidden by default, shown for Pro/Enterprise)
- Status badge (connected/error/inactive), config form, Test Connection button, sync log table
- 3 new API endpoints:
  - `GET /api/{slug}/emr/sync-log`
  - `GET /api/{slug}/emr/patient-lookup`
  - `GET /api/{slug}/emr/slots`
- 41 tests added (24 unit + 17 live smoke SMOKE-017)

### 3. EMR Phase 2 — Cerner + Athenahealth + Intake Pre-population (commit `cc59744`)
- **Cerner FHIR R4**: OAuth token, `POST /Appointment`, `GET /Patient`, `GET /Schedule → /Slot`
- **Athenahealth REST**: OAuth Basic-auth token, `/appointments/open`, `/patients`, paginated slots
- **`prefill_intake_from_ehr()`**: looks up patient, returns `pre_filled` dict + `questions_to_skip` list
- New Aria tool: `prefill_intake_from_ehr` — Aria skips re-asking known fields for returning patients
- Athena appointment type ID resolver wired in
- 10 new Phase 2 tests (34 total in `test_emr_integration.py`)

### 4. EMR Phase 3 — Auto-routing + Smart Scheduling (commit `2485277`)
- **Auto-routing**: `check_appointment_availability` now auto-fetches EHR slots when EHR configured, falls back to mock schedule
- **Appointment type resolver**: maps "annual physical" → Epic serviceType `11`, Athena type `2`, etc. (16 types)
- **Slot conflict detection**: `check_slot_still_available()` + `mark_slot_booked()` — prevents double-booking
- **Provider NPI filtering**: token-based name match ("Dr. Smith" finds "Dr. Jane Smith"), NPI passed to EHR
- **System prompt injection**: `_build_ehr_section()` tells Aria to use `prefill_intake_from_ehr` for returning patients
- `ehr_slot_id` added to `book_appointment` tool schema
- 15 new Phase 3 tests (49 total)

### 5. EMR Phase 4 — Chart Read + Note Sync + eClinicalWorks (commit `dd8e17e`)
- **Enterprise-only gates**: `can_read_patient_chart()`, `can_sync_notes()` in plans.py
- New plan keys: `chart_read: True`, `note_sync: True`, `ecw_integration: True` (Enterprise only)
- 2 new DB tables: `emr_chart_summaries` (1h TTL), `emr_note_syncs` (idempotent per session)
- **Chart read**: Epic + Cerner + Athena + eCW — Condition, MedicationRequest, AllergyIntolerance
- **Note sync**: FHIR DocumentReference (LOINC 11488-4) for Epic/Cerner/eCW; `/patients/{id}/documents` for Athena
- **eClinicalWorks adapter**: full OAuth + all 6 operations (sync, lookup, slots, chart, notes, test connection)
- 2 new Aria tools: `get_patient_chart_summary`, `sync_note_to_ehr`
- 3 new API endpoints: `GET /emr/chart`, `POST /emr/note-sync`, `GET /emr/note-syncs`
- eClinicalWorks added to EHR dropdown UI + `get_supported_ehr_systems()`
- 15 new Phase 4 tests (64 total, all passing)

### 6. Bug Fixes

| Commit | Bug | Fix |
|--------|-----|-----|
| `724657a` | Trial expiry emails linked to ChurchConnect (`app.taborsynergy.com`) | Fixed to `settings.base_url/c/{slug}` in `trial_jobs.py` + `billing_jobs.py` |
| `c431080` | EHR tab not visible until user clicked Plan & Billing tab | `showDash()` now silently fetches plan on login and calls `maybeShowWlTab()` |
| `bd84b97` | 3 smoke test assertions too strict | `010-C` accepts 400, `014-K` accepts 422, `014-N` uses allowed origin |
| `28b41a0` | `test_set_custom_domain` checking `verification_instructions` (renamed key) | Updated to check `dns_instructions.cname_target` |

### 7. Pricing Page Updates
- `f786195` — Growth: added "✓ EHR / EMR integration"; removed "– White label"
- `f786195` — Pro: added "✓ EHR / EMR integration + chart read"
- `44a0f56` — Starter: removed "– Custom agent name" and "– Priority support" crossed-out items

### 8. Pending Items Implemented (commit `bd53016`)
- **Custom domain DNS verification**: `POST /api/{slug}/whitelabel/verify-domain` — live DNS socket lookup, checks if CNAME resolves to Render IPs, auto-sets `domain_verified=True`
- **"🔍 Verify DNS" button** added to White Label tab UI
- **Athenahealth slot refinements**: provider name resolution (providerid → display name), paginated fetching (up to 150 slots), multi-format date parser
- **GitHub Actions uptime monitor**: `.github/workflows/uptime-monitor.yml` — pings `/api/health` every 5 min, emails on failure

### 9. Obsidian MCP Connected
- `~/.claude/mcp.json` created
- Package: `mcp-obsidian`
- Vault: `aigenthospital/aiagent/`
- **Needs Claude Code restart to activate MCP tools** — after restart, Obsidian tools appear as `mcp__obsidian__*`

### 10. Presentation Updated
- `HospitalAI_Aria_Deck_FULL_v3.pptx` — fully rebuilt, 10 slides
  - Slide 1: Cover (with "EHR / EMR connected" pill)
  - Slide 2: What Aria Does (EHR as 6th capability)
  - Slide 3: Pricing (EHR on Growth + Pro)
  - Slide 4: Why Practices Choose Aria
  - Slide 5: Starter detail
  - Slide 6: Growth detail (EHR Ph1-3 added)
  - Slide 7: Pro detail (EHR Ph1-4 added, all LIVE)
  - Slide 8: EMR Use Case — Maria's 8-step patient journey
  - Slide 9: EMR Feature Breakdown — 17-row table
  - Slide 10: Current Status & Roadmap

---

## 📊 Test Results (end of session)

| Suite | Tests | Pass | Skip | Fail |
|-------|------:|-----:|-----:|-----:|
| `backend/tests/` (unit) | 685 | 683 | 2 | **0** |
| `e2e/test_live_smoke.py` | 146 | 144 | 1 | **0** |
| **Total** | **831** | **827** | **3** | **0** |

### Test file breakdown (unit)

| File | Count | Coverage |
|------|------:|---------|
| `test_emr_integration.py` | 64 | EMR Ph1-4 all phases |
| `test_e2e_journeys.py` | 71 | Full end-to-end flows |
| `test_landing_links.py` | 83 | Landing page integrity |
| `test_chat.py` | 33 | Aria agent + analytics |
| `test_clinic_setup_tab.py` | 34 | Profile CRUD |
| `test_demo_request.py` | 29 | Demo request flow |
| + 26 more files | ~371 | Auth, billing, DB, security... |

### Live smoke coverage (SMOKE-001 to SMOKE-018)
- SMOKE-001..007: Positive journeys (36 tests)
- SMOKE-008..013: Negative + corner cases (48 tests)
- SMOKE-014: Security (15 tests)
- SMOKE-015: Performance SLAs (11 tests)
- SMOKE-016: DB persistence/CRUD/isolation (15 tests)
- SMOKE-017: EMR integration live (17 tests)
- SMOKE-018: Upgrade email URL regression (4 tests)

---

## 🗃️ Architecture Reference

```
backend/
├── plans.py              ← Plan gates (Starter/Professional/Enterprise)
├── services/
│   └── ehr_svc.py        ← ALL EHR logic (Epic/Cerner/Athena/eCW) — Phase 1-4
├── agent/
│   ├── tools.py          ← Aria tool definitions + dispatch
│   └── prompts.py        ← System prompt builder (incl. EHR section)
├── routers/
│   ├── ehr.py            ← /api/{slug}/ehr-config + /emr/* endpoints
│   └── whitelabel.py     ← /api/{slug}/whitelabel/* incl. DNS verify
└── db/
    └── models.py         ← All SQLAlchemy models incl. EMR* tables
```

### Key environment variables (Render)
- `OPENROUTER_API_KEY` — routes Aria LLM through OpenRouter
- `OPENROUTER_MODEL` — `anthropic/claude-sonnet-4-5`
- `ALLOWED_ORIGINS` — `https://aifrontdesk.taborsynergy.com,https://taborsynergy-agent.onrender.com`
- `SENTRY_DSN` — error tracking (already set)
- `ADMIN_PASSWORD` — admin panel access

---

## 📋 Tomorrow's TODO

### High priority
- [ ] **Restart Claude Code** to activate Obsidian MCP tools (`mcp__obsidian__*`)
- [ ] **Run live smoke tests fresh** (rate limit resets overnight)
  ```powershell
  $env:LIVE_BASE_URL      = "https://aifrontdesk.taborsynergy.com"
  $env:SMOKE_CLINIC_EMAIL = "smoketest@taborsynergy.com"
  $env:SMOKE_CLINIC_PASS  = "SmokeTest2026!"
  $env:SMOKE_CLINIC_SLUG  = "smoke-test-clinic-do-not-delet-024dc"
  python -m pytest e2e/test_live_smoke.py -v
  ```

### EMR follow-ups
- [ ] Athena slot display refinements — test with real Athena sandbox credentials
- [ ] Custom domain SSL — needs per-clinic Render domain config (DevOps task)
- [ ] EMR Phase 4: add chart read + note sync to the EHR tab UI (not yet in portal)

### Business
- [ ] Raj's EMR+EHS request (discussed 2026-06-21) — book follow-up to show demo
- [ ] Set up UptimeRobot as backup (GitHub Actions monitor is now live, but UptimeRobot is better for SMS alerts)
- [ ] Review OpenRouter API key usage — rotate if needed

---

## 💡 Key Technical Decisions Made

1. **EHR moved to Pro + Enterprise** (was Enterprise-only) — to drive plan upgrades and clinic stickiness
2. **OpenRouter as LLM proxy** — `base_url="https://openrouter.ai/api/"` (trailing slash critical — SDK appends `v1/messages`)
3. **Token-based provider name matching** — "Dr. Smith" matches "Dr. Jane Smith" using set intersection, not substring
4. **Note sync is idempotent** — one `emr_note_syncs` row per `session_id`, second call returns existing doc ID
5. **Athena uses REST not FHIR** — completely different API style from Epic/Cerner; slot pagination needed
6. **EHR tab visibility bug** — `maybeShowWlTab()` only ran when Plan tab was clicked; fixed to run on `showDash()` (login)

---

*Saved by Claude Sonnet 4.6 at end of session 2026-06-27*
