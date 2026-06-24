# Software Design Document — EMR Integration for Aria AI Front Desk
**Version:** 1.0  
**Date:** 2026-06-23  
**Author:** Tabor Synergy Engineering  
**Status:** Approved for Development  

---

## 1. Executive Summary

This document defines the full design for EMR (Electronic Medical Record) integration in Aria AI Front Desk. The feature moves Aria from a standalone scheduling assistant into a **bi-directional clinical workflow partner** — reading patient context from the clinic's EHR and writing appointments, notes, and intake data back into it automatically.

EMR integration will be offered on **Professional** and **Enterprise** plans (removed from Enterprise-only gate). This directly addresses the request from Raj (2026-06-21) and aligns with the $100M revenue trajectory by dramatically increasing clinic stickiness and expanding the per-seat value proposition.

---

## 2. Market Research — How AI Agents Use EMR Today

### 2.1 What Competitors Are Doing

| Product | EMR Strategy | AI Capability |
|---|---|---|
| **Nuance DAX** (Microsoft) | Deep Epic/Cerner integration | Ambient clinical documentation — listens to visit, auto-fills SOAP notes in EHR |
| **Nabla Copilot** | Epic MyChart, Cerner | Transcribes consultations → pushes structured notes to EHR in real-time |
| **Suki AI** | Epic, Cerner, Athenahealth, eClinicalWorks | Voice-to-EHR dictation; agent drafts referrals and orders |
| **Regard** | Epic (FHIR R4) | Reads entire patient chart; auto-generates diagnosis suggestions at admission |
| **Notable Health** | Epic, Cerner, Veradigm | Patient intake AI that pre-populates EHR fields before visit; sends structured questionnaires |
| **Inflection Health** | Athenahealth, Epic | Conversational AI front desk + auto-creates patient in EHR on first contact |
| **Luma Health** | 50+ EHRs | Automated reminders + waitlist management synced to EHR schedule slots |
| **Klara** | Epic, athenahealth, Nextech | Patient messaging hub that writes messages to EHR chart timeline |

### 2.2 Key Patterns Observed

**Pattern 1 — Read-First, Then Write**  
Every successful product reads patient context from EHR *before* the conversation starts (name, DOB, last visit, allergies, insurance). This makes the AI feel like it *knows* the patient rather than starting cold. Luma Health reports 40% higher patient satisfaction scores from this single change.

**Pattern 2 — FHIR R4 as the Universal Adapter**  
Epic, Cerner, and Athenahealth all expose FHIR R4 APIs. Products that built a single FHIR adapter serve 90%+ of the US market. HL7v2 is legacy (lab/ADT feeds only).

**Pattern 3 — Appointment as the Atomic Unit**  
Every product starts with appointment sync (create/update/cancel in EHR) then expands to demographics, then to clinical data. No product jumped straight to clinical records — the liability and complexity is too high without the scheduling foundation.

**Pattern 4 — AI Reads Chart → Personalises Conversation**  
Inflection Health's AI greets returning patients by name, references their last visit reason, and already knows their insurance. This is achievable by pulling the FHIR `Patient` and `Appointment` resources before the chat session starts.

**Pattern 5 — Structured Intake → EHR Pre-Population**  
Notable Health sends patients a pre-visit questionnaire. The responses are structured by AI and pushed to the EHR as a `QuestionnaireResponse` FHIR resource, saving 8–12 minutes of front-desk data entry per visit.

### 2.3 How This Fits Aria

Aria is currently a **write-only** system — it creates appointments in its own database but has no awareness of the clinic's existing EHR. The gap is:

