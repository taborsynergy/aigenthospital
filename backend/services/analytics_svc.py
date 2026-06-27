"""
Analytics service — real-time clinic dashboard data from the database.

All functions return structured dicts Aria can format conversationally,
and the clinic portal REST endpoint can render as cards/tables.

Functions are read-only and have no side effects.
"""
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func

logger = logging.getLogger(__name__)

# ── Today's appointments ──────────────────────────────────────────────────────

def get_today_appointments(db: Session, clinic_id: int) -> dict:
    """All appointments scheduled for today with status breakdown and provider split."""
    from backend.db.models import Appointment

    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end   = datetime.combine(date.today(), datetime.max.time())

    appts = (
        db.query(Appointment)
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.appointment_ts.between(today_start, today_end),
            Appointment.status != "waitlist",
        )
        .order_by(Appointment.appointment_ts.asc())
        .all()
    )

    status_counts = Counter(a.status for a in appts)
    provider_counts = Counter(a.provider for a in appts if a.provider)
    type_counts = Counter(a.appointment_type for a in appts)

    no_shows = [
        {"name": a.patient_name, "time": a.appointment_datetime, "type": a.appointment_type}
        for a in appts if a.status == "no_show"
    ]

    return {
        "date":     date.today().strftime("%A, %B %d, %Y"),
        "total":    len(appts),
        "scheduled":  status_counts.get("scheduled", 0),
        "confirmed":  status_counts.get("confirmed", 0),
        "completed":  status_counts.get("completed", 0),
        "no_show":    status_counts.get("no_show", 0),
        "cancelled":  status_counts.get("cancelled", 0),
        "rescheduled": status_counts.get("rescheduled", 0),
        "by_provider": dict(provider_counts.most_common(5)),
        "by_type":     dict(type_counts.most_common(5)),
        "no_show_details": no_shows[:5],
    }


# ── Weekly summary ────────────────────────────────────────────────────────────

def get_weekly_summary(db: Session, clinic_id: int) -> dict:
    """Appointments for the current week (Mon → today), grouped by day."""
    from backend.db.models import Appointment

    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    week_start = datetime.combine(monday, datetime.min.time())
    week_end   = datetime.combine(today, datetime.max.time())

    appts = (
        db.query(Appointment)
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.appointment_ts.between(week_start, week_end),
            Appointment.status.notin_(["cancelled", "waitlist"]),
        )
        .all()
    )

    by_day: dict[str, int] = defaultdict(int)
    for a in appts:
        if a.appointment_ts:
            day = a.appointment_ts.strftime("%A")
            by_day[day] += 1

    # Peak day
    peak_day = max(by_day, key=by_day.get) if by_day else "N/A"
    peak_count = by_day.get(peak_day, 0)

    return {
        "week_start":   monday.strftime("%B %d"),
        "week_end":     today.strftime("%B %d, %Y"),
        "total":        len(appts),
        "by_day":       dict(by_day),
        "peak_day":     peak_day,
        "peak_count":   peak_count,
        "daily_average": round(len(appts) / max(today.weekday() + 1, 1), 1),
    }


# ── Monthly summary ───────────────────────────────────────────────────────────

def get_monthly_summary(db: Session, clinic_id: int) -> dict:
    """Appointments for the current calendar month with key KPIs."""
    from backend.db.models import Appointment
    from sqlalchemy import extract

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    appts = (
        db.query(Appointment)
        .filter(
            Appointment.clinic_id == clinic_id,
            extract("year",  Appointment.appointment_ts) == now.year,
            extract("month", Appointment.appointment_ts) == now.month,
        )
        .all()
    )

    active   = [a for a in appts if a.status not in ("cancelled", "waitlist")]
    cancelled = [a for a in appts if a.status == "cancelled"]
    no_shows  = [a for a in appts if a.status == "no_show"]
    new_pats  = [a for a in active if a.is_new_patient]

    cancel_rate = round(len(cancelled) / max(len(appts), 1) * 100, 1)
    noshow_rate = round(len(no_shows)  / max(len(active), 1) * 100, 1)
    new_pat_rate = round(len(new_pats) / max(len(active), 1) * 100, 1)

    type_counts = Counter(a.appointment_type for a in active)
    prov_counts = Counter(a.provider for a in active if a.provider)

    return {
        "month":            now.strftime("%B %Y"),
        "total":            len(appts),
        "active":           len(active),
        "cancelled":        len(cancelled),
        "no_shows":         len(no_shows),
        "new_patients":     len(new_pats),
        "cancellation_rate": f"{cancel_rate}%",
        "no_show_rate":      f"{noshow_rate}%",
        "new_patient_rate":  f"{new_pat_rate}%",
        "top_appointment_types": dict(type_counts.most_common(5)),
        "top_providers":         dict(prov_counts.most_common(5)),
    }


