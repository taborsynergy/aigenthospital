"""Clinic timezone helpers.

Appointment timestamps (`appointment_ts`) are stored as naive datetimes in the
clinic's LOCAL wall-clock time (that's how the booking flow parses "Monday 10am").
Schedulers run in UTC, so any due-window math must be anchored to the clinic's
local "now" — otherwise reminders fire hours early/late for non-UTC clinics.
"""
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    ZoneInfo = None

# Map the human-readable clinic.timezone strings to IANA zones. Order matters
# only in that the first substring hit wins; all US zones are distinct here.
_TZ_MAP = (
    ("eastern", "America/New_York"),
    ("et",      "America/New_York"),
    ("central", "America/Chicago"),
    ("ct",      "America/Chicago"),
    ("mountain","America/Denver"),
    ("mt",      "America/Denver"),
    ("arizona", "America/Phoenix"),
    ("pacific", "America/Los_Angeles"),
    ("pt",      "America/Los_Angeles"),
    ("alaska",  "America/Anchorage"),
    ("hawaii",  "Pacific/Honolulu"),
    ("utc",     "UTC"),
)


def iana_zone(tz_str: str) -> str:
    """Best-effort map a clinic timezone label to an IANA zone (UTC if unknown)."""
    s = (tz_str or "").lower()
    for needle, zone in _TZ_MAP:
        if needle in s:
            return zone
    return "UTC"


def clinic_local_now(clinic) -> datetime:
    """The clinic's current local wall-clock time as a naive datetime.

    Falls back to UTC if zoneinfo is unavailable or the zone can't be resolved,
    so behavior is always defined and safe.
    """
    zone = iana_zone(getattr(clinic, "timezone", "") or "")
    if ZoneInfo is None:
        return datetime.utcnow()
    try:
        return datetime.now(ZoneInfo(zone)).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()
