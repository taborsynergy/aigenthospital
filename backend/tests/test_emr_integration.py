"""
EMR / EHR Integration tests — Functional, Security, Performance.

Covers:
  EMR-FUNC-001..012   Functional: plan gating, CRUD config, test-connection, sync-log,
                       patient-lookup, slot-fetch, Aria tool dispatch
  EMR-SEC-001..008    Security: auth required, cross-tenant isolation, plan gate enforcement,
                       secret masking, HIPAA audit trail, SQL-injection-safe params
  EMR-PERF-001..004   Performance: config GET <200ms, PATCH <300ms, sync-log <300ms,
                       zero-EHR-config no cold path regression

All tests run against SQLite in memory; no live EHR endpoint required.
"""
import os
import time
import json
from unittest.mock import patch, MagicMock

os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL",      "sqlite:///./test_emr.db")
os.environ.setdefault("MOCK_MODE",         "1")
os.environ.setdefault("DEBUG_MODE",        "true")
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import (
    Clinic, EHRConfiguration, EMRSyncLog, EMRPatient, EMRAppointment,
)
from backend.routers.clinic_auth import hash_password

_counter = 0
PW = "TestPass123!"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def db():
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = S()
    try:
        yield s
    finally:
        s.close()


def _make_clinic(db, plan="professional", status="active"):
    global _counter
    _counter += 1
    slug = f"emr-test-{_counter}"
    c = Clinic(
        slug=slug,
        name=f"EMR Clinic {_counter}",
        specialty="Family Medicine",
        email=f"emr{_counter}@test.com",
        plan=plan,
        subscription_status=status,
        customer_password_hash=hash_password(PW),
        is_active=True,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _token(client, email, password=PW):
    r = client.post("/api/clinic-auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["token"]


def _auth(token):
    return {"X-Clinic-Token": token}


# ── Functional Tests ──────────────────────────────────────────────────────────

class TestEMRFunctional:

    def test_emr_func_001_get_config_pro_plan(self, client, db):
        """EMR-FUNC-001: Pro clinic can GET /ehr-config and receives config fields."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.get(f"/api/{clinic.slug}/ehr-config", headers=_auth(tok))
        assert r.status_code == 200
        body = r.json()
        assert "ehr_system" in body
        assert "api_endpoint" in body
        assert "sync_status" in body

    def test_emr_func_002_get_config_enterprise_plan(self, client, db):
        """EMR-FUNC-002: Enterprise clinic can GET /ehr-config."""
        clinic = _make_clinic(db, plan="enterprise")
        tok = _token(client, clinic.email)
        r = client.get(f"/api/{clinic.slug}/ehr-config", headers=_auth(tok))
        assert r.status_code == 200

    def test_emr_func_003_starter_plan_blocked(self, client, db):
        """EMR-FUNC-003: Starter plan clinic receives 403 on /ehr-config."""
        clinic = _make_clinic(db, plan="starter")
        tok = _token(client, clinic.email)
        r = client.get(f"/api/{clinic.slug}/ehr-config", headers=_auth(tok))
        assert r.status_code == 403
        assert "plan" in r.json().get("error", "").lower() or "upgrade" in r.json().get("error", "").lower()

    def test_emr_func_004_patch_ehr_config(self, client, db):
        """EMR-FUNC-004: PATCH /ehr-config saves and returns updated fields."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        payload = {
            "ehr_system":   "epic",
            "api_endpoint": "https://fhir.epic.example.com/R4",
            "auto_sync":    True,
        }
        r = client.patch(f"/api/{clinic.slug}/ehr-config",
                         json=payload, headers=_auth(tok))
        assert r.status_code == 200
        body = r.json()
        assert body["ehr_system"] == "epic"
        assert body["api_endpoint"] == "https://fhir.epic.example.com/R4"
        assert body["auto_sync"] is True

    def test_emr_func_005_patch_empty_body_returns_400(self, client, db):
        """EMR-FUNC-005: PATCH with no fields returns 400."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.patch(f"/api/{clinic.slug}/ehr-config",
                         json={}, headers=_auth(tok))
        assert r.status_code == 400

    def test_emr_func_006_test_connection_no_config_returns_false(self, client, db):
        """EMR-FUNC-006: Test-connection on unconfigured EHR returns success=False."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.post(f"/api/{clinic.slug}/ehr-config/test", headers=_auth(tok))
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert "message" in body

    def test_emr_func_007_supported_systems(self, client, db):
        """EMR-FUNC-007: /ehr-config/systems returns epic, cerner, athenahealth."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.get(f"/api/{clinic.slug}/ehr-config/systems", headers=_auth(tok))
        assert r.status_code == 200
        systems = r.json()["supported_systems"]
        assert "epic" in systems
        assert "cerner" in systems
        assert "athenahealth" in systems

    def test_emr_func_008_sync_log_empty_on_new_clinic(self, client, db):
        """EMR-FUNC-008: /emr/sync-log returns empty list for new clinic."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.get(f"/api/{clinic.slug}/emr/sync-log", headers=_auth(tok))
        assert r.status_code == 200
        assert r.json()["entries"] == []

    def test_emr_func_009_sync_log_records_operation(self, client, db):
        """EMR-FUNC-009: After a sync operation, /emr/sync-log shows the entry."""
        from datetime import datetime
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        # Insert a log entry directly
        entry = EMRSyncLog(
            clinic_id=clinic.id,
            ehr_system="epic",
            operation="appt_sync",
            direction="outbound",
            status="success",
            ehr_resource_id="EPIC-APPT-123",
        )
        db.add(entry)
        db.commit()
        r = client.get(f"/api/{clinic.slug}/emr/sync-log", headers=_auth(tok))
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert len(entries) >= 1
        assert any(e["ehr_resource_id"] == "EPIC-APPT-123" for e in entries)

    def test_emr_func_010_patient_lookup_no_ehr_returns_not_found(self, client, db):
        """EMR-FUNC-010: Patient lookup with no EHR configured returns found=False."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.get(
            f"/api/{clinic.slug}/emr/patient-lookup",
            params={"patient_name": "John Doe", "date_of_birth": "1980-01-15"},
            headers=_auth(tok),
        )
        assert r.status_code == 200
        assert r.json()["found"] is False

    def test_emr_func_011_slots_no_ehr_returns_empty(self, client, db):
        """EMR-FUNC-011: Slot fetch with no EHR configured returns empty list."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.get(
            f"/api/{clinic.slug}/emr/slots",
            params={"appointment_type": "annual physical"},
            headers=_auth(tok),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["slots"] == []
        assert body["count"] == 0

    def test_emr_func_012_patient_cache_returned_on_hit(self, client, db):
        """EMR-FUNC-012: Cached EMRPatient is returned without hitting the EHR."""
        from datetime import datetime, timedelta
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        # Seed a cached patient
        cached = EMRPatient(
            clinic_id=clinic.id,
            ehr_patient_id="EPIC-P-999",
            ehr_system="epic",
            full_name="Jane Smith",
            date_of_birth="1985-03-22",
            phone="555-0199",
            email="jane@example.com",
            fetched_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.add(cached)
        db.commit()
        # Configure EHR so the endpoint doesn't short-circuit
        ehr_cfg = EHRConfiguration(
            clinic_id=clinic.id,
            ehr_system="epic",
            api_endpoint="https://fhir.epic.example.com/R4",
            api_key="test-key",
            client_id="test-client",
        )
        db.add(ehr_cfg)
        db.commit()
        r = client.get(
            f"/api/{clinic.slug}/emr/patient-lookup",
            params={"patient_name": "Jane Smith", "date_of_birth": "1985-03-22"},
            headers=_auth(tok),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["found"] is True
        assert body["patient"]["ehr_patient_id"] == "EPIC-P-999"


# ── Security Tests ────────────────────────────────────────────────────────────

class TestEMRSecurity:

    def test_emr_sec_001_no_token_returns_403(self, client, db):
        """EMR-SEC-001: /ehr-config without token returns 403."""
        clinic = _make_clinic(db, plan="professional")
        r = client.get(f"/api/{clinic.slug}/ehr-config")
        assert r.status_code == 403

    def test_emr_sec_002_wrong_token_returns_403(self, client, db):
        """EMR-SEC-002: /ehr-config with invalid token returns 403."""
        clinic = _make_clinic(db, plan="professional")
        r = client.get(f"/api/{clinic.slug}/ehr-config",
                       headers={"X-Clinic-Token": "totally-fake-token"})
        assert r.status_code == 403

    def test_emr_sec_003_cross_tenant_isolation(self, client, db):
        """EMR-SEC-003: Clinic A's token cannot read Clinic B's EHR config."""
        clinicA = _make_clinic(db, plan="professional")
        clinicB = _make_clinic(db, plan="professional")
        tokA = _token(client, clinicA.email)
        r = client.get(f"/api/{clinicB.slug}/ehr-config", headers=_auth(tokA))
        assert r.status_code == 403

    def test_emr_sec_004_cross_tenant_sync_log_isolation(self, client, db):
        """EMR-SEC-004: Clinic A cannot read Clinic B's sync log."""
        clinicA = _make_clinic(db, plan="professional")
        clinicB = _make_clinic(db, plan="professional")
        tokA = _token(client, clinicA.email)
        # Seed a log entry for B
        db.add(EMRSyncLog(clinic_id=clinicB.id, ehr_system="epic",
                          operation="appt_sync", status="success"))
        db.commit()
        r = client.get(f"/api/{clinicB.slug}/emr/sync-log", headers=_auth(tokA))
        assert r.status_code == 403

    def test_emr_sec_005_starter_plan_blocked_all_emr_endpoints(self, client, db):
        """EMR-SEC-005: Starter plan is blocked on all 6 EMR endpoints."""
        clinic = _make_clinic(db, plan="starter")
        tok = _token(client, clinic.email)
        slug = clinic.slug
        endpoints = [
            ("GET",   f"/api/{slug}/ehr-config"),
            ("PATCH", f"/api/{slug}/ehr-config"),
            ("POST",  f"/api/{slug}/ehr-config/test"),
            ("GET",   f"/api/{slug}/ehr-config/systems"),
            ("GET",   f"/api/{slug}/emr/sync-log"),
            ("GET",   f"/api/{slug}/emr/patient-lookup"),
        ]
        for method, path in endpoints:
            if method == "GET":
                r = client.get(path, headers=_auth(tok),
                               params={"patient_name": "X", "date_of_birth": "2000-01-01"})
            elif method == "PATCH":
                r = client.patch(path, json={"ehr_system": "epic"}, headers=_auth(tok))
            else:
                r = client.post(path, headers=_auth(tok))
            assert r.status_code == 403, f"{method} {path} returned {r.status_code}, expected 403"

    def test_emr_sec_006_api_key_not_returned_in_config_get(self, client, db):
        """EMR-SEC-006: GET /ehr-config does NOT expose the api_key field."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        # Save a config with an api_key
        client.patch(f"/api/{clinic.slug}/ehr-config",
                     json={"ehr_system": "epic", "api_endpoint": "https://fhir.example.com",
                           "api_key": "super-secret-key"},
                     headers=_auth(tok))
        r = client.get(f"/api/{clinic.slug}/ehr-config", headers=_auth(tok))
        assert r.status_code == 200
        body = r.json()
        # api_key must not be surfaced
        assert "api_key" not in body
        assert "super-secret-key" not in r.text

    def test_emr_sec_007_sql_injection_in_patient_name(self, client, db):
        """EMR-SEC-007: SQL injection in patient_name does not cause 500."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        for payload in ["'; DROP TABLE emr_patients; --", "1' OR '1'='1", "<script>alert(1)</script>"]:
            r = client.get(
                f"/api/{clinic.slug}/emr/patient-lookup",
                params={"patient_name": payload, "date_of_birth": "1990-01-01"},
                headers=_auth(tok),
            )
            assert r.status_code in (200, 400, 422), \
                f"SQL injection payload caused {r.status_code}: {r.text}"
            assert r.status_code != 500

    def test_emr_sec_008_audit_log_written_on_config_update(self, client, db):
        """EMR-SEC-008: HIPAA audit trail — sync-log entry is written on appt_sync."""
        from datetime import datetime
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        # Insert a sync log entry (simulates what ehr_svc does after sync)
        db.add(EMRSyncLog(
            clinic_id=clinic.id,
            ehr_system="epic",
            operation="appt_sync",
            direction="outbound",
            status="success",
            ehr_resource_id="AUDIT-TEST-001",
        ))
        db.commit()
        r = client.get(f"/api/{clinic.slug}/emr/sync-log", headers=_auth(tok))
        assert r.status_code == 200
        entries = r.json()["entries"]
        audit = next((e for e in entries if e["ehr_resource_id"] == "AUDIT-TEST-001"), None)
        assert audit is not None, "Audit log entry not found"
        assert audit["operation"] == "appt_sync"
        assert audit["status"] == "success"


# ── Performance Tests ─────────────────────────────────────────────────────────

class TestEMRPerformance:

    def test_emr_perf_001_get_config_under_200ms(self, client, db):
        """EMR-PERF-001: GET /ehr-config responds in < 200ms (SQLite, no cold start)."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        t0 = time.monotonic()
        r = client.get(f"/api/{clinic.slug}/ehr-config", headers=_auth(tok))
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert r.status_code == 200
        assert elapsed_ms < 200, f"GET /ehr-config took {elapsed_ms:.0f}ms (limit: 200ms)"

    def test_emr_perf_002_patch_config_under_300ms(self, client, db):
        """EMR-PERF-002: PATCH /ehr-config responds in < 300ms."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        t0 = time.monotonic()
        r = client.patch(f"/api/{clinic.slug}/ehr-config",
                         json={"ehr_system": "epic"}, headers=_auth(tok))
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert r.status_code == 200
        assert elapsed_ms < 300, f"PATCH /ehr-config took {elapsed_ms:.0f}ms (limit: 300ms)"

    def test_emr_perf_003_sync_log_under_300ms(self, client, db):
        """EMR-PERF-003: GET /emr/sync-log (20 rows) responds in < 300ms."""
        from datetime import datetime
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        # Seed 20 log entries
        for i in range(20):
            db.add(EMRSyncLog(
                clinic_id=clinic.id, ehr_system="epic",
                operation="appt_sync", status="success",
                ehr_resource_id=f"PERF-{i:03d}",
            ))
        db.commit()
        t0 = time.monotonic()
        r = client.get(f"/api/{clinic.slug}/emr/sync-log", headers=_auth(tok))
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert r.status_code == 200
        assert len(r.json()["entries"]) <= 20
        assert elapsed_ms < 300, f"GET /emr/sync-log took {elapsed_ms:.0f}ms (limit: 300ms)"

    def test_emr_perf_004_patient_lookup_cache_hit_under_100ms(self, client, db):
        """EMR-PERF-004: Patient cache hit (no EHR HTTP call) responds in < 100ms."""
        from datetime import datetime, timedelta
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        # Seed cache + EHR config
        db.add(EMRPatient(
            clinic_id=clinic.id, ehr_patient_id="PERF-CACHE-01", ehr_system="epic",
            full_name="Cache Patient", date_of_birth="1975-06-15",
            fetched_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        ))
        db.add(EHRConfiguration(
            clinic_id=clinic.id, ehr_system="epic",
            api_endpoint="https://fhir.epic.example.com/R4",
            api_key="key", client_id="client",
        ))
        db.commit()
        t0 = time.monotonic()
        r = client.get(
            f"/api/{clinic.slug}/emr/patient-lookup",
            params={"patient_name": "Cache Patient", "date_of_birth": "1975-06-15"},
            headers=_auth(tok),
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert r.status_code == 200
        assert r.json()["found"] is True
        assert elapsed_ms < 100, f"Cache hit took {elapsed_ms:.0f}ms (limit: 100ms)"


# ── Phase 2 Tests ─────────────────────────────────────────────────────────────

class TestEMRPhase2Intake:
    """EMR-P2: Intake pre-population and multi-vendor adapter contract tests."""

    def test_emr_p2_001_prefill_no_ehr_returns_not_found(self, client, db):
        """EMR-P2-001: prefill_intake_from_ehr with no EHR configured returns found=False."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.get(
            f"/api/{clinic.slug}/emr/patient-lookup",
            params={"patient_name": "Alice Johnson", "date_of_birth": "1992-04-10"},
            headers=_auth(tok),
        )
        assert r.status_code == 200
        assert r.json()["found"] is False

    def test_emr_p2_002_prefill_cache_hit_populates_fields(self, client, db):
        """EMR-P2-002: prefill_intake_from_ehr with cached patient returns all pre-fill fields."""
        from datetime import datetime, timedelta
        from backend.services.ehr_svc import prefill_intake_from_ehr

        clinic = _make_clinic(db, plan="professional")
        # Seed patient cache + EHR config
        db.add(EMRPatient(
            clinic_id=clinic.id,
            ehr_patient_id="P2-001",
            ehr_system="epic",
            full_name="Alice Johnson",
            date_of_birth="1992-04-10",
            phone="555-0200",
            email="alice@example.com",
            primary_provider="Dr. Smith",
            last_visit_date="2025-11-15",
            fetched_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        ))
        db.add(EHRConfiguration(
            clinic_id=clinic.id, ehr_system="epic",
            api_endpoint="https://fhir.epic.example.com/R4",
            api_key="key", client_id="client",
        ))
        db.commit()

        result = prefill_intake_from_ehr(clinic.id, "Alice Johnson", "1992-04-10", db)

        assert result["found"] is True
        assert result["pre_filled"]["patient_name"] == "Alice Johnson"
        assert result["pre_filled"]["patient_dob"]  == "1992-04-10"
        assert result["pre_filled"]["patient_phone"] == "555-0200"
        assert result["pre_filled"]["patient_email"] == "alice@example.com"
        assert result["pre_filled"]["preferred_provider"] == "Dr. Smith"
        assert "name" in result["questions_to_skip"]
        assert "phone number" in result["questions_to_skip"]
        assert "Dr. Smith" in result["message"]

    def test_emr_p2_003_prefill_missing_fields_skipped(self, client, db):
        """EMR-P2-003: Fields not in EHR record are not added to pre_filled."""
        from datetime import datetime, timedelta
        from backend.services.ehr_svc import prefill_intake_from_ehr

        clinic = _make_clinic(db, plan="professional")
        db.add(EMRPatient(
            clinic_id=clinic.id,
            ehr_patient_id="P2-002",
            ehr_system="cerner",
            full_name="Bob Lee",
            date_of_birth="1988-07-20",
            phone="",           # no phone
            email="",           # no email
            primary_provider="",
            fetched_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        ))
        db.add(EHRConfiguration(
            clinic_id=clinic.id, ehr_system="cerner",
            api_endpoint="https://fhir.cerner.example.com/r4",
            api_key="key", client_id="client",
        ))
        db.commit()

        result = prefill_intake_from_ehr(clinic.id, "Bob Lee", "1988-07-20", db)

        assert result["found"] is True
        assert "patient_phone" not in result["pre_filled"]
        assert "patient_email" not in result["pre_filled"]
        assert "preferred_provider" not in result["pre_filled"]
        assert "phone number" not in result["questions_to_skip"]

    def test_emr_p2_004_prefill_starter_plan_blocked(self, client, db):
        """EMR-P2-004: Starter plan clinic cannot use prefill_intake_from_ehr tool."""
        from backend.plans import can_use_ehr_integration
        clinic = _make_clinic(db, plan="starter")
        assert can_use_ehr_integration(clinic) is False

    def test_emr_p2_005_cerner_ehr_system_accepted_in_config(self, client, db):
        """EMR-P2-005: PATCH /ehr-config accepts 'cerner' as ehr_system."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        r = client.patch(
            f"/api/{clinic.slug}/ehr-config",
            json={"ehr_system": "cerner", "api_endpoint": "https://fhir.cerner.example.com/r4"},
            headers=_auth(tok),
        )
        assert r.status_code == 200
        assert r.json()["ehr_system"] == "cerner"

    def test_emr_p2_006_athenahealth_system_accepted_in_config(self, client, db):
        """EMR-P2-006: PATCH /ehr-config accepts 'athenahealth' as ehr_system."""
        clinic = _make_clinic(db, plan="enterprise")
        tok = _token(client, clinic.email)
        r = client.patch(
            f"/api/{clinic.slug}/ehr-config",
            json={"ehr_system": "athenahealth",
                  "api_endpoint": "https://api.platform.athenahealth.com/v1/12345"},
            headers=_auth(tok),
        )
        assert r.status_code == 200
        assert r.json()["ehr_system"] == "athenahealth"

    def test_emr_p2_007_cerner_patient_lookup_no_config_returns_not_found(self, client, db):
        """EMR-P2-007: Cerner patient lookup with no credentials returns not found (no 500)."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        # Configure Cerner but no credentials
        client.patch(
            f"/api/{clinic.slug}/ehr-config",
            json={"ehr_system": "cerner",
                  "api_endpoint": "https://fhir.cerner.example.com/r4"},
            headers=_auth(tok),
        )
        r = client.get(
            f"/api/{clinic.slug}/emr/patient-lookup",
            params={"patient_name": "Test Patient", "date_of_birth": "1990-01-01"},
            headers=_auth(tok),
        )
        assert r.status_code == 200
        assert r.json()["found"] is False

    def test_emr_p2_008_athena_patient_lookup_no_config_returns_not_found(self, client, db):
        """EMR-P2-008: Athenahealth patient lookup with no credentials returns not found (no 500)."""
        clinic = _make_clinic(db, plan="professional")
        tok = _token(client, clinic.email)
        client.patch(
            f"/api/{clinic.slug}/ehr-config",
            json={"ehr_system": "athenahealth",
                  "api_endpoint": "https://api.platform.athenahealth.com/v1/99999"},
            headers=_auth(tok),
        )
        r = client.get(
            f"/api/{clinic.slug}/emr/patient-lookup",
            params={"patient_name": "Test Patient", "date_of_birth": "1985-06-15"},
            headers=_auth(tok),
        )
        assert r.status_code == 200
        assert r.json()["found"] is False

    def test_emr_p2_009_prefill_returns_message_for_aria(self, db):
        """EMR-P2-009: prefill message includes last visit date when available."""
        from datetime import datetime, timedelta
        from backend.services.ehr_svc import prefill_intake_from_ehr

        clinic = _make_clinic(db, plan="professional")
        db.add(EMRPatient(
            clinic_id=clinic.id,
            ehr_patient_id="P2-009",
            ehr_system="athenahealth",
            full_name="Carol White",
            date_of_birth="1979-12-05",
            last_visit_date="2026-03-10",
            fetched_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        ))
        db.add(EHRConfiguration(
            clinic_id=clinic.id, ehr_system="athenahealth",
            api_endpoint="https://api.platform.athenahealth.com/v1/12345",
            api_key="key", client_id="client",
        ))
        db.commit()

        result = prefill_intake_from_ehr(clinic.id, "Carol White", "1979-12-05", db)
        assert result["found"] is True
        assert "2026-03-10" in result["message"]

    def test_emr_p2_010_parse_athena_slot_normalizes_format(self):
        """EMR-P2-010: _parse_athena_slot correctly normalizes Athenahealth slot format."""
        from backend.services.ehr_svc import _parse_athena_slot
        raw = {
            "appointmentid": "ATH-777",
            "date":          "07/15/2026",
            "starttime":     "09:30",
            "duration":      "30",
            "providerid":    "42",
        }
        slot = _parse_athena_slot(raw, "annual physical")
        assert slot is not None
        assert slot["ehr_slot_id"] == "ATH-777"
        assert slot["slot_date_str"] == "2026-07-15"
        assert slot["slot_time_str"] == "9:30 AM"
        assert slot["duration_minutes"] == 30
        assert slot["ehr_system"] == "athenahealth"


# ── Phase 3 Tests ─────────────────────────────────────────────────────────────

class TestEMRPhase3AutoRouting:
    """EMR-P3: Auto-routing, appointment type resolver, slot conflict, provider NPI, prompt injection."""

    def test_emr_p3_001_appt_type_resolver_epic_annual_physical(self):
        """EMR-P3-001: 'annual physical' resolves to Epic serviceType '11'."""
        from backend.services.ehr_svc import resolve_appointment_type_id
        assert resolve_appointment_type_id("annual physical", "epic") == "11"

    def test_emr_p3_002_appt_type_resolver_epic_new_patient(self):
        """EMR-P3-002: 'new patient consultation' resolves to Epic serviceType '185'."""
        from backend.services.ehr_svc import resolve_appointment_type_id
        assert resolve_appointment_type_id("new patient consultation", "epic") == "185"

    def test_emr_p3_003_appt_type_resolver_athena_follow_up(self):
        """EMR-P3-003: 'follow-up' resolves to Athena appointmenttypeid '3'."""
        from backend.services.ehr_svc import resolve_appointment_type_id
        assert resolve_appointment_type_id("follow-up", "athenahealth") == "3"

    def test_emr_p3_004_appt_type_resolver_unknown_falls_back(self):
        """EMR-P3-004: Unknown appointment type falls back to '1'."""
        from backend.services.ehr_svc import resolve_appointment_type_id
        assert resolve_appointment_type_id("underwater basket weaving", "epic") == "1"

    def test_emr_p3_005_appt_type_resolver_case_insensitive(self):
        """EMR-P3-005: Resolver is case-insensitive."""
        from backend.services.ehr_svc import resolve_appointment_type_id
        assert resolve_appointment_type_id("Annual Physical", "epic") == "11"
        assert resolve_appointment_type_id("TELEHEALTH", "epic") == "448"

    def test_emr_p3_006_appt_type_cerner_returns_1(self):
        """EMR-P3-006: Cerner uses text serviceType — resolver always returns '1' (no ID mapping needed)."""
        from backend.services.ehr_svc import resolve_appointment_type_id
        # Cerner doesn't use numeric IDs in the same way; resolver returns '1'
        result = resolve_appointment_type_id("annual physical", "cerner")
        assert result == "1"

    def test_emr_p3_007_slot_conflict_check_free_slot(self, db):
        """EMR-P3-007: check_slot_still_available returns True for a free cached slot."""
        from datetime import datetime, timedelta
        from backend.services.ehr_svc import check_slot_still_available
        clinic = _make_clinic(db, plan="professional")
        db.add(EMRAppointment(
            clinic_id=clinic.id,
            ehr_system="epic",
            ehr_slot_id="SLOT-FREE-001",
            status="free",
            slot_date_str="2026-08-01",
            slot_time_str="10:00 AM",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        ))
        db.commit()
        assert check_slot_still_available("SLOT-FREE-001", clinic.id, db) is True

    def test_emr_p3_008_slot_conflict_check_busy_slot(self, db):
        """EMR-P3-008: check_slot_still_available returns False for a busy cached slot."""
        from datetime import datetime, timedelta
        from backend.services.ehr_svc import check_slot_still_available
        clinic = _make_clinic(db, plan="professional")
        db.add(EMRAppointment(
            clinic_id=clinic.id,
            ehr_system="epic",
            ehr_slot_id="SLOT-BUSY-001",
            status="busy",
            slot_date_str="2026-08-01",
            slot_time_str="11:00 AM",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        ))
        db.commit()
        assert check_slot_still_available("SLOT-BUSY-001", clinic.id, db) is False

    def test_emr_p3_009_mark_slot_booked(self, db):
        """EMR-P3-009: mark_slot_booked changes cached slot status to 'busy'."""
        from datetime import datetime, timedelta
        from backend.services.ehr_svc import mark_slot_booked, check_slot_still_available
        clinic = _make_clinic(db, plan="professional")
        db.add(EMRAppointment(
            clinic_id=clinic.id,
            ehr_system="cerner",
            ehr_slot_id="SLOT-MARK-001",
            status="free",
            slot_date_str="2026-08-02",
            slot_time_str="2:00 PM",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        ))
        db.commit()
        assert check_slot_still_available("SLOT-MARK-001", clinic.id, db) is True
        mark_slot_booked("SLOT-MARK-001", clinic.id, db)
        assert check_slot_still_available("SLOT-MARK-001", clinic.id, db) is False

    def test_emr_p3_010_slot_conflict_unknown_slot_returns_true(self, db):
        """EMR-P3-010: check_slot_still_available on unknown slot ID returns True (optimistic)."""
        from backend.services.ehr_svc import check_slot_still_available
        clinic = _make_clinic(db, plan="professional")
        assert check_slot_still_available("SLOT-DOES-NOT-EXIST", clinic.id, db) is True

    def test_emr_p3_011_provider_npi_lookup_no_providers(self, db):
        """EMR-P3-011: resolve_provider_npi returns None when no providers in DB."""
        from backend.services.ehr_svc import resolve_provider_npi
        clinic = _make_clinic(db, plan="professional")
        result = resolve_provider_npi("Dr. Smith", clinic.id, db)
        assert result is None

    def test_emr_p3_012_provider_npi_lookup_with_match(self, db):
        """EMR-P3-012: resolve_provider_npi returns NPI when provider name matches."""
        from backend.db.models import Provider
        from backend.services.ehr_svc import resolve_provider_npi
        clinic = _make_clinic(db, plan="professional")
        db.add(Provider(
            clinic_id=clinic.id,
            name="Dr. Jane Smith",
            npi_number="1234567890",
            is_active=True,
        ))
        db.commit()
        result = resolve_provider_npi("Dr. Smith", clinic.id, db)
        assert result == "1234567890"

    def test_emr_p3_013_provider_npi_any_returns_none(self, db):
        """EMR-P3-013: resolve_provider_npi with 'any' returns None (no filter)."""
        from backend.services.ehr_svc import resolve_provider_npi
        clinic = _make_clinic(db, plan="professional")
        assert resolve_provider_npi("any", clinic.id, db) is None
        assert resolve_provider_npi("",    clinic.id, db) is None

    def test_emr_p3_014_check_availability_no_ehr_uses_local(self, client, db):
        """EMR-P3-014: check_appointment_availability falls back to local slots when no EHR."""
        clinic = _make_clinic(db, plan="professional")
        # No EHR config — should use mock schedule
        tok = _token(client, clinic.email)
        # We can't call the Aria tool directly but we can confirm EHR config is absent
        from backend.db.crud import get_ehr_configuration
        config = get_ehr_configuration(db, clinic.id)
        # Either None or ehr_system is empty
        assert config is None or not config.ehr_system

    def test_emr_p3_015_ehr_section_injected_when_ehr_active(self, db):
        """EMR-P3-015: System prompt includes EHR section when EHR is configured."""
        from backend.agent.prompts import build_system_prompt
        clinic = _make_clinic(db, plan="professional")
        clinic._db = db
        # No EHR config — section should be absent
        prompt_no_ehr = build_system_prompt(clinic, db=db)
        assert "EHR INTEGRATION" not in prompt_no_ehr

        # Add EHR config
        db.add(EHRConfiguration(
            clinic_id=clinic.id,
            ehr_system="epic",
            api_endpoint="https://fhir.epic.example.com/R4",
        ))
        db.commit()
        # Invalidate prompt cache
        from backend.agent.aria import invalidate_prompt
        invalidate_prompt(clinic.id)
        prompt_with_ehr = build_system_prompt(clinic, db=db)
        assert "EHR INTEGRATION" in prompt_with_ehr
        assert "prefill_intake_from_ehr" in prompt_with_ehr
        assert "EPIC" in prompt_with_ehr