# ── No-shows ──────────────────────────────────────────────────────────────────

def get_no_shows(db: Session, clinic_id: int, days_back: int = 7) -> dict:
    """Recent no-shows with patient names — used for follow-up outreach."""
    from backend.db.models import Appointment

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_back)
    rows = (
        db.query(Appointment)
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.status == "no_show",
            Appointment.appointment_ts >= since,
        )
        .order_by(Appointment.appointment_ts.desc())
        .limit(20)
        .all()
    )

    return {
        "period":  f"Last {days_back} days",
        "count":   len(rows),
        "patients": [
            {
                "name":  a.patient_name,
                "phone": a.patient_phone,
                "time":  a.appointment_datetime,
                "type":  a.appointment_type,
            }
            for a in rows
        ],
    }


# ── Provider breakdown ────────────────────────────────────────────────────────

def get_provider_breakdown(db: Session, clinic_id: int) -> dict:
    """Appointments per provider this month — helps with workload balancing."""
    from backend.db.models import Appointment
    from sqlalchemy import extract

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = (
        db.query(
            Appointment.provider,
            func.count(Appointment.id).label("count"),
        )
        .filter(
            Appointment.clinic_id == clinic_id,
            Appointment.status.notin_(["cancelled", "waitlist"]),
            extract("year",  Appointment.appointment_ts) == now.year,
            extract("month", Appointment.appointment_ts) == now.month,
        )
        .group_by(Appointment.provider)
        .order_by(func.count(Appointment.id).desc())
        .all()
    )

    providers = [{"provider": r.provider or "Unassigned", "appointments": r.count} for r in rows]
    total = sum(r["appointments"] for r in providers)
    for p in providers:
        p["share"] = f"{round(p['appointments'] / max(total, 1) * 100)}%"

    return {
        "month":     now.strftime("%B %Y"),
        "total":     total,
        "providers": providers,
    }


# ── Conversation stats ────────────────────────────────────────────────────────

def get_conversation_stats(db: Session, clinic_id: int, clinic) -> dict:
    """AI chat usage this month vs. plan limit."""
    from backend.db.crud import get_usage_this_month
    from backend.plans import monthly_conversation_limit

    used  = get_usage_this_month(db, clinic_id)
    limit = monthly_conversation_limit(clinic)
    remaining = None if limit is None else max(0, limit - used)
    pct_used  = None if limit is None else round(used / max(limit, 1) * 100, 1)

    # Daily average this month
    days_in_month = date.today().day
    daily_avg = round(used / max(days_in_month, 1), 1)

    return {
        "sessions_this_month": used,
        "plan_limit":          limit,
        "sessions_remaining":  remaining,
        "percent_used":        f"{pct_used}%" if pct_used is not None else "Unlimited",
        "daily_average":       daily_avg,
        "plan":                getattr(clinic, "plan", "unknown"),
    }


# ── Recall campaign performance ───────────────────────────────────────────────

def get_recall_performance(db: Session, clinic_id: int) -> dict:
    """Recall campaign performance across all campaigns for this clinic."""
    from backend.db.crud import get_recall_stats, list_recall_campaigns

    campaigns = list_recall_campaigns(db, clinic_id)
    if not campaigns:
        return {"campaigns": 0, "total_sent": 0, "booked": 0, "opted_out": 0}

    total_sent = total_booked = total_opted_out = total_failed = 0
    campaign_details = []

    for c in campaigns:
        stats = get_recall_stats(db, c.id)
        total_sent    += stats.get("sent", 0)
        total_booked  += stats.get("booked", 0)
        total_opted_out += stats.get("opted_out", 0)
        total_failed  += stats.get("failed", 0)
        campaign_details.append({
            "name":       c.name,
            "visit_type": c.visit_type,
            "interval":   f"{c.interval_months} months",
            "active":     c.is_active,
            **stats,
        })

    book_rate = round(total_booked / max(total_sent, 1) * 100, 1)

    return {
        "campaigns":    len(campaigns),
        "total_sent":   total_sent,
        "booked":       total_booked,
        "opted_out":    total_opted_out,
        "failed":       total_failed,
        "booking_rate": f"{book_rate}%",
        "details":      campaign_details,
    }


