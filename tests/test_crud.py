
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
# Temporarily import ColumnElement if needed for some type checking issues.
# from sqlalchemy.sql.elements import ColumnElement
# from typing import TypeVar, Union

from backend.db.database import Base #, get_db
from backend.db.crud import create_clinic, get_clinic

from backend.db.models import Clinic

# Use an in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Drop tables after each test to ensure a clean state
        Base.metadata.drop_all(bind=engine)


def test_create_and_get_clinic(db_session):
    # Create a test clinic data (as dict)
    clinic_data = {
        "name": "Test Clinic for CRUD",
        "slug": "test-crud",
        "specialty": "General Medicine",
        "email": "crud@example.com",
        "agent_name": "TestBot",
        "phone": "123-456-7890",
        "address": "123 Test St",
        "city_state": "Testville, CA",
        "timezone": "UTC",
        "office_hours": "9-5",
        "after_hours_protocol": "call 911",
        "providers": "Dr. Test",
        "services_offered": "Checkups",
        "insurance_accepted": "All",
        "pms_system": "TestPM",
        "cancellation_policy": "24hr notice",
        "escalation_contact": "test@test.com",
        "hipaa_verify_method": "dob",
        "twilio_phone": "+155****4567"
    }
    
    # Create the clinic
    created_clinic = create_clinic(db_session, clinic_data)

    assert created_clinic.name == "Test Clinic for CRUD"
    assert created_clinic.slug == "test-crud"
    assert created_clinic.email == "crud@example.com"

    # Get the clinic
    fetched_clinic = get_clinic(db_session, "test-crud")

    assert fetched_clinic is not None
    assert fetched_clinic.id == created_clinic.id
    assert fetched_clinic.name == created_clinic.name
