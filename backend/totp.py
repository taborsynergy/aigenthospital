"""RFC 6238 TOTP (time-based one-time passwords) — stdlib only, no extra deps.

Used for optional 2FA on clinic-user (staff) login. Compatible with Google
Authenticator / Authy / 1Password via the otpauth:// provisioning URI.
"""
import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote


def generate_secret() -> str:
    """A new random base32 TOTP secret."""
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32 + pad, casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def now_code(secret_b32: str, step: int = 30, t: float = None) -> str:
    """Current TOTP code for a secret (used in tests / display)."""
    if t is None:
        t = time.time()
    return _hotp(secret_b32, int(t // step))


def verify(secret_b32: str, code: str, step: int = 30, window: int = 1, t: float = None) -> bool:
    """True if `code` is valid now (±`window` steps to tolerate clock drift)."""
    if not secret_b32 or not code:
        return False
    code = str(code).strip()
    if not code.isdigit():
        return False
    if t is None:
        t = time.time()
    counter = int(t // step)
    for w in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + w), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account: str, issuer: str = "Tabor Synergy") -> str:
    """otpauth:// URI for QR enrollment in an authenticator app."""
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}"
            f"?secret={secret_b32}&issuer={quote(issuer)}&digits=6&period=30")
