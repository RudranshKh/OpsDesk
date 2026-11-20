from dataclasses import dataclass

from app.db.models import AgentProfile, User

EXACT_REGION_POINTS = 40
GLOBAL_REGION_POINTS = 20
AVAILABILITY_POINTS = 20
MAX_WORKLOAD_POINTS = 30
ELIGIBLE_ROLES = {"agent", "escalation_manager"}
PRIORITY_ROLE_POINTS = {
    "urgent": {"escalation_manager": 30, "agent": 16},
    "high": {"escalation_manager": 26, "agent": 19},
    "normal": {"agent": 22, "escalation_manager": 20},
    "low": {"agent": 22, "escalation_manager": 18},
}
WORKLOAD_PENALTY = {"urgent": 10, "high": 8, "normal": 5, "low": 4}


@dataclass(frozen=True)
class RoutingCandidate:
    user: User
    profile: AgentProfile
    current_workload: int


@dataclass(frozen=True)
class ScoredAgent:
    candidate: RoutingCandidate
    score: int
    region_points: int
    priority_points: int
    workload_points: int
    availability_points: int
    regional_match: str
    explanation: str


def score_agent(
    candidate: RoutingCandidate,
    *,
    ticket_priority: str,
    ticket_region: str | None,
) -> ScoredAgent | None:
    user = candidate.user
    profile = candidate.profile
    if user.role not in ELIGIBLE_ROLES or not user.is_active or not profile.is_available:
        return None

    normalized_region = ticket_region.strip().casefold() if ticket_region else ""
    expertise = {region.strip().casefold() for region in profile.regions if region.strip()}
    if normalized_region and normalized_region in expertise:
        regional_match = "exact"
        region_points = EXACT_REGION_POINTS
        region_reason = f"exact regional expertise match for {ticket_region.strip()} (+{region_points})"
    elif normalized_region and "global" in expertise:
        regional_match = "global"
        region_points = GLOBAL_REGION_POINTS
        region_reason = f"Global expertise fallback for {ticket_region.strip()} (+{region_points})"
    elif normalized_region:
        regional_match = "none"
        region_points = 0
        region_reason = f"no regional expertise match for {ticket_region.strip()} (+0)"
    else:
        regional_match = "none"
        region_points = 0
        region_reason = "ticket has no region specified (+0)"
    priority_points = PRIORITY_ROLE_POINTS[ticket_priority][user.role]
    workload_points = max(
        0,
        MAX_WORKLOAD_POINTS - WORKLOAD_PENALTY[ticket_priority] * candidate.current_workload,
    )
    availability_points = AVAILABILITY_POINTS
    score = region_points + priority_points + workload_points + availability_points

    priority_reason = (
        f"{user.role.replace('_', ' ')} priority fit for {ticket_priority} tickets "
        f"(+{priority_points})"
    )

    explanation = (
        f"{region_reason}; {priority_reason}; available (+{availability_points}); "
        f"workload is {candidate.current_workload} active ticket(s) (+{workload_points})."
    )
    return ScoredAgent(
        candidate=candidate,
        score=score,
        region_points=region_points,
        priority_points=priority_points,
        workload_points=workload_points,
        availability_points=availability_points,
        regional_match=regional_match,
        explanation=explanation,
    )


def score_candidates(
    candidates: list[RoutingCandidate],
    *,
    ticket_priority: str,
    ticket_region: str | None,
) -> list[ScoredAgent]:
    scored = [
        result
        for candidate in candidates
        if (result := score_agent(
            candidate, ticket_priority=ticket_priority, ticket_region=ticket_region
        )) is not None
    ]
    return sorted(
        scored,
        key=lambda result: (
            -result.score,
            result.candidate.current_workload,
            result.candidate.user.id,
        ),
    )


def choose_agent(
    candidates: list[RoutingCandidate],
    *,
    ticket_priority: str,
    ticket_region: str | None,
) -> ScoredAgent | None:
    scored = score_candidates(
        candidates, ticket_priority=ticket_priority, ticket_region=ticket_region
    )
    if not scored:
        return None
    return scored[0]
