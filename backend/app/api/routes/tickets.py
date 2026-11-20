from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.schemas.case_links import (
    ConfirmTicketLinkRequest,
    RelatedTicketRead,
    TicketLinkRead,
)
from app.api.schemas.sla import SLAEscalationRead, SLAOverviewRead, TicketSLASummary
from app.api.dependencies import get_db
from app.api.dependencies import get_current_user, get_ticket_for_user, require_roles
from app.api.schemas.tickets import (
    TicketCreate,
    TicketPriority,
    TicketRead,
    TicketStatus,
    TicketUpdate,
)
from app.db.models import ActivityLog, Assignment, SLAEscalation, Ticket, TicketLink, User
from app.services.case_linking import find_related_tickets
from app.services.sla import evaluate_ticket_sla

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _ticket_query():
    return select(Ticket).options(joinedload(Ticket.agency), joinedload(Ticket.created_by))


def _to_read(ticket: Ticket, db: Session) -> TicketRead:
    sla = evaluate_ticket_sla(db, ticket)
    return TicketRead(
        id=ticket.id,
        reference=ticket.reference,
        agency_id=ticket.agency_id,
        agency_name=ticket.agency.name,
        created_by_id=ticket.created_by_id,
        created_by_name=ticket.created_by.full_name,
        subject=ticket.subject,
        description=ticket.description,
        region=ticket.region,
        check_in_at=ticket.check_in_at,
        departure_at=ticket.departure_at,
        status=ticket.status,
        priority=ticket.priority,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
        sla=TicketSLASummary.model_validate(sla, from_attributes=True),
    )


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketRead:
    ticket = Ticket(
        reference=f"OPS-{uuid4().hex[:10].upper()}",
        agency_id=user.agency_id,
        created_by_id=user.id,
        subject=payload.subject,
        description=payload.description,
        region=payload.region,
        check_in_at=payload.check_in_at,
        departure_at=payload.departure_at,
        priority=payload.priority,
    )
    try:
        db.add(ticket)
        db.flush()
        ticket = db.scalar(_ticket_query().where(Ticket.id == ticket.id))
        result = _to_read(ticket, db)
        db.commit()
        return result
    except Exception:
        # Keep the ticket, initial SLA row, and any initial escalation effects
        # in one transaction. A failed response must not leave an unseen ticket.
        db.rollback()
        raise


@router.get("", response_model=list[TicketRead])
def list_tickets(
    response: Response,
    status_filter: TicketStatus | None = Query(default=None, alias="status"),
    priority: TicketPriority | None = None,
    risk: str | None = Query(default=None, pattern="^(at_risk|breached)$"),
    q: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TicketRead]:
    statement = _ticket_query().where(Ticket.agency_id == user.agency_id)
    if status_filter is not None:
        statement = statement.where(Ticket.status == status_filter)
    if priority is not None:
        statement = statement.where(Ticket.priority == priority)
    if q:
        search = f"%{q.strip()}%"
        statement = statement.where(
            or_(Ticket.reference.ilike(search), Ticket.subject.ilike(search), Ticket.description.ilike(search))
        )
    statement = statement.order_by(Ticket.created_at.desc(), Ticket.id.desc())
    items = []
    for ticket in db.scalars(statement).unique().all():
        result = _to_read(ticket, db)
        if risk == "at_risk" and result.sla.sla_status not in {"approaching", "travel_urgent"}:
            continue
        if risk == "breached" and result.sla.sla_status != "breached":
            continue
        items.append(result)
    db.commit()
    # The list body remains an array for compatibility; expose the exact
    # agency-scoped filtered total so clients can paginate without guessing.
    response.headers["X-Total-Count"] = str(len(items))
    return items[offset : offset + limit]


@router.get("/summary")
def ticket_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    counts = db.execute(
        select(
            func.count(Ticket.id),
            func.sum(case((Ticket.status == "open", 1), else_=0)),
            func.sum(case((Ticket.status == "pending", 1), else_=0)),
            func.sum(case((Ticket.priority == "urgent", 1), else_=0)),
        ).where(Ticket.agency_id == user.agency_id)
    ).one()
    return {
        "total": counts[0] or 0,
        "open": counts[1] or 0,
        "pending": counts[2] or 0,
        "urgent": counts[3] or 0,
    }


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(
    ticket_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketRead:
    get_ticket_for_user(ticket_id, user, db)
    ticket = db.scalar(_ticket_query().where(Ticket.id == ticket_id))
    result = _to_read(ticket, db)
    db.commit()
    return result


@router.patch("/{ticket_id}", response_model=TicketRead)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketRead:
    get_ticket_for_user(ticket_id, user, db, write=True)
    ticket = db.scalar(_ticket_query().where(Ticket.id == ticket_id))
    old_status = ticket.status
    if "check_in_at" in payload.model_fields_set:
        ticket.check_in_at = payload.check_in_at
    if "departure_at" in payload.model_fields_set:
        ticket.departure_at = payload.departure_at

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)
    if "status" in payload.model_fields_set and payload.status != old_status:
        if payload.status in {"resolved", "closed"}:
            ticket.resolved_at = ticket.resolved_at or datetime.now(timezone.utc)
        else:
            ticket.resolved_at = None
        db.add(
            ActivityLog(
                ticket_id=ticket.id,
                actor_id=user.id,
                event_type="ticket.status_changed",
                summary=f"Ticket status changed from {old_status} to {payload.status}.",
                details={"from": old_status, "to": payload.status},
            )
        )
    db.commit()
    db.refresh(ticket)
    ticket = db.scalar(_ticket_query().where(Ticket.id == ticket_id))
    result = _to_read(ticket, db)
    db.commit()
    return result


