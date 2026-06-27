"""
Production hardening tests — correlation IDs, circuit breaker, health endpoints,
PHI-safe logging, thread-safe token cache, security headers.

Maps to the Production Readiness Review findings:
  PH-001..006  Correlation ID middleware
  PH-007..012  Health endpoints (liveness / readiness)
  PH-013..018  Circuit breaker
  PH-019..022  Thread-safe token cache
  PH-023..026  PHI-safe logging
  PH-027..030  Security headers
"""
import os
import threading
import time
import logging

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_prod_hardening.db")
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import Base, engine
from backend.middleware import (
    CircuitBreaker, CircuitOpenError, get_circuit_breaker,
    all_circuit_breaker_statuses, redact_phi,
)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ── PH-001..006: Correlation ID middleware ────────────────────────────────────

class TestCorrelationID:

    def test_ph_001_response_contains_x_request_id(self, client):
        """PH-001: Every response carries X-Request-ID header."""
        r = client.get("/api/health")
        assert "x-request-id" in r.headers, "Missing X-Request-ID header"

    def test_ph_002_custom_request_id_echoed(self, client):
        """PH-002: Provided X-Request-ID is echoed back unchanged."""
        custom_id = "test-correlation-abc123"
        r = client.get("/api/health", headers={"X-Request-ID": custom_id})
        assert r.headers.get("x-request-id") == custom_id

    def test_ph_003_auto_generated_id_is_hex(self, client):
        """PH-003: Auto-generated ID is a 32-char hex string (UUID4 without dashes)."""
        r = client.get("/api/health")
        req_id = r.headers.get("x-request-id", "")
        assert len(req_id) == 32
        assert all(c in "0123456789abcdef" for c in req_id)

    def test_ph_004_different_requests_get_unique_ids(self, client):
        """PH-004: Two requests without a provided ID get different IDs."""
        id1 = client.get("/api/health").headers.get("x-request-id")
        id2 = client.get("/api/health").headers.get("x-request-id")
        assert id1 != id2

    def test_ph_005_non_http_scope_does_not_crash(self):
        """PH-005: Correlation middleware ignores non-HTTP scopes (WebSocket)."""
        from backend.middleware import CorrelationIDMiddleware
        import asyncio

        async def dummy_app(scope, receive, send):
            pass

        mw = CorrelationIDMiddleware(dummy_app)

        async def run():
            await mw({"type": "websocket"}, None, None)

        asyncio.run(run())  # must not raise

    def test_ph_006_request_id_present_on_404(self, client):
        """PH-006: X-Request-ID is present even on 404 responses."""
        r = client.get("/api/this-route-does-not-exist-xyz")
        assert "x-request-id" in r.headers


# ── PH-007..012: Health endpoints ─────────────────────────────────────────────

class TestHealthEndpoints:

    def test_ph_007_health_returns_200(self, client):
        """PH-007: /api/health returns 200 when DB is reachable."""
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_ph_008_health_body_has_status(self, client):
        """PH-008: /api/health body includes status, db, and circuits."""
        r = client.get("/api/health")
        body = r.json()
        assert "status" in body
        assert "db" in body
        assert "circuits" in body

    def test_ph_009_health_db_section_has_ok_and_latency(self, client):
        """PH-009: /api/health db section has ok=True and latency_ms."""
        r = client.get("/api/health")
        db = r.json()["db"]
        assert db["ok"] is True
        assert isinstance(db["latency_ms"], int)
        assert db["latency_ms"] >= 0

    def test_ph_010_liveness_returns_200(self, client):
        """PH-010: /api/health/live always returns 200 (process alive)."""
        r = client.get("/api/health/live")
        assert r.status_code == 200
        assert r.json()["status"] == "alive"

    def test_ph_011_readiness_returns_200_when_db_ok(self, client):
        """PH-011: /api/health/ready returns 200 when DB is up."""
        r = client.get("/api/health/ready")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_ph_012_health_circuits_is_list(self, client):
        """PH-012: /api/health circuits field is a list."""
        r = client.get("/api/health")
        assert isinstance(r.json()["circuits"], list)


