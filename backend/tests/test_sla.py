from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.orm import Session

from app.db.models import AgentProfile, Assignment, Conversation, SLAEscalation, Ticket, TicketSLA, User
from app.services.sla import _record_escalation, evaluate_ticket_sla


def create_ticket(api_client, *, priority="normal", **travel):
    response = api_client.post(
        "/api/tickets",
        json={"subject": "SLA check", "priority": priority, **travel},
    )
    assert response.status_code == 201
    return response.json()


def set_created_at(database_session, ticket_id, value):
    ticket = database_session.get(Ticket, ticket_id)
    ticket.created_at = value
    database_session.commit()


def test_normal_sla_is_on_track_and_missing_travel_data_is_explicit(api_client):
    ticket = create_ticket(api_client)

    assert ticket["sla"]["sla_status"] == "on_track"
    assert ticket["sla"]["travel_data_status"] == "missing"
    assert ticket["sla"]["travel_deadline_at"] is None
    assert ticket["sla"]["response_remaining_seconds"] > 0
    assert ticket["sla"]["resolution_remaining_seconds"] > 0

    detail = api_client.get(f"/api/tickets/{ticket['id']}/sla").json()
    assert detail["travel_data_status"] == "missing"
    assert detail["sla_status"] != "breached"


def test_approaching_deadline_is_filtered_and_auto_escalated(api_client, database_session):
    ticket = create_ticket(api_client)
    set_created_at(database_session, ticket["id"], datetime.now(timezone.utc) - timedelta(hours=7, minutes=30))

    overview = api_client.get(f"/api/tickets/{ticket['id']}/sla").json()
    assert overview["sla_status"] == "approaching"
    assert overview["response_remaining_seconds"] <= 60 * 60
    assert len(overview["escalation_history"]) == 1
    assert overview["escalation_history"][0]["rule_key"] == "approaching"
    assert overview["escalation_history"][0]["assigned_to"] == "Erin Manager"
    assert [item["id"] for item in api_client.get("/api/tickets", params={"risk": "at_risk"}).json()] == [ticket["id"]]
    assert database_session.query(SLAEscalation).filter_by(ticket_id=ticket["id"]).count() == 1
    assert (
        database_session.query(Assignment)
        .filter_by(ticket_id=ticket["id"], unassigned_at=None)
        .count()
        == 1
    )


def test_breached_sla_is_distinct_and_records_escalation(api_client, database_session):
    ticket = create_ticket(api_client)
    set_created_at(database_session, ticket["id"], datetime.now(timezone.utc) - timedelta(hours=9))

    overview = api_client.get(f"/api/tickets/{ticket['id']}/sla").json()
    assert overview["sla_status"] == "breached"
    assert overview["response_status"] == "breached"
    assert overview["response_remaining_seconds"] < 0
    assert overview["travel_data_status"] == "missing"
    assert overview["escalation_history"][-1]["rule_key"] == "breached"
    assert [item["id"] for item in api_client.get("/api/tickets", params={"risk": "breached"}).json()] == [ticket["id"]]


def test_known_departure_makes_ticket_travel_urgent(api_client):
    departure = datetime.now(timezone.utc) + timedelta(hours=2)
    ticket = create_ticket(api_client, priority="low", departure_at=departure.isoformat())

    assert ticket["sla"]["sla_status"] == "travel_urgent"
    assert ticket["sla"]["travel_data_status"] == "available"
    assert ticket["sla"]["travel_deadline_type"] == "departure"
    assert datetime.fromisoformat(ticket["sla"]["response_due_at"]) == departure
    overview = api_client.get(f"/api/tickets/{ticket['id']}/sla").json()
    assert overview["escalation_history"][0]["rule_key"] == "approaching"


def test_timezone_is_required_for_travel_deadlines(api_client):
    response = api_client.post(
        "/api/tickets",
        json={"subject": "Ambiguous travel time", "departure_at": "2026-12-01T10:00:00"},
    )
    assert response.status_code == 422


