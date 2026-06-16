"""
Pydantic schemas for request validation.
"""
from pydantic import BaseModel, field_validator
from typing import Optional


class ClinicProfileUpdate(BaseModel):
    """
    Clinic self-edit profile fields.
    Staff can update their own clinic's profile info (not admin-only).
    """
    name: Optional[str] = None
    agent_name: Optional[str] = None   # AI assistant name — plan-gated in the route
    specialty: Optional[str] = None
    address: Optional[str] = None
    city_state: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    office_hours: Optional[str] = None
    providers: Optional[str] = None
    services_offered: Optional[str] = None
    insurance_accepted: Optional[str] = None
    cancellation_policy: Optional[str] = None
    after_hours_protocol: Optional[str] = None
    timezone: Optional[str] = None
    hipaa_verify_method: Optional[str] = None
    escalation_contact: Optional[str] = None
    pms_system: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) < 2 or len(v) > 100:
                raise ValueError("Clinic name must be 2–100 characters.")
        return v

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) < 2 or len(v) > 40:
                raise ValueError("Agent name must be 2–40 characters.")
        return v

    @field_validator("specialty")
    @classmethod
    def validate_specialty(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) < 2 or len(v) > 50:
                raise ValueError("Specialty must be 2–50 characters.")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if v is not None:
            v = v.strip()
            # Allow formats: (555) 123-4567, 555-123-4567, 5551234567, +1-555-123-4567
            if not (len(v) >= 10 and any(c.isdigit() for c in v)):
                raise ValueError("Phone number must contain at least 10 digits.")
        return v

    @field_validator("website")
    @classmethod
    def validate_website(cls, v):
        if v is not None and v.strip():
            v = v.strip()
            if not v.startswith(("http://", "https://")):
                raise ValueError("Website must start with http:// or https://")
            if len(v) > 500:
                raise ValueError("Website URL is too long.")
        return v

    @field_validator("office_hours")
    @classmethod
    def validate_office_hours(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) < 5 or len(v) > 200:
                raise ValueError("Office hours must be 5–200 characters.")
            # Basic format check: should contain time indicators like am, pm, or hyphens
            lower = v.lower()
            if not any(x in lower for x in ["am", "pm", "-", "–", ":"]):
                raise ValueError("Office hours should include time format (e.g., 8am-5pm).")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v):
        if v is not None:
            v = v.strip()
            valid_zones = {
                "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
                "US/Alaska", "US/Hawaii", "UTC", "Europe/London",
                "Europe/Paris", "Australia/Sydney",
            }
            if v not in valid_zones:
                raise ValueError(f"Timezone must be one of: {', '.join(sorted(valid_zones))}")
        return v

    @field_validator("cancellation_policy", "after_hours_protocol", "escalation_contact")
    @classmethod
    def validate_text_field(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) > 500:
                raise ValueError("Text field is too long (max 500 chars).")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Sunshine Family Medicine",
                "specialty": "Family Medicine",
                "phone": "555-123-4567",
                "address": "123 Main St",
                "office_hours": "Mon–Fri 8am–5pm",
                "timezone": "US/Eastern",
            }
        }
