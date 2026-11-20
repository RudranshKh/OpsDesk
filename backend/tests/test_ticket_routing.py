from app.db.models import AgentProfile, User
from app.services.ticket_routing import RoutingCandidate, choose_agent, score_agent


def candidate(
    user_id: int,
    *,
    role: str = "agent",
    regions: list[str] | None = None,
    available: bool = True,
    workload: int = 0,
) -> RoutingCandidate:
    user = User(id=user_id, role=role, is_active=True)
    profile = AgentProfile(user_id=user_id, regions=regions or [], is_available=available)
    return RoutingCandidate(user=user, profile=profile, current_workload=workload)


def test_selects_agent_with_matching_regional_expertise():
    expert = candidate(1, regions=["Europe"])
    generalist = candidate(2, regions=["Asia"])

    selected = choose_agent(
        [generalist, expert], ticket_priority="normal", ticket_region="europe"
    )

    assert selected is not None
    assert selected.candidate.user.id == 1
    assert selected.regional_match == "exact"
    assert "exact regional expertise match" in selected.explanation
    assert selected.region_points == 40
    assert selected.score == 112


def test_exact_region_match_scores_above_global_fallback():
    exact = candidate(1, regions=["Europe"])
    global_fallback = candidate(2, regions=["Global"])

    exact_score = score_agent(exact, ticket_priority="normal", ticket_region="Europe")
    global_score = score_agent(global_fallback, ticket_priority="normal", ticket_region="Europe")

    assert exact_score is not None and global_score is not None
    assert exact_score.regional_match == "exact"
    assert exact_score.region_points == 40
    assert global_score.regional_match == "global"
    assert global_score.region_points == 20
    assert exact_score.score == global_score.score + 20
    assert "Global expertise fallback" in global_score.explanation


def test_no_matching_region_is_explained_without_global_fallback():
    regional_agent = candidate(1, regions=["Asia Pacific"])

    scored = score_agent(
        regional_agent, ticket_priority="normal", ticket_region="Europe"
    )

    assert scored is not None
    assert scored.regional_match == "none"
    assert scored.region_points == 0
    assert "no regional expertise match for Europe" in scored.explanation


def test_workload_balancing_prefers_less_loaded_agent():
    lightly_loaded = candidate(1, regions=["Europe"], workload=0)
    heavily_loaded = candidate(2, regions=["Europe"], workload=3)

    selected = choose_agent(
        [heavily_loaded, lightly_loaded], ticket_priority="normal", ticket_region="Europe"
    )

    assert selected is not None
    assert selected.candidate.user.id == 1
    assert selected.candidate.current_workload == 0


def test_unavailable_agent_is_excluded():
    unavailable_expert = candidate(1, regions=["Europe"], available=False)
    available_agent = candidate(2, regions=["Asia"], available=True)

    selected = choose_agent(
        [unavailable_expert, available_agent],
        ticket_priority="urgent",
        ticket_region="Europe",
    )

    assert selected is not None
    assert selected.candidate.user.id == 2


def test_unavailable_exact_expert_does_not_beat_available_global_fallback():
    unavailable_exact = candidate(1, regions=["Europe"], available=False)
    available_global = candidate(2, regions=["Global"], available=True)

    selected = choose_agent(
        [unavailable_exact, available_global],
        ticket_priority="high",
        ticket_region="Europe",
    )

    assert selected is not None
    assert selected.candidate.user.id == 2
    assert selected.regional_match == "global"


def test_no_eligible_agents_returns_none():
    unavailable = candidate(1, available=False)
    admin = candidate(2, role="admin")

    assert choose_agent(
        [unavailable, admin], ticket_priority="high", ticket_region="Europe"
    ) is None


def test_deterministic_tie_break_uses_lowest_user_id_regardless_of_input_order():
    higher_id = candidate(8, regions=["Global"], workload=1)
    lower_id = candidate(3, regions=["Global"], workload=1)

    first = choose_agent(
        [higher_id, lower_id], ticket_priority="normal", ticket_region="Europe"
    )
    second = choose_agent(
        [lower_id, higher_id], ticket_priority="normal", ticket_region="Europe"
    )

    assert first is not None and second is not None
    assert first.candidate.user.id == second.candidate.user.id == 3


def test_route_endpoint_records_assignment_and_explanation(api_client, login_as):
    ticket = api_client.post(
        "/api/tickets",
        json={
            "subject": "Urgent itinerary change",
            "description": "Traveler needs a same-day rebooking.",
            "priority": "urgent",
            "region": "Europe",
        },
    ).json()

    assert login_as("alex@northstar.example").status_code == 200
    denied = api_client.post(f"/api/tickets/{ticket['id']}/assign")
    assert denied.status_code == 403

    assert login_as("erin@northstar.example").status_code == 200
    routed = api_client.post(f"/api/tickets/{ticket['id']}/assign")
    assert routed.status_code == 200
    assert routed.json()["agent_name"] == "Erin Manager"
    assert routed.json()["score"] > 0
    assert "escalation manager priority fit" in routed.json()["explanation"]
    candidates = routed.json()["candidate_scores"]
    assert {item["agent_name"] for item in candidates} == {"Alex Morgan", "Erin Manager"}
    assert candidates[0]["total_score"] >= candidates[1]["total_score"]
    assert all(item["available"] for item in candidates)

    current = api_client.get(f"/api/tickets/{ticket['id']}/assignment")
    assert current.status_code == 200
    assert current.json()["id"] == routed.json()["id"]
    assert len(current.json()["candidate_scores"]) == 2
    assert "available" in current.json()["explanation"]


def test_route_endpoint_returns_conflict_when_all_profiles_are_unavailable(api_client, database_engine):
    from sqlalchemy.orm import Session

    with Session(database_engine) as session:
        profiles = session.query(AgentProfile).all()
        for profile in profiles:
            profile.is_available = False
        session.commit()

    ticket = api_client.post("/api/tickets", json={
        "subject": "No agents available",
        "priority": "normal",
    }).json()
    response = api_client.post(f"/api/tickets/{ticket['id']}/assign")

    assert response.status_code == 409
    assert response.json()["detail"].startswith("No eligible")
