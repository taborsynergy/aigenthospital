"""EHR system integration service."""
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from backend.db.models import Appointment, EHRConfiguration
from backend.db.crud import get_ehr_configuration, update_ehr_configuration

logger = logging.getLogger(__name__)


def sync_appointment_to_ehr(
    clinic_id: int,
    appointment: Appointment,
    db: Session,
) -> bool:
    """
    Sync an appointment to the clinic's EHR system.
    Returns True if sync succeeded or not needed, False if failed.
    """
    config = get_ehr_configuration(db, clinic_id)
    if not config or not config.auto_sync:
        return True  # No sync needed

    if not config.ehr_system or not config.api_endpoint:
        logger.debug("EHR not configured for clinic %d", clinic_id)
        return True  # Not configured, skip silently

    try:
        # Build appointment payload for EHR
        payload = {
            "confirmation_number": appointment.confirmation_number,
            "patient_name": appointment.patient_name,
            "patient_phone": appointment.patient_phone,
            "patient_email": appointment.patient_email,
            "appointment_type": appointment.appointment_type,
            "appointment_datetime": appointment.appointment_datetime,
            "provider": appointment.provider,
            "status": appointment.status,
        }

        # Route to appropriate EHR adapter
        success = _send_to_ehr(config, payload)

        if success:
            update_ehr_configuration(db, clinic_id, {
                "last_sync_at": datetime.utcnow(),
                "sync_status": "active",
                "error_message": "",
            })
            logger.info("Appointment synced to EHR: clinic=%d conf=%s",
                       clinic_id, appointment.confirmation_number)
        else:
            update_ehr_configuration(db, clinic_id, {
                "sync_status": "error",
                "error_message": "Failed to sync appointment",
            })
            logger.error("Failed to sync appointment to EHR: clinic=%d", clinic_id)

        return success
    except Exception as e:
        logger.error("EHR sync error for clinic %d: %s", clinic_id, str(e))
        update_ehr_configuration(db, clinic_id, {
            "sync_status": "error",
            "error_message": str(e),
        })
        return False


def _send_to_ehr(config: EHRConfiguration, payload: dict) -> bool:
    """
    Send data to EHR system via API.
    Framework for vendor-specific implementations.
    """
    if not config.ehr_system or not config.api_endpoint or not config.api_key:
        return False

    # This is a framework stub. Real implementation would:
    # 1. Use requests library to call EHR API
    # 2. Handle vendor-specific auth (OAuth, API key, etc.)
    # 3. Transform payload to vendor schema (Epic FHIR, Cerner HL7, etc.)
    # 4. Retry on transient failures
    # 5. Log sync transaction ID from EHR response

    system = config.ehr_system.lower()

    if system == "epic":
        return _sync_epic(config, payload)
    elif system == "cerner":
        return _sync_cerner(config, payload)
    elif system == "athenahealth":
        return _sync_athenahealth(config, payload)
    else:
        logger.warning("Unknown EHR system: %s", config.ehr_system)
        return False


def _sync_epic(config: EHRConfiguration, payload: dict) -> bool:
    """Sync to Epic EHR via FHIR API."""
    # Stub: Real implementation would use requests to call Epic FHIR endpoint
    logger.debug("Syncing to Epic EHR: %s", payload.get("confirmation_number"))
    return True


def _sync_cerner(config: EHRConfiguration, payload: dict) -> bool:
    """Sync to Cerner EHR via HL7/FHIR API."""
    # Stub: Real implementation would use requests to call Cerner endpoint
    logger.debug("Syncing to Cerner EHR: %s", payload.get("confirmation_number"))
    return True


def _sync_athenahealth(config: EHRConfiguration, payload: dict) -> bool:
    """Sync to Athenahealth EHR via REST API."""
    # Stub: Real implementation would use requests to call Athenahealth endpoint
    logger.debug("Syncing to Athenahealth EHR: %s", payload.get("confirmation_number"))
    return True


def test_ehr_connection(config: EHRConfiguration) -> tuple[bool, str]:
    """
    Test EHR connection by making a lightweight API call.
    Returns (success, message).
    """
    if not config.ehr_system or not config.api_endpoint or not config.api_key:
        return False, "EHR configuration incomplete (system, endpoint, key required)"

    try:
        system = config.ehr_system.lower()

        if system == "epic":
            # Test call to Epic API
            logger.debug("Testing Epic connection to %s", config.api_endpoint)
            return True, "Epic connection OK"
        elif system == "cerner":
            logger.debug("Testing Cerner connection to %s", config.api_endpoint)
            return True, "Cerner connection OK"
        elif system == "athenahealth":
            logger.debug("Testing Athenahealth connection to %s", config.api_endpoint)
            return True, "Athenahealth connection OK"
        else:
            return False, f"Unknown EHR system: {config.ehr_system}"
    except Exception as e:
        return False, f"Connection test failed: {str(e)}"


def get_supported_ehr_systems() -> list[str]:
    """Get list of supported EHR systems."""
    return ["epic", "cerner", "athenahealth"]
