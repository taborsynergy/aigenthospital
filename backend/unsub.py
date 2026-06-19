"""
Signed unsubscribe tokens for recall emails (CAN-SPAM).

A token encodes (clinic_id, email) and is HMAC-signed so the unsubscribe link
can't be forged. Stateless — no DB row needed to issue a link.
"""
import base64
import hashlib
import hmac
import json
from typing import Optional, Tuple

from backend.config import settings


def _key() -> bytes:
    return (settings.jwt_secret_key or settings.admin_password or "tabor-unsub").encode()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_unsub_token(clinic_id: int, email: str) -> str:
    payload = _b64e(json.dumps({"c": clinic_id, "e": email}, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_unsub_token(token: str) -> Optional[Tuple[int, str]]:
    """Return (clinic_id, email) if the token is valid, else None."""
    try:
        payload, sig = (token or "").split(".", 1)
        expected = _b64e(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_b64d(payload))
        return int(data["c"]), str(data["e"])
    except Exception:
        return None