# ── Full dashboard ────────────────────────────────────────────────────────────

def get_full_dashboard(db: Session, clinic_id: int, clinic) -> dict:
    """All analytics in a single call for the clinic portal dashboard tab."""
    return {
        "today":     get_today_appointments(db, clinic_id),
        "weekly":    get_weekly_summary(db, clinic_id),
        "monthly":   get_monthly_summary(db, clinic_id),
        "no_shows":  get_no_shows(db, clinic_id, days_back=7),
        "providers": get_provider_breakdown(db, clinic_id),
        "conversations": get_conversation_stats(db, clinic_id, clinic),
        "recall":    get_recall_performance(db, clinic_id),
    }


# ── Aria-friendly text summaries ──────────────────────────────────────────────

def format_for_aria(report_type: str, data: dict) -> str:
    """Convert analytics data dict into a natural language summary for Aria."""

    if report_type == "today_appointments":
        total = data["total"]
        if total == 0:
            return f"No appointments are scheduled for today, {data['date']}."
        parts = [f"Today ({data['date']}) has {total} appointment{'s' if total != 1 else ''}"]
        by_status = []
        if data["confirmed"]:
            by_status.append(f"{data['confirmed']} confirmed")
        if data["scheduled"]:
            by_status.append(f"{data['scheduled']} pending confirmation")
        if data["completed"]:
            by_status.append(f"{data['completed']} completed")
        if data["no_show"]:
            by_status.append(f"{data['no_show']} no-show")
        if by_status:
            parts.append("(" + ", ".join(by_status) + ")")
        if data["by_provider"]:
            prov_str = ", ".join(f"{p} ×{c}" for p, c in data["by_provider"].items())
            parts.append(f"Providers: {prov_str}")
        return ". ".join(parts) + "."

    if report_type == "no_shows":
        count = data["count"]
        if count == 0:
            return f"No no-shows in the {data['period'].lower()}."
        names = [p["name"] for p in data["patients"][:3]]
        msg = f"{count} no-show{'s' if count != 1 else ''} in the {data['period'].lower()}: {', '.join(names)}"
        if count > 3:
            msg += f" and {count - 3} more"
        msg += ". Would you like me to notify staff to follow up?"
        return msg

    if report_type == "weekly_summary":
        total = data["total"]
        if total == 0:
            return "No appointments recorded this week yet."
        return (
            f"This week ({data['week_start']}–{data['week_end']}): {total} appointments, "
            f"averaging {data['daily_average']} per day. "
            f"Busiest day: {data['peak_day']} ({data['peak_count']} appointments)."
        )

    if report_type == "monthly_summary":
        return (
            f"{data['month']}: {data['active']} appointments "
            f"({data['new_patients']} new patients, {data['new_patient_rate']} new patient rate). "
            f"Cancellation rate: {data['cancellation_rate']}. "
            f"No-show rate: {data['no_show_rate']}."
        )

    if report_type == "conversations":
        used  = data["sessions_this_month"]
        limit = data["plan_limit"]
        if limit is None:
            return f"This month: {used} patient conversations (unlimited plan). Daily average: {data['daily_average']}."
        remaining = data["sessions_remaining"]
        return (
            f"This month: {used} of {limit} patient conversations used "
            f"({data['percent_used']} used, {remaining} remaining). "
            f"Daily average: {data['daily_average']}."
        )

    if report_type == "provider_breakdown":
        if not data["providers"]:
            return "No provider data available this month."
        top = data["providers"][0]
        return (
            f"{data['month']} provider summary: {data['total']} total appointments. "
            f"Top provider: {top['provider']} ({top['appointments']} appointments, {top['share']}). "
            + " | ".join(f"{p['provider']}: {p['appointments']}" for p in data["providers"][1:4])
        )

    if report_type == "recall_performance":
        if data["campaigns"] == 0:
            return "No recall campaigns configured yet."
        return (
            f"{data['campaigns']} recall campaign{'s' if data['campaigns'] != 1 else ''}: "
            f"{data['total_sent']} messages sent, "
            f"{data['booked']} bookings ({data['booking_rate']} booking rate), "
            f"{data['opted_out']} opted out."
        )

    return str(data)
