from datetime import datetime, timedelta, timezone
from math import floor

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AgentProfile,
    Assignment,
    Conversation,
    SLAEscalation,
    Ticket,
    TicketSLA,
    User,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _travel_deadline(ticket: Ticket) -> tuple[datetime | None, str | None]:
    candidates = [
        (ticket.check_in_at, "check_in"),
        (ticket.departure_at, "departure"),
    ]
    candidates = [(value, label) for value, label in candidates if value is not None]
    if not candidates:
        return None, None
    value, label = min(candidates, key=lambda item: _utc(item[0]))
    return _utc(value), label


def _deadline(start: datetime, target_minutes: int, travel_at: datetime | None) -> datetime:
    policy_deadline = start + timedelta(minutes=target_minutes)
    return min(policy_deadline, travel_at) if travel_at is not None else policy_deadline


def evaluate_ticket_sla(
    db: Session,
    ticket: Ticket,
    *,
    now: datetime | None = None,
    auto_escalate: bool = True,
) -> TicketSLA:
    """Recalculate one ticket's travel-aware deadlines and persist its current SLA state."""
    now = _utc(now or datetime.now(timezone.utc))
    policy = settings.sla_targets[ticket.priority]
    created_at = _utc(ticket.created_at)
    travel_at, travel_type = _travel_deadline(ticket)
    response_due = _deadline(created_at, policy["response_minutes"], travel_at)
    resolution_due = _deadline(created_at, policy["resolution_minutes"], travel_at)

    first_response = db.scalar(
        select(func.min(Conversation.created_at)).where(
            Conversation.ticket_id == ticket.id,
            Conversation.is_internal.is_(False),
        )
    )
    if first_response is not None:
        first_response = _utc(first_response)

    sla = db.get(TicketSLA, ticket.id)
    if sla is None:
        new_sla = TicketSLA(
            ticket_id=ticket.id,
            response_due_at=response_due,
            resolution_due_at=resolution_due,
            evaluated_at=now,
        )
        try:
            with db.begin_nested():
                db.add(new_sla)
                db.flush()
            sla = new_sla
        except IntegrityError:
            # Another request or the background evaluator created this ticket's
            # one-to-one SLA row first.
            sla = db.get(TicketSLA, ticket.id)
            if sla is None:
                raise
    resolved_at = None
    if ticket.status in {"resolved", "closed"} and ticket.resolved_at is not None:
        resolved_at = _utc(ticket.resolved_at)

    def deadline_status(due_at: datetime, completed_at: datetime | None) -> tuple[str, int | None]:
        if completed_at is not None:
            return ("met" if completed_at <= due_at else "breached"), None
        remaining = (due_at - now).total_seconds()
        if remaining < 0:
            return "breached", floor(remaining)
        if remaining <= settings.sla_approaching_minutes * 60:
            return "approaching", floor(remaining)
        return "on_track", floor(remaining)

    response_status, response_remaining = deadline_status(response_due, first_response)
    resolution_status, resolution_remaining = deadline_status(resolution_due, resolved_at)
    if ticket.status in {"resolved", "closed"} and resolved_at is not None:
        # A completed ticket no longer has a pending resolution clock.
        resolution_remaining = None

    if "breached" in {response_status, resolution_status}:
        overall_status = "breached"
    elif (
        ticket.status in {"open", "pending"}
        and travel_at is not None
        and 0 <= (travel_at - now).total_seconds() <= settings.sla_travel_urgent_minutes * 60
    ):
        overall_status = "travel_urgent"
    elif "approaching" in {response_status, resolution_status}:
        overall_status = "approaching"
    elif response_status == "met" and resolution_status == "met":
        overall_status = "met"
    else:
        overall_status = "on_track"

    sla.response_due_at = response_due
    sla.resolution_due_at = resolution_due
    sla.travel_deadline_at = travel_at
    sla.travel_deadline_type = travel_type
    sla.travel_data_status = "available" if travel_at is not None else "missing"
    sla.response_status = response_status
    sla.resolution_status = resolution_status
    sla.sla_status = overall_status
    sla.response_remaining_seconds = response_remaining
    sla.resolution_remaining_seconds = resolution_remaining
    sla.first_response_at = first_response
    sla.resolved_at = resolved_at
    sla.evaluated_at = now
    db.flush()

    if auto_escalate and settings.sla_escalation_enabled and ticket.status in {"open", "pending"}:
        if overall_status == "breached":
            _record_escalation(db, ticket, sla, "breached", now)
        elif overall_status in {"approaching", "travel_urgent"}:
            _record_escalation(db, ticket, sla, "approaching", now)
    return sla


