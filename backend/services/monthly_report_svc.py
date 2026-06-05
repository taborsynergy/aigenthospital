"""Monthly performance report generation for clinics."""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.models import Appointment, ChatSession, RecallLog


def generate_monthly_report(clinic_id: int, db: Session, year: int, month: int) -> dict:
    """
    Generate comprehensive monthly performance report for a clinic.
    Returns KPIs, trends, and recommendations.
    """
    # Date range for the month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    # ── Appointment metrics ──────────────────────────────────────────────────
    total_appts = db.query(func.count(Appointment.id)).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.created_at >= start_date,
        Appointment.created_at < end_date,
    ).scalar() or 0

    completed_appts = db.query(func.count(Appointment.id)).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.status == "completed",
        Appointment.created_at >= start_date,
        Appointment.created_at < end_date,
    ).scalar() or 0

    no_shows = db.query(func.count(Appointment.id)).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.status == "no_show",
        Appointment.created_at >= start_date,
        Appointment.created_at < end_date,
    ).scalar() or 0

    cancelled_appts = db.query(func.count(Appointment.id)).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.status == "cancelled",
        Appointment.created_at >= start_date,
        Appointment.created_at < end_date,
    ).scalar() or 0

    new_patients = db.query(func.count(Appointment.id)).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.is_new_patient.is_(True),
        Appointment.created_at >= start_date,
        Appointment.created_at < end_date,
    ).scalar() or 0

    # ── Chat engagement ──────────────────────────────────────────────────────
    total_chat_sessions = db.query(func.count(ChatSession.id)).filter(
        ChatSession.clinic_id == clinic_id,
        ChatSession.created_at >= start_date,
        ChatSession.created_at < end_date,
    ).scalar() or 0

    total_chat_messages = db.query(func.sum(func.length(ChatSession.history))).filter(
        ChatSession.clinic_id == clinic_id,
        ChatSession.created_at >= start_date,
        ChatSession.created_at < end_date,
    ).scalar() or 0

    # ── Recall campaign metrics ──────────────────────────────────────────────
    recall_sent = db.query(func.count(RecallLog.id)).filter(
        RecallLog.clinic_id == clinic_id,
        RecallLog.status == "sent",
        RecallLog.sent_at >= start_date,
        RecallLog.sent_at < end_date,
    ).scalar() or 0

    recall_booked = db.query(func.count(RecallLog.id)).filter(
        RecallLog.clinic_id == clinic_id,
        RecallLog.status == "booked",
        RecallLog.sent_at >= start_date,
        RecallLog.sent_at < end_date,
    ).scalar() or 0

    recall_opted_out = db.query(func.count(RecallLog.id)).filter(
        RecallLog.clinic_id == clinic_id,
        RecallLog.status == "opted_out",
        RecallLog.sent_at >= start_date,
        RecallLog.sent_at < end_date,
    ).scalar() or 0

    # ── Calculate KPIs ───────────────────────────────────────────────────────
    no_show_rate = (no_shows / total_appts * 100) if total_appts > 0 else 0
    completion_rate = (completed_appts / total_appts * 100) if total_appts > 0 else 0
    new_patient_rate = (new_patients / total_appts * 100) if total_appts > 0 else 0
    recall_conversion_rate = (recall_booked / recall_sent * 100) if recall_sent > 0 else 0

    # ── Recommendations ──────────────────────────────────────────────────────
    recommendations = []
    if no_show_rate > 20:
        recommendations.append("High no-show rate detected. Consider SMS reminders closer to appointment time.")
    if completion_rate < 80:
        recommendations.append("Completion rate below 80%. Review cancellation patterns.")
    if new_patient_rate < 10 and total_appts > 20:
        recommendations.append("Low new patient rate. Consider marketing initiatives.")
    if recall_conversion_rate < 15 and recall_sent > 20:
        recommendations.append("Low recall conversion. Optimize message timing or content.")

    month_name = datetime(year, month, 1).strftime("%B %Y")

    return {
        "period": month_name,
        "generated_at": datetime.utcnow().isoformat(),
        "appointments": {
            "total": total_appts,
            "completed": completed_appts,
            "no_shows": no_shows,
            "cancelled": cancelled_appts,
            "new_patients": new_patients,
        },
        "kpis": {
            "no_show_rate": round(no_show_rate, 1),
            "completion_rate": round(completion_rate, 1),
            "new_patient_rate": round(new_patient_rate, 1),
        },
        "chat": {
            "total_sessions": total_chat_sessions,
            "total_interactions": total_chat_messages or 0,
        },
        "recall": {
            "sent": recall_sent,
            "booked": recall_booked,
            "opted_out": recall_opted_out,
            "conversion_rate": round(recall_conversion_rate, 1),
        },
        "recommendations": recommendations,
        "summary": (
            f"This month: {total_appts} appointments ({completion_rate:.0f}% completed), "
            f"{no_show_rate:.0f}% no-show rate, {new_patient_rate:.0f}% new patients. "
            f"Chat: {total_chat_sessions} sessions. Recall: {recall_sent} sent with "
            f"{recall_conversion_rate:.0f}% conversion rate."
        ),
    }


def get_last_month_report(clinic_id: int, db: Session) -> dict:
    """Generate report for the previous calendar month."""
    today = datetime.utcnow()
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1
    return generate_monthly_report(clinic_id, db, year, month)