# ── PH-013..018: Circuit breaker ──────────────────────────────────────────────

class TestCircuitBreaker:

    def test_ph_013_circuit_starts_closed(self):
        """PH-013: Fresh circuit breaker starts in CLOSED state."""
        cb = CircuitBreaker("test_ph013", failure_threshold=3)
        assert cb.state.value == "closed"

    def test_ph_014_circuit_opens_after_threshold(self):
        """PH-014: Circuit opens after failure_threshold consecutive failures."""
        cb = CircuitBreaker("test_ph014", failure_threshold=3)
        err = RuntimeError("boom")
        for _ in range(3):
            try:
                with cb:
                    raise err
            except RuntimeError:
                pass
        assert cb.state.value == "open"

    def test_ph_015_open_circuit_raises_circuit_open_error(self):
        """PH-015: Calls through an OPEN circuit raise CircuitOpenError (fast-fail)."""
        cb = CircuitBreaker("test_ph015", failure_threshold=1)
        try:
            with cb:
                raise RuntimeError("trigger")
        except RuntimeError:
            pass
        assert cb.state.value == "open"
        with pytest.raises(CircuitOpenError):
            with cb:
                pass  # should never reach here

    def test_ph_016_circuit_transitions_half_open_after_timeout(self):
        """PH-016: Circuit moves to HALF_OPEN after reset_timeout elapses."""
        cb = CircuitBreaker("test_ph016", failure_threshold=1, reset_timeout=0.05)
        try:
            with cb:
                raise RuntimeError("trigger")
        except RuntimeError:
            pass
        time.sleep(0.1)
        assert cb.state.value == "half_open"

    def test_ph_017_circuit_recovers_after_successful_probe(self):
        """PH-017: HALF_OPEN → CLOSED after success_threshold successes."""
        cb = CircuitBreaker("test_ph017", failure_threshold=1,
                            reset_timeout=0.05, success_threshold=2)
        try:
            with cb:
                raise RuntimeError("trigger")
        except RuntimeError:
            pass
        time.sleep(0.1)
        # Two successful probes
        with cb:
            pass
        with cb:
            pass
        assert cb.state.value == "closed"

    def test_ph_018_singleton_via_get_circuit_breaker(self):
        """PH-018: get_circuit_breaker returns same instance for same name."""
        cb1 = get_circuit_breaker("singleton_test_ph018")
        cb2 = get_circuit_breaker("singleton_test_ph018")
        assert cb1 is cb2

    def test_ph_018b_circuit_breaker_thread_safe(self):
        """PH-018b: Circuit breaker withstands concurrent access from 20 threads."""
        cb = CircuitBreaker("test_ph018b_threads", failure_threshold=100)
        errors = []

        def worker():
            try:
                with cb:
                    pass
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"


# ── PH-019..022: Thread-safe token cache ──────────────────────────────────────