def test_non_utc_travel_time_round_trips_as_explicit_utc(api_client):
    departure = datetime(2026, 11, 18, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    ticket = create_ticket(api_client, departure_at=departure.isoformat())

    assert ticket["departure_at"].endswith(("+00:00", "Z"))
    assert datetime.fromisoformat(ticket["departure_at"]) == departure.astimezone(timezone.utc)
    assert datetime.fromisoformat(ticket["sla"]["travel_deadline_at"]) == departure.astimezone(timezone.utc)

    detail = api_client.get(f"/api/tickets/{ticket['id']}").json()
    assert detail["departure_at"].endswith(("+00:00", "Z"))
    assert datetime.fromisoformat(detail["departure_at"]) == departure.astimezone(timezone.utc)
    sla_detail = api_client.get(f"/api/tickets/{ticket['id']}/sla").json()
    assert sla_detail["travel_deadline_at"].endswith(("+00:00", "Z"))
    assert datetime.fromisoformat(sla_detail["travel_deadline_at"]) == departure.astimezone(timezone.utc)


def test_resolution_sla_uses_resolution_transition_not_later_ticket_edit(api_client, database_session):
    ticket_data = create_ticket(api_client)
    ticket = database_session.get(Ticket, ticket_data["id"])
    created_at = datetime.now(timezone.utc) - timedelta(days=1)
    ticket.created_at = created_at
    ticket.status = "resolved"
    ticket.resolved_at = created_at + timedelta(hours=12)
    ticket.updated_at = created_at + timedelta(days=4)
    database_session.add(
        Conversation(
            ticket_id=ticket.id,
            author_id=ticket.created_by_id,
            body="We have confirmed the updated itinerary.",
            is_internal=False,
            created_at=created_at + timedelta(hours=1),
        )
    )
    database_session.commit()

    overview = api_client.get(f"/api/tickets/{ticket.id}/sla").json()
    assert overview["resolution_status"] == "met"
    detail = api_client.get(f"/api/tickets/{ticket.id}").json()
    assert datetime.fromisoformat(detail["resolved_at"]) == ticket.resolved_at.replace(tzinfo=timezone.utc)


def test_existing_unassigned_escalation_retries_when_manager_becomes_available(
    api_client, database_session
):
    ticket_data = create_ticket(api_client)
    ticket = database_session.get(Ticket, ticket_data["id"])
    ticket.created_at = datetime.now(timezone.utc) - timedelta(hours=7, minutes=30)
    manager = database_session.query(User).filter_by(email="erin@northstar.example").one()
    manager.agent_profile.is_available = False
    database_session.commit()

    first = api_client.get(f"/api/tickets/{ticket.id}/sla").json()
    assert len(first["escalation_history"]) == 1
    assert first["escalation_history"][0]["assigned_to"] is None

    manager.agent_profile.is_available = True
    database_session.commit()
    second = api_client.get(f"/api/tickets/{ticket.id}/sla").json()
    assert len(second["escalation_history"]) == 1
    assert second["escalation_history"][0]["assigned_to"] == manager.full_name
    assert second["escalation_history"][0]["assignment_id"] is not None
    third = api_client.get(f"/api/tickets/{ticket.id}/sla").json()
    assert len(third["escalation_history"]) == 1
    assert (
        database_session.query(Assignment)
        .filter_by(ticket_id=ticket.id, unassigned_at=None)
        .count()
        == 1
    )


def test_concurrent_sla_escalations_create_one_event_and_assignment(
    api_client, database_engine
):
    ticket_data = create_ticket(api_client)
    barrier = Barrier(2)
    now = datetime.now(timezone.utc)

    def evaluate_concurrently():
        with Session(database_engine) as session:
            ticket = session.get(Ticket, ticket_data["id"])
            sla = session.get(TicketSLA, ticket_data["id"])
            barrier.wait(timeout=10)
            _record_escalation(session, ticket, sla, "approaching", now)
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(evaluate_concurrently) for _ in range(2)]
        for future in futures:
            future.result(timeout=15)

    with Session(database_engine) as session:
        assert session.query(SLAEscalation).filter_by(ticket_id=ticket_data["id"]).count() == 1
        assert (
            session.query(Assignment)
            .filter_by(ticket_id=ticket_data["id"], unassigned_at=None)
            .count()
            == 1
        )


@pytest.mark.parametrize("unavailable_state", ["unavailable", "inactive"])
def test_ineligible_current_manager_is_reassigned_to_available_manager(
    api_client, database_session, unavailable_state
):
    ticket_data = create_ticket(api_client)
    ticket = database_session.get(Ticket, ticket_data["id"])
    ticket.created_at = datetime.now(timezone.utc) - timedelta(hours=7, minutes=30)
    current_manager = database_session.query(User).filter_by(email="erin@northstar.example").one()
    database_session.commit()
    api_client.get(f"/api/tickets/{ticket.id}/sla")  # First escalation assigns Erin.

    if unavailable_state == "unavailable":
        current_manager.agent_profile.is_available = False
    else:
        current_manager.is_active = False
        login = api_client.post(
            "/api/auth/login",
            json={"email": "nora@northstar.example", "password": "Travel-test-password!45"},
        )
        assert login.status_code == 200
        api_client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    replacement = User(
        agency_id=ticket.agency_id,
        full_name="Sam Escalation",
        email="sam@northstar.example",
        role="escalation_manager",
        is_active=True,
    )
    replacement.agent_profile = AgentProfile(regions=["Global"], is_available=True)
    database_session.add(replacement)
    database_session.commit()

    overview = api_client.get(f"/api/tickets/{ticket.id}/sla").json()
    assert overview["escalation_history"][0]["assigned_to"] == replacement.full_name
    active = (
        database_session.query(Assignment)
        .filter_by(ticket_id=ticket.id, unassigned_at=None)
        .one()
    )
    assert active.user_id == replacement.id
    assert active.id == overview["escalation_history"][0]["assignment_id"]
    assert database_session.query(SLAEscalation).filter_by(ticket_id=ticket.id).count() == 1


def test_subsecond_past_deadline_is_breached_without_truncation(api_client, database_session):
    ticket_data = create_ticket(api_client)
    ticket = database_session.get(Ticket, ticket_data["id"])
    now = datetime.now(timezone.utc)
    ticket.created_at = now - timedelta(hours=8, milliseconds=500)
    database_session.commit()

    sla = evaluate_ticket_sla(database_session, ticket, now=now, auto_escalate=False)
    assert sla.response_status == "breached"
    assert sla.response_remaining_seconds == -1