@router.get("/{ticket_id}/sla", response_model=SLAOverviewRead)
def ticket_sla_overview(
    ticket_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SLAOverviewRead:
    ticket = get_ticket_for_user(ticket_id, user, db)
    sla = evaluate_ticket_sla(db, ticket)
    history = db.scalars(
        select(SLAEscalation)
        .where(SLAEscalation.ticket_id == ticket.id)
        .options(joinedload(SLAEscalation.assignment).joinedload(Assignment.user))
        .order_by(SLAEscalation.triggered_at.desc(), SLAEscalation.id.desc())
    ).all()
    result = SLAOverviewRead(
        ticket_id=ticket.id,
        **TicketSLASummary.model_validate(sla, from_attributes=True).model_dump(),
        escalation_history=[
            SLAEscalationRead(
                id=event.id,
                rule_key=event.rule_key,
                triggered_at=event.triggered_at,
                assignment_id=event.assignment_id,
                assigned_to=event.assignment.user.full_name if event.assignment else None,
                summary=event.summary,
            )
            for event in history
        ],
    )
    db.commit()
    return result


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket(
    ticket_id: int,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> Response:
    ticket = get_ticket_for_user(ticket_id, user, db, write=True)
    db.delete(ticket)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{ticket_id}/related", response_model=list[RelatedTicketRead])
def related_tickets(
    ticket_id: int,
    limit: int = Query(default=8, ge=1, le=30),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RelatedTicketRead]:
    ticket = get_ticket_for_user(ticket_id, user, db)

    candidates = list(
        db.scalars(
            select(Ticket)
            .where(Ticket.agency_id == user.agency_id, Ticket.id != ticket.id)
            .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        ).all()
    )
    link_rows = db.execute(
        select(TicketLink.ticket_id, TicketLink.linked_ticket_id).where(
            or_(TicketLink.ticket_id == ticket.id, TicketLink.linked_ticket_id == ticket.id)
        )
    ).all()
    linked_ids = {
        linked_id if linked_id != ticket.id else source_id
        for source_id, linked_id in link_rows
    }

    matches = find_related_tickets(ticket, candidates)
    return [
        RelatedTicketRead(
            id=match.ticket.id,
            reference=match.ticket.reference,
            subject=match.ticket.subject,
            status=match.ticket.status,
            priority=match.ticket.priority,
            created_at=match.ticket.created_at,
            similarity_score=round(match.similarity_score, 4),
            explanation=match.explanation,
            match_type=match.match_type,
            is_linked=match.ticket.id in linked_ids,
        )
        for match in matches[:limit]
    ]


@router.post(
    "/{ticket_id}/links",
    response_model=TicketLinkRead,
    status_code=status.HTTP_201_CREATED,
)
def confirm_ticket_link(
    ticket_id: int,
    payload: ConfirmTicketLinkRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketLink:
    ticket = get_ticket_for_user(ticket_id, user, db, write=True)
    linked_ticket = db.scalar(
        select(Ticket).where(
            Ticket.id == payload.linked_ticket_id,
            Ticket.agency_id == user.agency_id,
        )
    )
    if linked_ticket is None:
        raise HTTPException(status_code=404, detail="Suggested ticket not found")
    if linked_ticket.id == ticket.id:
        raise HTTPException(status_code=422, detail="A ticket cannot be linked to itself")
    if linked_ticket.agency_id != ticket.agency_id:
        raise HTTPException(status_code=422, detail="Tickets must belong to the same agency")

    existing_link = db.scalar(
        select(TicketLink.id).where(
            or_(
                (TicketLink.ticket_id == ticket.id)
                & (TicketLink.linked_ticket_id == linked_ticket.id),
                (TicketLink.ticket_id == linked_ticket.id)
                & (TicketLink.linked_ticket_id == ticket.id),
            )
        )
    )
    if existing_link is not None:
        raise HTTPException(status_code=409, detail="These tickets are already linked")

    link = TicketLink(ticket_id=ticket.id, linked_ticket_id=linked_ticket.id, link_type="related")
    db.add(link)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="These tickets are already linked") from error
    db.refresh(link)
    return link