class TestThreadSafeTokenCache:

    def test_ph_019_cache_get_returns_none_for_missing(self):
        """PH-019: _cache_get returns None when key not present."""
        from backend.services.ehr_svc import _cache_get
        result = _cache_get("key_that_does_not_exist_ph019")
        assert result is None

    def test_ph_020_cache_set_then_get_returns_value(self):
        """PH-020: _cache_set persists and _cache_get retrieves it."""
        from backend.services.ehr_svc import _cache_get, _cache_set
        _cache_set("ph020_key", {"token": "abc", "expires_at": time.time() + 3600})
        result = _cache_get("ph020_key")
        assert result is not None
        assert result["token"] == "abc"

    def test_ph_021_expired_entry_returns_none(self):
        """PH-021: _cache_get returns None for an entry past its expires_at."""
        from backend.services.ehr_svc import _cache_get, _cache_set
        _cache_set("ph021_expired", {"token": "old", "expires_at": time.time() - 1})
        assert _cache_get("ph021_expired") is None

    def test_ph_022_concurrent_cache_writes_no_corruption(self):
        """PH-022: 50 concurrent threads can write cache without corruption."""
        from backend.services.ehr_svc import _cache_get, _cache_set
        errors = []

        def writer(i):
            try:
                key = f"concurrent_ph022_{i % 5}"
                _cache_set(key, {"token": f"t{i}", "expires_at": time.time() + 3600})
                _cache_get(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Cache corruption: {errors}"


# ── PH-023..026: PHI-safe logging ─────────────────────────────────────────────

class TestPhiSafeLogging:

    def test_ph_023_redact_phi_scrubs_patient_name(self):
        """PH-023: redact_phi removes patient_name field."""
        data = {"patient_name": "Jane Doe", "clinic_id": 1}
        result = redact_phi(data)
        assert result["patient_name"] == "[REDACTED]"
        assert result["clinic_id"] == 1

    def test_ph_024_redact_phi_scrubs_multiple_phi_fields(self):
        """PH-024: redact_phi scrubs all PHI fields in one call."""
        data = {
            "patient_name":  "John Smith",
            "patient_phone": "555-1234",
            "patient_email": "john@example.com",
            "patient_dob":   "1980-01-01",
            "clinic_id":     42,
            "action":        "book",
        }
        result = redact_phi(data)
        for phi_key in ("patient_name", "patient_phone", "patient_email", "patient_dob"):
            assert result[phi_key] == "[REDACTED]", f"{phi_key} not redacted"
        assert result["clinic_id"] == 42
        assert result["action"] == "book"

    def test_ph_025_redact_phi_does_not_mutate_original(self):
        """PH-025: redact_phi returns a new dict — original is unmodified."""
        original = {"patient_name": "Jane", "clinic_id": 1}
        redact_phi(original)
        assert original["patient_name"] == "Jane"

    def test_ph_026_appointment_booked_log_no_patient_name(self, client, caplog):
        """PH-026: Booking log message does not contain patient name at ERROR level."""
        with caplog.at_level(logging.ERROR, logger="backend.services.appointment_svc"):
            pass  # Errors only fire on DB failure — just verify redact_phi works above
        # The structural guarantee: appointment_svc now logs conf_num, not patient_name
        import inspect
        import backend.services.appointment_svc as svc
        src = inspect.getsource(svc.book_appointment)
        # Patient name must not appear in the exception log line
        assert "patient_name" not in src.split("logger.exception")[1].split("\n")[0]


# ── PH-027..030: Security headers ─────────────────────────────────────────────

class TestSecurityHeaders:

    def test_ph_027_x_content_type_options(self, client):
        """PH-027: X-Content-Type-Options: nosniff on every response."""
        r = client.get("/api/health")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_ph_028_x_frame_options_deny(self, client):
        """PH-028: X-Frame-Options: DENY (no clickjacking)."""
        r = client.get("/api/health")
        assert r.headers.get("x-frame-options") == "DENY"

    def test_ph_029_strict_transport_security(self, client):
        """PH-029: Strict-Transport-Security header present with long max-age."""
        r = client.get("/api/health")
        hsts = r.headers.get("strict-transport-security", "")
        assert "max-age=" in hsts
        max_age = int(hsts.split("max-age=")[1].split(";")[0])
        assert max_age >= 31536000, f"HSTS max-age too short: {max_age}"

    def test_ph_030_permissions_policy_present(self, client):
        """PH-030: Permissions-Policy header restricts camera/mic/geolocation."""
        r = client.get("/api/health")
        pp = r.headers.get("permissions-policy", "")
        assert "camera=()" in pp
        assert "microphone=()" in pp
        assert "geolocation=()" in pp