1. **Aria doesn't know if a patient already exists** in the EHR (creates duplicates)
2. **Aria doesn't know the patient's insurance** (asks for it again)
3. **Aria doesn't know the patient's history** (can't personalise the conversation)
4. **Appointments Aria books don't appear** in the EHR schedule automatically

EMR integration closes all four gaps.

---

## 3. Objectives

| # | Objective | Metric |
|---|---|---|
| O-1 | Eliminate duplicate patient creation | Zero new duplicates after go-live |
| O-2 | Reduce front-desk data re-entry | < 1 min per new patient (from ~8 min) |
| O-3 | Auto-sync Aria appointments to EHR | 100% of appointments reflected in EHR within 30s |
| O-4 | Enable Aria to greet returning patients by name | Returning patient recognition rate > 90% |
| O-5 | Drive Pro plan upgrades | 15% of Starter clinics upgrade within 90 days of announcement |

---

## 4. Plan Gating — Where EMR Lives

### Current State (broken)
EMR is Enterprise-only → zero usage, zero feedback, zero revenue from it.

### New State

| Feature | Starter | **Professional** | **Enterprise** |
|---|---|---|---|
| Appointment sync to EHR | ✗ | ✅ Epic, Cerner, Athena | ✅ All + custom FHIR |
| Patient lookup (returning patient recognition) | ✗ | ✅ | ✅ |
| Pre-visit intake → EHR pre-population | ✗ | ✅ | ✅ |
| Aria reads patient chart (last visit, allergies, meds) | ✗ | ✗ | ✅ |
| Custom EHR adapter (eClinicalWorks, Kareo, etc.) | ✗ | ✗ | ✅ |
| Real-time schedule slot availability from EHR | ✗ | ✅ | ✅ |
| Bi-directional note sync (Aria chat → EHR chart) | ✗ | ✗ | ✅ |
| EHR audit log export | ✗ | ✅ | ✅ |

**Why Pro gets core EMR:**  
Pro clinics ($299/month) are multi-provider practices that *need* EHR sync. Giving them the core 3 features (appointment sync + patient lookup + intake pre-population) is the hook. Enterprise gets full clinical record read access and custom adapters.

---

## 5. Supported EHR Systems

### Phase 1 (Pro + Enterprise) — Ship First
| EHR | Market Share | API | Auth |
|---|---|---|---|
| **Epic** | 38% of US hospitals | FHIR R4 (MyChart API) | OAuth 2.0 + SMART on FHIR |
| **Cerner (Oracle Health)** | 25% of US hospitals | FHIR R4 | OAuth 2.0 |
| **Athenahealth** | 15% of ambulatory | REST + FHIR R4 | OAuth 2.0 |

### Phase 2 (Enterprise) — Ship 60 Days Later
| EHR | Segment | API |
|---|---|---|
| eClinicalWorks | Small/mid practices | REST + HL7v2 |
| Kareo (Tebra) | Small practices | REST |
| DrChrono | Mobile-first practices | REST + FHIR |
| Veradigm (Allscripts) | Specialty | FHIR R4 |

---

## 6. Architecture

### 6.1 System Context

```
┌─────────────────────────────────────────────────────────────────┐
│                    PATIENT CHANNEL                               │
│                  (Chat widget / SMS)                            │
└────────────────────────┬────────────────────────────────────────┘
                         │ message
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ARIA AGENT (FastAPI)                          │
│                                                                  │
│  ┌─────────────┐   ┌──────────────┐   ┌────────────────────┐  │
│  │  Chat       │   │  EMR Tool    │   │  Appointment       │  │
│  │  Engine     │──▶│  Dispatcher  │──▶│  Tool              │  │
│  │  (LLM)      │   │              │   │                    │  │
│  └─────────────┘   └──────┬───────┘   └────────────────────┘  │
│                            │                                     │
└────────────────────────────┼────────────────────────────────────┘
                             │ FHIR R4 / REST
             ┌───────────────┴──────────────────┐
             │                                  │
             ▼                                  ▼
   ┌─────────────────┐               ┌─────────────────────┐
   │  EHR Adapter    │               │  Aria DB            │
   │  Service        │               │  (PostgreSQL)        │
   │                 │               │                     │
   │  ┌───────────┐  │               │  Appointments       │
   │  │  Epic     │  │               │  Patients           │
   │  │  Adapter  │  │               │  EHRConfig          │
   │  ├───────────┤  │               │  EHRSyncLog         │
   │  │  Cerner   │  │               └─────────────────────┘
   │  │  Adapter  │  │
   │  ├───────────┤  │
   │  │  Athena   │  │
   │  │  Adapter  │  │
   │  └───────────┘  │
   └─────────────────┘
             │
             ▼
   ┌─────────────────┐
   │  Clinic's EHR   │
   │  (Epic/Cerner/  │
   │   Athenahealth) │
   └─────────────────┘
```

### 6.2 New Database Tables

#### `emr_patients` — Local patient cache from EHR
```sql
CREATE TABLE emr_patients (
    id                  SERIAL PRIMARY KEY,
    clinic_id           INTEGER REFERENCES clinics(id) ON DELETE CASCADE,
    ehr_patient_id      VARCHAR NOT NULL,          -- EHR's native patient ID
    fhir_id             VARCHAR,                   -- FHIR Patient resource ID
    first_name          VARCHAR NOT NULL,
    last_name           VARCHAR NOT NULL,
    dob                 DATE,
    phone               VARCHAR,
    email               VARCHAR,
    insurance_member_id VARCHAR,
    insurance_payer     VARCHAR,
    last_visit_date     DATE,
    last_visit_reason   VARCHAR,
    known_allergies     TEXT,                      -- JSON array
    active_medications  TEXT,                      -- JSON array (Enterprise only)
    synced_at           TIMESTAMP DEFAULT NOW(),
    INDEX(clinic_id, phone),
    INDEX(clinic_id, email),
    UNIQUE(clinic_id, ehr_patient_id)
);
```

#### `emr_sync_log` — Audit trail for every EHR sync
```sql
CREATE TABLE emr_sync_log (
    id                  SERIAL PRIMARY KEY,
    clinic_id           INTEGER REFERENCES clinics(id),
    direction           VARCHAR NOT NULL,          -- 'inbound' | 'outbound'
    resource_type       VARCHAR NOT NULL,          -- 'Patient' | 'Appointment' | 'QuestionnaireResponse'
    ehr_resource_id     VARCHAR,
    aria_record_id      VARCHAR,
    status              VARCHAR NOT NULL,          -- 'success' | 'failed' | 'skipped'
    error_message       TEXT,
    duration_ms         INTEGER,
    created_at          TIMESTAMP DEFAULT NOW()
);
```

#### `emr_appointments` — EHR-side appointment references
```sql
CREATE TABLE emr_appointments (
    id                  SERIAL PRIMARY KEY,
    clinic_id           INTEGER REFERENCES clinics(id),
    aria_appointment_id INTEGER REFERENCES appointments(id),
    ehr_appointment_id  VARCHAR,                   -- EHR's appointment ID
    ehr_slot_id         VARCHAR,                   -- Slot resource ID (for cancellation)
    sync_status         VARCHAR DEFAULT 'pending', -- 'pending'|'synced'|'failed'|'cancelled'
    last_sync_at        TIMESTAMP,
    error_count         INTEGER DEFAULT 0,
    UNIQUE(clinic_id, aria_appointment_id)
);
```

---

## 7. Feature Design

### 7.1 Feature A — Appointment Sync (Pro + Enterprise)

**What it does:** Every appointment booked by Aria is automatically created as an `Appointment` FHIR resource in the clinic's EHR.

**Trigger:** Aria tool `book_appointment` completes → fires background task  
**Direction:** Outbound (Aria → EHR)  
**Latency target:** < 30 seconds after booking confirmation

**FHIR Payload sent to EHR:**
```json
{
  "resourceType": "Appointment",
  "status": "booked",
  "serviceType": [{"text": "General Practice"}],
  "appointmentType": {"text": "Routine"},
  "start": "2026-07-01T09:00:00-05:00",
  "end": "2026-07-01T09:30:00-05:00",
  "participant": [
    {
      "actor": {"reference": "Patient/{ehr_patient_id}"},
      "status": "accepted"
    },
    {
      "actor": {"reference": "Practitioner/{provider_id}"},
      "status": "accepted"
    }
  ],
  "comment": "Booked via Aria AI Front Desk. Chief complaint: {chief_complaint}"
}
```

**Status sync (bidirectional):**
- Aria CONFIRMS → EHR status: `booked`
- Aria CANCELS → EHR status: `cancelled`
- EHR CANCELS (webhook) → Aria status: `cancelled` (Enterprise)

---

### 7.2 Feature B — Returning Patient Recognition (Pro + Enterprise)

**What it does:** When a patient starts a chat, Aria silently checks the EHR for a matching patient record by phone number or email. If found, Aria personalises the greeting and skips asking for information it already has.

**Trigger:** First message in a new chat session  
**Direction:** Inbound (EHR → Aria)  
**Latency target:** < 2 seconds (cached for session)

**Lookup flow:**
```
Patient says "Hi"
       │
       ▼
Extract phone/email from session context?
       │
  No ──┤── Yes
       │        │
       │        ▼
       │   Query emr_patients cache (< 5ms)
       │        │
       │   Not found ──▶ Query EHR FHIR API
       │        │              │
       │   Found ◀─────────────┘
       │        │
       ▼        ▼
  Standard   Aria receives patient context:
  greeting   {name, insurance, last_visit}
             │
             ▼
         Aria greets: "Welcome back, Sarah!
         I see you last visited for a physical
         in March. How can I help today?"
```

**New Aria tool added:**
```python
{
  "name": "lookup_patient_in_ehr",
  "description": "Look up an existing patient in the clinic EHR by phone or email. Returns name, insurance, and last visit details if found.",
  "input_schema": {
    "type": "object",
    "properties": {
      "phone": {"type": "string"},
      "email": {"type": "string"},
      "dob":   {"type": "string", "description": "YYYY-MM-DD"}
    }
  }
}
```

---

### 7.3 Feature C — Pre-Visit Intake → EHR Pre-Population (Pro + Enterprise)

**What it does:** Aria collects structured intake information during the booking chat (reason for visit, symptoms, duration, insurance update) and pushes it to the EHR as a `QuestionnaireResponse` FHIR resource. Front desk staff sees it pre-filled when the patient arrives.

**Trigger:** Appointment booking confirmed  
**Direction:** Outbound (Aria → EHR)  
**Format:** FHIR `QuestionnaireResponse`

**Aria collects during chat:**
- Chief complaint and duration
- Current medications (yes/no, then list if yes)
- Known allergies
- Insurance change since last visit (yes/no)
- Preferred provider (if multi-provider clinic)

**Data sent to EHR:**
```json
{
  "resourceType": "QuestionnaireResponse",
  "status": "completed",
  "subject": {"reference": "Patient/{ehr_patient_id}"},
  "authored": "2026-07-01T08:45:00Z",
  "source": {"display": "Aria AI Front Desk"},
  "item": [
    {"linkId": "chief-complaint", "text": "Reason for visit",
     "answer": [{"valueString": "Persistent headache for 3 days"}]},
    {"linkId": "current-meds", "text": "Current medications",
     "answer": [{"valueString": "Lisinopril 10mg, Metformin 500mg"}]},
    {"linkId": "allergies", "text": "Known allergies",
     "answer": [{"valueString": "Penicillin"}]},
    {"linkId": "insurance-change", "text": "Insurance changed?",
     "answer": [{"valueBoolean": false}]}
  ]
}
```

---

### 7.4 Feature D — Real-Time Slot Availability from EHR (Pro + Enterprise)

**What it does:** Instead of Aria presenting generic time slots, it queries the EHR's actual `Slot` FHIR resources to show only slots that are truly available in the provider's schedule.

**Trigger:** Patient says "I want to book an appointment"  
**Direction:** Inbound (EHR → Aria)  
**Latency target:** < 3 seconds

**New Aria tool added:**
```python
{
  "name": "get_available_slots_from_ehr",
  "description": "Get real available appointment slots from the EHR schedule for a given date range and provider.",
  "input_schema": {
    "type": "object",
    "properties": {
      "provider_id":  {"type": "string"},
      "start_date":   {"type": "string", "description": "YYYY-MM-DD"},
      "end_date":     {"type": "string", "description": "YYYY-MM-DD"},
      "service_type": {"type": "string"}
    },
    "required": ["start_date"]
  }
}
```

---

### 7.5 Feature E — Full Chart Read (Enterprise Only)

**What it does:** Aria can read the patient's active problem list, medication list, and recent lab results to provide more informed responses (e.g., "I see you're managing Type 2 diabetes — Dr. Smith will need 30 minutes for your HbA1c review").

**FHIR resources read:**
- `Condition` (problem list)
- `MedicationRequest` (active meds)
- `Observation` (lab results — last 90 days)
- `AllergyIntolerance`
- `Immunization`

**Privacy gate:** This data is only used within the session; never logged or stored in Aria's DB beyond the `emr_patients.known_allergies` cache field.

---

### 7.6 Feature F — Bi-Directional Note Sync (Enterprise Only)

**What it does:** After the chat session ends, Aria creates a structured `Communication` FHIR resource in the EHR timeline with a summary of the patient interaction — what was discussed, what was booked, and any flags raised.

**FHIR payload:**
```json
{
  "resourceType": "Communication",
  "status": "completed",
  "category": [{"text": "Patient Contact"}],
  "subject": {"reference": "Patient/{ehr_patient_id}"},
  "sent": "2026-07-01T08:52:00Z",
  "payload": [{
    "contentString": "Patient contacted Aria AI Front Desk. Booked appointment for 2026-07-03 09:00 AM with Dr. Smith. Chief complaint: persistent headache. Stated no insurance changes. No safety concerns raised."
  }],
  "note": [{"text": "Auto-generated by Aria AI Front Desk"}]
}
```

---

## 8. Workflow — End-to-End Patient Journey With EMR Integration

### 8.1 New Patient (First Visit)

```
Step 1: Patient opens chat widget
        Aria: "Hi! I'm Aria, the AI front desk assistant for Westside Family Clinic.
               Are you a new or returning patient?"

Step 2: Patient: "New patient"
        Aria collects: name, DOB, phone, email, reason for visit
        [Background: Aria checks EHR by phone/DOB → no match → confirmed new]

Step 3: Aria offers available slots (pulled live from EHR schedule)
        Aria: "Dr. Smith has openings Tuesday at 9am or Thursday at 2pm.
               Which works better?"

Step 4: Patient selects slot
        Aria collects intake: insurance, current meds, allergies, chief complaint

Step 5: Confirmation sent
        [Background tasks fire in parallel:]
        ├── Create Patient resource in EHR          (FHIR POST /Patient)
        ├── Create Appointment resource in EHR      (FHIR POST /Appointment)
        ├── Push QuestionnaireResponse to EHR       (FHIR POST /QuestionnaireResponse)
        └── Save to Aria appointments table

Step 6: Front desk staff opens EHR the next morning:
        ✅ Patient already registered (no duplicate entry)
        ✅ Appointment on schedule
        ✅ Intake form pre-filled
        ✅ Chief complaint visible in chart
        Time saved: ~8 minutes per new patient
```

### 8.2 Returning Patient

```
Step 1: Patient opens chat widget
        [Background: Aria pulls patient context from EHR cache or live FHIR query]
        Aria: "Welcome back, Robert! Great to hear from you again.
               I see you last visited us in April for a blood pressure check.
               How can I help today?"

Step 2: Patient: "I need to come in again for my blood pressure"
        [Aria already knows insurance, provider preference, allergies]
        Aria skips demographic collection entirely

Step 3: Aria offers slots (live from EHR)
        Patient picks slot

Step 4: Booking confirmed
        [Background tasks:]
        ├── Update Appointment in EHR (linked to existing Patient resource)
        ├── Push intake QuestionnaireResponse
        └── Update Aria appointments table
        Time saved: ~5 minutes (no re-collection of demographics)
```

### 8.3 Cancellation / Reschedule

```
Patient: "I need to cancel my appointment on Thursday"
        │
        ▼
Aria looks up appointment by patient context + date
        │
        ▼
Aria confirms: "I found your appointment with Dr. Smith on Thursday 2pm.
               Shall I cancel it?"
        │
Patient: "Yes"
        │
        ▼
[Parallel:]
├── PATCH /Appointment/{ehr_id} → status: "cancelled"   (EHR)
└── PATCH /api/{slug}/appointments/{conf} → status: "cancelled"  (Aria DB)
        │
        ▼
Aria: "Done! Your appointment has been cancelled. Would you like to reschedule?"
```

---

## 9. Security & Compliance

### 9.1 HIPAA Requirements

| Requirement | Implementation |
|---|---|
| PHI at rest | EHR credentials encrypted (AES-256 via `cryptography` lib) |
| PHI in transit | TLS 1.3 for all EHR API calls; no PHI in query strings |
| Minimum necessary | Aria only reads fields needed for the current operation |
| Audit trail | Every EHR read/write logged in `emr_sync_log` with user, timestamp, resource |
| Access control | EHR config read/write requires clinic admin token |
| Patient data cache | `emr_patients` cache auto-expires after 24h; no clinical data retained beyond session |
| BAA | Clinics must sign BAA before enabling EHR integration |

### 9.2 EHR Credential Storage

```python
# AES-256 encryption for EHR API keys
from cryptography.fernet import Fernet

def encrypt_credential(value: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(value.encode()).decode()

def decrypt_credential(encrypted: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()
```

Encryption key stored in `CREDENTIAL_ENCRYPTION_KEY` Render env var — never in DB.

### 9.3 Rate Limiting & EHR Quotas

| EHR | API Rate Limit | Our Strategy |
|---|---|---|
| Epic | 60 req/min per app | Local cache + exponential backoff |
| Cerner | 100 req/min | Same |
| Athenahealth | 60 req/min | Same |

Cache strategy: Patient lookups cached for 24h. Slot availability cached for 5 minutes.

---

## 10. Error Handling

| Scenario | Aria Behaviour | EHR Behaviour |
|---|---|---|
| EHR API down | Aria continues normally (no EHR features); alerts admin | Sync queued for retry (3 attempts × exponential backoff) |
| Patient not found in EHR | Aria asks patient for info and creates new record | `POST /Patient` on booking |
| Appointment sync fails | Aria confirms to patient; adds to retry queue | Alert sent to admin dashboard |
| Invalid EHR credentials | Admin notified via email; EHR features disabled until fixed | — |
| FHIR validation error | Logged in `emr_sync_log` with full payload | Aria appointment still saved locally |
| Network timeout | Retry after 5s, 30s, 5min | After 3 failures → status: `error` |

---

## 11. New API Endpoints

```
# EHR Configuration (exists, needs plan gate update)
GET    /api/{slug}/ehr-config                  → EHR setup info
PATCH  /api/{slug}/ehr-config                  → Update credentials/settings
POST   /api/{slug}/ehr-config/test             → Validate connection
GET    /api/{slug}/ehr-config/systems          → List supported EHR systems

# Patient Lookup (NEW)
GET    /api/{slug}/emr/patient-lookup          → Search EHR for patient
       ?phone=&email=&dob=

# Slot Availability (NEW)
GET    /api/{slug}/emr/slots                   → Get available slots from EHR
       ?start=&end=&provider=&service_type=

# Sync Log (NEW)
GET    /api/{slug}/emr/sync-log                → Audit log of all EHR syncs
       ?limit=&offset=&status=

# Manual Sync (NEW)
POST   /api/{slug}/emr/sync-appointment/{id}   → Manually push appointment to EHR
```

---

## 12. New Aria Tools

Two new tools added to `backend/agent/tools.py`:

```python
{
    "name": "lookup_patient_in_ehr",
    "description": (
        "Search the clinic's EHR for an existing patient by phone number, email, "
        "or date of birth. Use this early in the conversation to check if the "
        "patient already has a record. Returns name, insurance, last visit info."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "phone": {"type": "string", "description": "Patient phone number"},
            "email": {"type": "string", "description": "Patient email address"},
            "dob":   {"type": "string", "description": "Date of birth YYYY-MM-DD"},
        }
    }
},
{
    "name": "get_available_slots_from_ehr",
    "description": (
        "Retrieve real open appointment slots from the EHR calendar. "
        "Use instead of generic time suggestions when EHR integration is enabled. "
        "Returns a list of available datetime slots."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "start_date":   {"type": "string", "description": "YYYY-MM-DD"},
            "end_date":     {"type": "string", "description": "YYYY-MM-DD"},
            "provider_id":  {"type": "string", "description": "Provider EHR ID (optional)"},
            "service_type": {"type": "string", "description": "Type of appointment"},
        },
        "required": ["start_date"]
    }
}
```

---

## 13. Advantages

### For Clinics (Why They Buy)

| Advantage | Detail |
|---|---|
| **8 min saved per new patient** | No manual entry of demographics, insurance, intake data |
| **Zero duplicate patients** | EHR lookup before creation prevents duplicate medical records |
| **Live schedule accuracy** | Patients only see slots that actually exist in the EHR |
| **Faster day-of-service** | Pre-filled intake means front desk verifies, not enters |
| **Audit trail** | Every AI-patient interaction logged in EHR chart for compliance |
| **Staff morale** | Reduces repetitive copy-paste work; staff focus on patient care |
| **No-show reduction** | Confirmation + reminders tied to real EHR appointment |

### For Aria / Tabor Synergy (Revenue Impact)

| Advantage | Detail |
|---|---|
| **Lock-in** | Clinics with EHR integration have near-zero churn (data embedded in workflow) |
| **Pro plan upgrade driver** | EHR integration is the #1 reason a solo-provider upgrades |
| **Enterprise justification** | Full chart read + note sync = $599+/month justification |
| **Referral engine** | One happy clinic tells their health system → group deal |
| **Data moat** | EHR sync data makes Aria smarter per clinic over time |

### For Patients

| Advantage | Detail |
|---|---|
| **No repeating themselves** | Returning patients never re-enter their history |
| **Accurate scheduling** | Book a real slot, not a generic "Tuesday morning" |
| **Faster check-in** | Pre-filled intake means < 2 min paperwork on arrival |
| **Continuity of care** | Aria's notes appear in their medical chart |

---

## 14. Phased Delivery Plan

### Phase 1 — Foundation (Weeks 1–3)
- [ ] Update plan gating: EMR on Professional + Enterprise (remove Enterprise-only)
- [ ] Add `emr_patients`, `emr_sync_log`, `emr_appointments` DB tables
- [ ] Implement FHIR adapter base class + Epic adapter (FHIR R4)
- [ ] Feature A: Appointment sync (Aria → Epic)
- [ ] Admin setup UI for EHR credentials in portal

### Phase 2 — Patient Intelligence (Weeks 4–6)
- [ ] Feature B: Returning patient lookup tool
- [ ] Update Aria system prompt to use patient context when available
- [ ] Feature C: Intake → EHR pre-population (QuestionnaireResponse)
- [ ] Cerner adapter
- [ ] `emr_sync_log` endpoint for admin dashboard

### Phase 3 — Live Schedule (Weeks 7–8)
- [ ] Feature D: Real-time slot availability from EHR
- [ ] Athenahealth adapter
- [ ] Slot caching layer (5-min TTL)
- [ ] Webhook receiver for EHR-initiated cancellations (Epic)

### Phase 4 — Enterprise Depth (Weeks 9–12)
- [ ] Feature E: Full chart read (Condition, MedicationRequest, Observation)
- [ ] Feature F: Bi-directional note sync (Communication resource)
- [ ] eClinicalWorks + Kareo adapters
- [ ] BAA workflow + consent gating
- [ ] Full HIPAA audit package

---

## 15. Success Metrics

| Metric | Target | Measured At |
|---|---|---|
| Appointment sync success rate | > 99% | Week 4 |
| Patient lookup accuracy (phone match) | > 95% | Week 6 |
| EHR API error rate | < 0.5% | Ongoing |
| Pro plan upgrades attributed to EMR | 15 clinics in 90 days | Day 90 |
| Front-desk time saved per new patient | ≥ 6 minutes | User survey Week 8 |
| Net Promoter Score delta | +15 points vs pre-EMR | Quarter end |

---

## 16. Dependencies

| Dependency | Purpose | Risk |
|---|---|---|
| Epic developer sandbox | Test FHIR integration | Medium — 2-week approval |
| Cerner developer account | Test FHIR integration | Low — self-serve |
| Athenahealth API access | Test REST+FHIR | Medium — approval needed |
| `cryptography` Python lib | Credential encryption | Low — pip install |
| SMART on FHIR OAuth library | Epic/Cerner auth | Low — open source |
| Render background workers | Async EHR sync | Low — already on Render |
| BAA template (legal) | HIPAA compliance | Medium — legal review |

---

## 17. Open Questions

1. **Consent:** Do we ask the patient during chat to consent to EHR data lookup, or rely on the clinic's existing BAA/consent forms?
2. **Epic app registration:** Epic requires app approval for production access. Do we register as a standalone app or work through a partner (Redox, Health Gorilla)?
3. **Telehealth slots:** Should Aria distinguish between in-person and telehealth slots from the EHR calendar?
4. **Multi-location:** For Enterprise clinics with multiple locations, how do we route the EHR lookup to the correct facility?

---

*Document owner: Tabor Synergy Engineering*  
*Next review: 2026-07-07*  
*Related docs: CHURCH_APP_SDD.md, CHURCH_APP_ENTERPRISE_BLUEPRINT.md*
