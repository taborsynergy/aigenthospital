"""
Production middleware — correlation IDs, structured request logging, circuit breaker.
"""
import time
import uuid
import logging
import threading
from enum import Enum
from collections import deque
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# ── Correlation ID context ────────────────────────────────────────────────────
# Stored in a ContextVar so it flows through async tasks without thread confusion.
_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return _request_id_var.get()


class CorrelationIDMiddleware:
    """
    Reads X-Request-ID from inbound request (or generates a UUID4).
    Echoes it on every response so clients can correlate logs.
    Sets the ContextVar so all downstream log calls can include it.
    """
    HEADER = b"x-request-id"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate request ID
        headers = dict(scope.get("headers", []))
        req_id = (headers.get(self.HEADER, b"") or b"").decode() or uuid.uuid4().hex
        token = _request_id_var.set(req_id)

        t_start = time.monotonic()

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                hdrs.append((self.HEADER, req_id.encode()))
                message = dict(message, headers=hdrs)
                # Structured access log
                method  = scope.get("method", "")
                path    = scope.get("path", "")
                status  = message.get("status", 0)
                elapsed = int((time.monotonic() - t_start) * 1000)
                logger.info(
                    "HTTP %s %s %d %dms request_id=%s",
                    method, path, status, elapsed, req_id,
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_var.reset(token)


# ── Circuit breaker ───────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED   = "closed"    # Normal — requests flow through
    OPEN     = "open"      # Tripped — fast-fail all requests
    HALF_OPEN = "half_open" # Probe — let one request through to test recovery


class CircuitBreaker:
    """
    Thread-safe circuit breaker for external service calls (EHR, email, SMS).

    States:
      CLOSED:    Normal operation. Failures are counted.
      OPEN:      Fast-fail. No calls made. Resets after `reset_timeout` seconds.
      HALF_OPEN: One probe call allowed. Success → CLOSED, failure → OPEN.

    Usage:
        cb = CircuitBreaker("epic_fhir", failure_threshold=5, reset_timeout=60)
        with cb:
            result = call_epic_api(...)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        success_threshold: int = 2,
    ):
        self.name              = name
        self.failure_threshold = failure_threshold
        self.reset_timeout     = reset_timeout
        self.success_threshold = success_threshold

        self._state            = CircuitState.CLOSED
        self._failure_count    = 0
        self._success_count    = 0
        self._last_failure_time: float = 0.0
        self._lock             = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.reset_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info("CircuitBreaker[%s] → HALF_OPEN", self.name)
            return self._state

    def __enter__(self):
        state = self.state
        if state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit breaker [{self.name}] is OPEN — "
                f"service unavailable, retry after {self.reset_timeout}s"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._on_success()
        elif not issubclass(exc_type, CircuitOpenError):
            self._on_failure(exc_val)
        return False  # don't suppress exceptions

    def _on_success(self):
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    logger.info("CircuitBreaker[%s] → CLOSED (recovered)", self.name)

    def _on_failure(self, exc):
        with self._lock:
            self._failure_count    += 1
            self._last_failure_time = time.monotonic()
            if (self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)
                    and self._failure_count >= self.failure_threshold):
                self._state = CircuitState.OPEN
                logger.error(
                    "CircuitBreaker[%s] → OPEN after %d failures. Last error: %s",
                    self.name, self._failure_count, exc,
                )

    def is_available(self) -> bool:
        return self.state != CircuitState.OPEN

    def status(self) -> dict:
        with self._lock:
            return {
                "name":           self.name,
                "state":          self._state.value,
                "failure_count":  self._failure_count,
                "last_failure_ago": (
                    round(time.monotonic() - self._last_failure_time, 1)
                    if self._last_failure_time else None
                ),
            }


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is OPEN and a call is attempted."""


# ── Pre-built circuit breakers for each external service ─────────────────────

_BREAKERS: dict[str, CircuitBreaker] = {}
_BREAKER_LOCK = threading.Lock()


def get_circuit_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Get or create a named circuit breaker (singleton per name)."""
    with _BREAKER_LOCK:
        if name not in _BREAKERS:
            _BREAKERS[name] = CircuitBreaker(name, **kwargs)
        return _BREAKERS[name]


def all_circuit_breaker_statuses() -> list[dict]:
    with _BREAKER_LOCK:
        return [cb.status() for cb in _BREAKERS.values()]


# ── PHI-safe log filter ───────────────────────────────────────────────────────

_PHI_FIELDS = frozenset({
    "patient_name", "patient_phone", "patient_email", "patient_dob",
    "first_name", "last_name", "date_of_birth", "dob", "ssn",
    "phone", "email", "address", "zip_code",
})


def redact_phi(data: dict) -> dict:
    """
    Return a copy of `data` with PHI fields replaced by '[REDACTED]'.
    Safe to call before logging — never mutates the original.
    """
    return {
        k: "[REDACTED]" if k.lower() in _PHI_FIELDS else v
        for k, v in data.items()
    }
