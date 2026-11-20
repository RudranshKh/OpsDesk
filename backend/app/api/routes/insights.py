from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.api.schemas.insights import InsightsRead
from app.api.schemas.tickets import TicketPriority
from app.db.models import User
from app.services.insights import build_insights

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("", response_model=InsightsRead)
def get_insights(
    date_from: date | None = None,
    date_to: date | None = None,
    agency_id: int | None = Query(default=None, gt=0),
    priority: TicketPriority | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InsightsRead:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    if agency_id is not None and agency_id != user.agency_id:
        raise HTTPException(status_code=403, detail="You cannot access insights for another agency")
    return build_insights(
        db,
        agency_id=user.agency_id,
        date_from=date_from,
        date_to=date_to,
        priority=priority,
    )