def _record_escalation(
    db: Session, ticket: Ticket, sla: TicketSLA, rule_key: str, now: datetime
) -> None:
    initial_summary = (
        f"SLA {rule_key} rule triggered for {ticket.reference}; "
        "no available escalation manager was found."
    )
    db.execute(
        sqlite_insert(SLAEscalation)
        .values(
            ticket_id=ticket.id,
            rule_key=rule_key,
            triggered_at=now,
            assignment_id=None,
            summary=initial_summary,
        )
        .on_conflict_do_nothing(index_elements=["ticket_id", "rule_key"])
    )
    event = db.scalar(
        select(SLAEscalation).where(
            SLAEscalation.ticket_id == ticket.id, SLAEscalation.rule_key == rule_key
        )
    )
    if event is None:
        raise RuntimeError("SLA escalation reservation could not be loaded")

    active_assignment = db.scalar(
        select(Assignment)
        .where(Assignment.ticket_id == ticket.id, Assignment.unassigned_at.is_(None))
        .order_by(Assignment.assigned_at.desc(), Assignment.id.desc())
    )
    assignment = None
    if active_assignment is not None:
        current_manager = active_assignment.user
        profile = current_manager.agent_profile
        if (
            current_manager.role == "escalation_manager"
            and current_manager.is_active
            and profile is not None
            and profile.is_available
        ):
            assignment = active_assignment
    if assignment is not None:
        summary = f"SLA {rule_key} rule triggered for {ticket.reference}; assigned to {assignment.user.full_name}."
        _set_escalation_assignment(db, event, assignment.id, summary, now)
        return

    if assignment is None:
        workload_rows = db.execute(
            select(Assignment.user_id, func.count(Assignment.id))
            .join(Ticket, Ticket.id == Assignment.ticket_id)
            .where(
                Assignment.unassigned_at.is_(None),
                Assignment.ticket_id != ticket.id,
                Ticket.agency_id == ticket.agency_id,
                Ticket.status.in_(("open", "pending")),
            )
            .group_by(Assignment.user_id)
        ).all()
        workloads = {user_id: count for user_id, count in workload_rows}
        managers = db.execute(
            select(User, AgentProfile)
            .join(AgentProfile, AgentProfile.user_id == User.id)
            .where(
                User.agency_id == ticket.agency_id,
                User.role == "escalation_manager",
                User.is_active.is_(True),
                AgentProfile.is_available.is_(True),
            )
            .order_by(User.id)
        ).all()
        selected_manager = min(managers, key=lambda item: (workloads.get(item[0].id, 0), item[0].id), default=None)
        if selected_manager is not None:
            manager, _profile = selected_manager
            proposed_assignment = Assignment(
                ticket_id=ticket.id,
                user_id=manager.id,
                assigned_by_id=None,
                assigned_at=now,
                routing_explanation=f"Automatically assigned to {manager.full_name} by the {rule_key} SLA escalation rule.",
            )
            db.add(proposed_assignment)
            db.flush()
            summary = f"SLA {rule_key} rule triggered for {ticket.reference}; assigned to {manager.full_name}."
            if _set_escalation_assignment(db, event, proposed_assignment.id, summary, now):
                if active_assignment is not None:
                    active_assignment.unassigned_at = now
            else:
                # A concurrent evaluator won the event's assignment claim.
                db.delete(proposed_assignment)
                db.flush()
            return

    if active_assignment is not None:
        active_assignment.unassigned_at = now
    _set_escalation_assignment(db, event, None, initial_summary, now)


def _set_escalation_assignment(
    db: Session,
    event: SLAEscalation,
    assignment_id: int | None,
    summary: str,
    now: datetime,
) -> bool:
    """Atomically update the event's assignment pointer, preventing duplicate claims."""
    current_assignment_id = event.assignment_id
    result = db.execute(
        update(SLAEscalation)
        .where(
            SLAEscalation.id == event.id,
            SLAEscalation.assignment_id == current_assignment_id,
        )
        .values(assignment_id=assignment_id, summary=summary, triggered_at=now)
    )
    if result.rowcount != 1:
        db.refresh(event)
        return False
    event.assignment_id = assignment_id
    event.summary = summary
    event.triggered_at = now
    return True


def evaluate_open_ticket_slas(db: Session) -> int:
    """Periodic worker entry point; evaluate open tickets and persist escalation events."""
    tickets = db.scalars(select(Ticket).where(Ticket.status.in_(("open", "pending")))).all()
    for ticket in tickets:
        evaluate_ticket_sla(db, ticket)
    db.commit()
    return len(tickets)
