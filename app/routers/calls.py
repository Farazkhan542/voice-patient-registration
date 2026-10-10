"""Read-only access to call logs (transcripts and summaries) for the dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ok
from app.schemas import CallLogOut
from app.services import calls as call_service

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("")
def list_calls(session: Session = Depends(get_session)):
    logs = call_service.list_calls(session)
    return ok([CallLogOut.model_validate(log).model_dump(mode="json") for log in logs])
