"""Demo records inserted on first start so the API and dashboard are not empty."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Patient
from app.schemas import PatientCreate
from app.services import patients as patient_service

SEED_PATIENTS = [
    {
        "first_name": "Jane", "last_name": "Doe", "date_of_birth": "03/03/1985", "sex": "Female",
        "phone_number": "7325550101", "email": "jane.doe@example.com",
        "address_line_1": "123 Main Street", "address_line_2": "Apt 4B",
        "city": "Somerset", "state": "NJ", "zip_code": "08873",
        "insurance_provider": "Blue Cross Blue Shield", "insurance_member_id": "XYZ123456789",
        "emergency_contact_name": "John Doe", "emergency_contact_phone": "7325550102",
    },
    {
        "first_name": "Carlos", "last_name": "Rivera", "date_of_birth": "11/21/1972", "sex": "Male",
        "phone_number": "2125550147", "address_line_1": "88 Hudson Avenue",
        "city": "New York", "state": "NY", "zip_code": "10013-2204",
        "preferred_language": "Spanish",
    },
]


def seed_if_empty(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(Patient)):
        return
    for record in SEED_PATIENTS:
        patient_service.create_patient(session, PatientCreate(**record))
