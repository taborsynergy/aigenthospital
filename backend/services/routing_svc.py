"""Multi-location routing service for intelligent location matching."""
from typing import Optional
from sqlalchemy.orm import Session

from backend.db.models import Location
from backend.db.crud import list_locations


def route_to_location(
    clinic_id: int,
    db: Session,
    patient_zip: Optional[str] = None,
    appointment_type: Optional[str] = None,
) -> Optional[Location]:
    """
    Route patient to best-match location based on zip code and appointment type.
    Returns Location or None if no suitable location found.

    Routing logic:
    1. Match patient zip code to location coverage
    2. Match appointment type to location services
    3. Prefer primary location if no specific match
    4. Fall back to first active location
    """
    locations = list_locations(db, clinic_id)
    if not locations:
        return None

    # Filter by active status
    active_locs = [loc for loc in locations if loc.is_active]
    if not active_locs:
        return None

    # If no patient info, return primary or first location
    if not patient_zip and not appointment_type:
        primary = next((loc for loc in active_locs if loc.is_primary), None)
        return primary or active_locs[0]

    # Score locations based on matching criteria
    scored_locs = []
    for loc in active_locs:
        score = 0

        # Zip code match (highest priority)
        if patient_zip and loc.zip_code_coverage:
            covered_zips = [z.strip() for z in loc.zip_code_coverage.split(",") if z.strip()]
            if patient_zip in covered_zips:
                score += 100

        # Appointment type / service match
        if appointment_type and loc.service_categories:
            services = [s.strip().lower() for s in loc.service_categories.split(",") if s.strip()]
            if appointment_type.lower() in services:
                score += 50

        # Primary location bonus
        if loc.is_primary:
            score += 10

        scored_locs.append((score, loc))

    # Return location with highest score
    if scored_locs:
        scored_locs.sort(key=lambda x: x[0], reverse=True)
        return scored_locs[0][1]

    # Fallback to primary or first location
    primary = next((loc for loc in active_locs if loc.is_primary), None)
    return primary or active_locs[0]


def get_routing_info(location: Location) -> dict:
    """Get human-readable routing info for a location."""
    zip_codes = location.zip_code_coverage.split(",") if location.zip_code_coverage else []
    services = location.service_categories.split(",") if location.service_categories else []

    return {
        "location_id": location.id,
        "name": location.name,
        "address": location.address or "",
        "phone": location.phone or "",
        "zip_code_coverage": [z.strip() for z in zip_codes if z.strip()],
        "service_categories": [s.strip() for s in services if s.strip()],
        "is_primary": location.is_primary,
    }
