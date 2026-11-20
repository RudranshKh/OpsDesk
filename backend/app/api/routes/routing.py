from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_current_user, get_db, get_ticket_for_user, require_roles
from app.api.schemas.routing import RoutingAssignmentRead, RoutingCandidateScoreRead
from app.db.models import AgentProfile, Assignment, Ticket, User
from app.services.ticket_routing import RoutingCandidate, score_candidates

router = APIRouter(prefix="/tickets", tags=["ticket-routing"])
def _routing_candidates(db: Session, ticket: Ticket) -> list[RoutingCandidate]:
    workload_rows = db.execute(
        select(Assignment.user_id, func.count(Assignment.id))
        .join(Ticket, Ticket.id == Assignment.ticket_id)
        .where(
            Assignment.unassigned_at.is_(None),
            Assignment.ticket_id != ticket.id,
            Ticket.status.in_(("open", "pending")),
            Ticket.agency_id == ticket.agency_id,
        )
        .group_by(Assignment.user_id)
    ).all()
    workloads = {user_id: count for user_id, count in workload_rows}
    profile_rows = db.execute(
        select(User, AgentProfile)
        .join(AgentProfile, AgentProfile.user_id == User.id)
        .where(
            User.agency_id == ticket.agency_id,
            User.role.in_(("agent", "escalation_manager")),
            User.is_active.is_(True),
        )
        .order_by(User.id)
    ).all()
    return [
        RoutingCandidate(user=user, profile=profile, current_workload=workloads.get(user.id, 0))
        for user, profile in profile_rows
    ]


def _candidate_score_reads(scores) -> list[RoutingCandidateScoreRead]:
    return [
        RoutingCandidateScoreRead(
            agent_id=scored.candidate.user.id,
            agent_name=scored.candidate.user.full_name,
            agent_role=scored.candidate.user.role,
            regional_expertise=scored.candidate.profile.regions,
            available=scored.candidate.profile.is_available,
            regional_match=scored.regional_match,
            region_points=scored.region_points,
            priority_points=scored.priority_points,
            workload=scored.candidate.current_workload,
            workload_points=scored.workload_points,
            availability_points=scored.availability_points,
            total_score=scored.score,
            explanation=scored.explanation,
        )
        for scored in scores
    ]


def _assignment_read(
    assignment: Assignment,
    candidate_scores: list[RoutingCandidateScoreRead] | None = None,
) -> RoutingAssignmentRead:
    profile = assignment.user.agent_profile
    return RoutingAssignmentRead(
        id=assignment.id,
        ticket_id=assignment.ticket_id,
        agent_id=assignment.user_id,
        agent_name=assignment.user.full_name,
        agent_role=assignment.user.role,
        agent_regions=profile.regions if profile else [],
        workload=assignment.routing_workload or 0,
        score=assignment.routing_score,
        explanation=assignment.routing_explanation or "This assignment has no routing explanation.",
        assigned_at=assignment.assigned_at,
        candidate_scores=candidate_scores or [],
    )


@router.get("/{ticket_id}/assignment", response_model=RoutingAssignmentRead)
def current_ticket_assignment(
    ticket_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoutingAssignmentRead:
    ticket = get_ticket_for_user(ticket_id, user, db)
    assignment = db.scalar(
        select(Assignment)
        .where(Assignment.ticket_id == ticket_id, Assignment.unassigned_at.is_(None))
        .options(joinedload(Assignment.user).joinedload(User.agent_profile))
        .order_by(Assignment.assigned_at.desc(), Assignment.id.desc())
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Ticket has no active assignment")
    candidates = _routing_candidates(db, ticket)
    scores = score_candidates(
        candidates, ticket_priority=ticket.priority, ticket_region=ticket.region
    )
    return _assignment_read(assignment, _candidate_score_reads(scores))


@router.post("/{ticket_id}/assign", response_model=RoutingAssignmentRead)
def route_ticket(
    ticket_id: int,
    user: User = Depends(require_roles("admin", "escalation_manager")),
    db: Session = Depends(get_db),
) -> RoutingAssignmentRead:
    ticket = get_ticket_for_user(ticket_id, user, db)

    candidates = _routing_candidates(db, ticket)
    scores = score_candidates(
        candidates, ticket_priority=ticket.priority, ticket_region=ticket.region
    )
    if not scores:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No eligible, available agent with a routing profile is available for this ticket",
        )

    selected = scores[0]
    candidate_scores = _candidate_score_reads(scores)
    active_assignments = list(
        db.scalars(
            select(Assignment).where(
                Assignment.ticket_id == ticket.id,
                Assignment.unassigned_at.is_(None),
            )
        ).all()
    )
    already_assigned = next(
        (item for item in active_assignments if item.user_id == selected.candidate.user.id),
        None,
    )
    if already_assigned is not None:
        already_assigned.routing_score = selected.score
        already_assigned.routing_workload = selected.candidate.current_workload
        already_assigned.routing_explanation = selected.explanation
        db.commit()
        assignment_id = already_assigned.id
    else:
        now = datetime.now(timezone.utc)
        for assignment in active_assignments:
            assignment.unassigned_at = now
        assignment = Assignment(
            ticket_id=ticket.id,
            user_id=selected.candidate.user.id,
            assigned_by_id=user.id,
            routing_score=selected.score,
            routing_workload=selected.candidate.current_workload,
            routing_explanation=selected.explanation,
        )
        db.add(assignment)
        db.commit()
        assignment_id = assignment.id

    assignment = db.scalar(
        select(Assignment)
        .where(Assignment.id == assignment_id)
        .options(joinedload(Assignment.user).joinedload(User.agent_profile))
    )
    return _assignment_read(assignment, candidate_scores)
