"""
Mock Practice Management System (Athenahealth / Dentrix / eClinicalWorks stand-in).
Returns realistic appointment slots and patient records for any specialty.
"""
from datetime import date, datetime, timedelta
from typing import Optional
import random
import uuid

from backend.config import settings

def _parse_providers(clinic=None) -> list[dict]:
    raw = (clinic.providers if clinic and clinic.providers else None) or settings.providers
    providers = []
    for i, p in enumerate(raw.split(",")):
        p = p.strip()
        if p:
            providers.append({"id": f"p{i+1}", "name": p})
    return providers or [{"id": "p1", "name": "Dr. Provider"}]


def _clinic_prefix(clinic=None) -> str:
    name = (clinic.name if clinic else None) or settings.clinic_name
    return name[:3].upper().replace(" ", "")


def _clinic_address(clinic=None) -> str:
    return (clinic.address if clinic else None) or settings.address or ""


def _cancellation_policy(clinic=None) -> str:
    return (clinic.cancellation_policy if clinic else None) or settings.cancellation_policy


MOCK_PATIENTS = {
    ("Jane Smith", "1985-04-12"): {
        "id": "pt_001",
        "name": "Jane Smith",
        "dob": "1985-04-12",
        "phone": "(512) 555-0201",
        "email": "jane.smith@email.com",
        "balance": 125.00,
        "last_visit": "2025-11-10",
        "insurance": "Aetna PPO",
        "preferred_provider": "",
    },
    ("Robert Johnson", "1972-08-30"): {
        "id": "pt_002",
        "name": "Robert Johnson",
        "dob": "1972-08-30",
        "phone": "(512) 555-0342",
        "email": "rjohnson@email.com",
        "balance": 0.00,
        "last_visit": "2025-09-05",
        "insurance": "BCBS PPO",
        "preferred_provider": "",
    },
}


def _slot_times() -> list[str]:
    return ["8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM",
            "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"]


def check_availability(
    appointment_type: str,
    date_range_start: Optional[str] = None,
    date_range_end: Optional[str] = None,
    provider: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    clinic=None,
) -> dict:
    providers = _parse_providers(clinic)
    start = (
        datetime.strptime(date_range_start, "%Y-%m-%d").date()
        if date_range_start
        else date.today() + timedelta(days=1)
    )
    end = (
        datetime.strptime(date_range_end, "%Y-%m-%d").date()
        if date_range_end
        else start + timedelta(days=6)
    )

    if provider and provider.lower() != "any":
        available = [p for p in providers if provider.lower() in p["name"].lower()]
        if not available:
            available = providers
    else:
        available = providers

    slots = []
    current = start
    while current <= end and len(slots) < 10:
        if current.weekday() < 5:  # Mon–Fri
            times = random.sample(_slot_times(), k=random.randint(2, 5))
            for time in sorted(times):
                prov = random.choice(available)
                slots.append({
                    "date": current.isoformat(),
                    "day": current.strftime("%A, %B %d"),
                    "time": time,
                    "provider": prov["name"],
                    "duration_minutes": duration_minutes or 30,
                    "slot_id": f"slot_{uuid.uuid4().hex[:8]}",
                })
        current += timedelta(days=1)

    return {"available_slots": slots[:8], "appointment_type": appointment_type}


def book_appointment(
    patient_name: str,
    appointment_type: str,
    datetime_str: str,
    provider: Optional[str] = None,
    patient_phone: Optional[str] = None,
    patient_email: Optional[str] = None,
    patient_dob: Optional[str] = None,
    is_new_patient: bool = False,
    chief_complaint: Optional[str] = None,
    clinic=None,
) -> dict:
    providers = _parse_providers(clinic)
    chosen_provider = provider or providers[0]["name"]
    confirmation_number = f"{_clinic_prefix(clinic)}-{random.randint(10000, 99999)}"
    return {
        "success": True,
        "confirmation_number": confirmation_number,
        "patient_name": patient_name,
        "appointment_type": appointment_type,
        "datetime": datetime_str,
        "provider": chosen_provider,
        "location": _clinic_address(clinic),
        "prep_instructions": (
            "Please arrive 15 minutes early and bring your insurance card and a photo ID."
            if is_new_patient
            else "Please arrive 5 minutes early with your insurance card."
        ),
        "reminder_sent": True,
    }


def reschedule_appointment(
    patient_name: str,
    new_datetime: str,
    patient_dob: Optional[str] = None,
    current_appointment_date: Optional[str] = None,
    reason: Optional[str] = None,
    clinic=None,
) -> dict:
    return {
        "success": True,
        "confirmation_number": f"{_clinic_prefix(clinic)}-{random.randint(10000, 99999)}",
        "patient_name": patient_name,
        "new_datetime": new_datetime,
        "message": "Appointment rescheduled successfully.",
    }


def cancel_appointment(
    patient_name: str,
    appointment_date: str,
    patient_dob: Optional[str] = None,
    reason: Optional[str] = None,
    clinic=None,
) -> dict:
    return {
        "success": True,
        "patient_name": patient_name,
        "cancelled_date": appointment_date,
        "cancellation_policy": _cancellation_policy(clinic),
        "message": "Appointment cancelled. We hope to see you again soon.",
    }


def get_patient_balance(
    patient_name: str,
    patient_dob: str,
    last_four_ssn: Optional[str] = None,
    patient_address: Optional[str] = None,
) -> dict:
    key = (patient_name, patient_dob)
    patient = MOCK_PATIENTS.get(key)
    if patient:
        return {
            "found": True,
            "patient_name": patient["name"],
            "balance": patient["balance"],
            "last_visit": patient["last_visit"],
            "message": (
                f"Outstanding balance of ${patient['balance']:.2f}."
                if patient["balance"] > 0
                else "No outstanding balance on file."
            ),
        }
    return {
        "found": False,
        "message": "Could not locate an account with that name and date of birth. Please verify the details.",
    }


def add_to_waitlist(
    patient_name: str,
    patient_phone: str,
    appointment_type: str,
    preferred_provider: Optional[str] = None,
    earliest_available: Optional[str] = None,
    clinic=None,
) -> dict:
    return {
        "success": True,
        "patient_name": patient_name,
        "position": random.randint(1, 4),
        "message": (
            f"{patient_name} has been added to our waitlist. "
            f"We'll contact {patient_phone} the moment a slot opens up."
        ),
    }
