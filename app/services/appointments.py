"""Appointment scheduling with mock availability.

There is no real clinic calendar behind this: slots are generated (fixed times on
the next few weekdays) and a slot disappears once somebody books it.
"""

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment

CLINIC_TIMEZONE = ZoneInfo("America/New_York")
PROVIDER = "Dr. Elena Park"
SLOT_TIMES = (time(9, 30), time(14, 0))
DAYS_AHEAD = 3
MAX_SLOTS_OFFERED = 4
SLOT_FORMAT = "%Y-%m-%dT%H:%M"


def describe(starts_at: datetime) -> str:
    """Human-readable slot, e.g. 'Tuesday, October 13 at 9:30 AM'."""
    hour = starts_at.hour % 12 or 12
    suffix = "AM" if starts_at.hour < 12 else "PM"
    return f"{starts_at:%A, %B} {starts_at.day} at {hour}:{starts_at:%M} {suffix}"


def _candidate_slots(now: datetime) -> list[datetime]:
    slots, day = [], now.date()
    while len(slots) < DAYS_AHEAD * len(SLOT_TIMES):
        day += timedelta(days=1)
        if day.weekday() < 5:  # Monday-Friday
            slots.extend(datetime.combine(day, slot_time) for slot_time in SLOT_TIMES)
    return slots


def available_slots(session: Session) -> list[datetime]:
    """Open slots as naive clinic-local datetimes."""
    booked = set(session.scalars(select(Appointment.starts_at)))
    now = datetime.now(CLINIC_TIMEZONE).replace(tzinfo=None)
    return [s for s in _candidate_slots(now) if s not in booked][:MAX_SLOTS_OFFERED]


def book_appointment(session: Session, patient_id: uuid.UUID, slot: str) -> Appointment | None:
    """Book a slot (given as YYYY-MM-DDTHH:MM). Returns None if it is not open."""
    try:
        starts_at = datetime.strptime(slot.strip(), SLOT_FORMAT)
    except ValueError:
        return None
    if starts_at not in available_slots(session):
        return None
    appointment = Appointment(patient_id=patient_id, starts_at=starts_at, provider=PROVIDER)
    session.add(appointment)
    session.commit()
    return appointment


def list_appointments(session: Session, patient_id: uuid.UUID) -> list[Appointment]:
    query = select(Appointment).where(Appointment.patient_id == patient_id)
    return list(session.scalars(query.order_by(Appointment.starts_at)))
