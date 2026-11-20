from app.db.models import Ticket


def ticket_payload():
    return {
        "subject": "Flight schedule changed",
        "description": "The departure time moved by two hours.",
        "priority": "high",
    }


def test_create_view_filter_and_update_ticket_workflow(api_client):
    created = api_client.post("/api/tickets", json=ticket_payload())
    assert created.status_code == 201
    ticket = created.json()
    ticket_id = ticket["id"]
    assert ticket["reference"].startswith("OPS-")
    assert ticket["status"] == "open"
    assert ticket["agency_name"] == "Northstar Travel"

    detail = api_client.get(f"/api/tickets/{ticket_id}")
    assert detail.status_code == 200
    assert detail.json()["subject"] == "Flight schedule changed"

    filtered = api_client.get("/api/tickets", params={"status": "open", "priority": "high"})
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [ticket_id]

    updated = api_client.patch(
        f"/api/tickets/{ticket_id}",
        json={"status": "pending", "priority": "urgent", "subject": "Rebook traveler"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "pending"
    assert updated.json()["priority"] == "urgent"
    assert updated.json()["subject"] == "Rebook traveler"

    refreshed = api_client.get("/api/tickets", params={"status": "pending", "q": "rebook"})
    assert [item["id"] for item in refreshed.json()] == [ticket_id]
    assert api_client.get("/api/tickets", params={"status": "open"}).json() == []


def test_ticket_pagination_reports_exact_filtered_total(api_client):
    ids = [api_client.post("/api/tickets", json={**ticket_payload(), "subject": f"Page item {i}"}).json()["id"] for i in range(3)]

    first_page = api_client.get("/api/tickets", params={"limit": 2, "offset": 0})
    second_page = api_client.get("/api/tickets", params={"limit": 2, "offset": 2})
    filtered = api_client.get("/api/tickets", params={"q": "Page item", "limit": 1, "offset": 1})

    assert first_page.status_code == second_page.status_code == filtered.status_code == 200
    assert first_page.headers["X-Total-Count"] == "3"
    assert second_page.headers["X-Total-Count"] == "3"
    ordered_ids = list(reversed(ids))
    assert [item["id"] for item in first_page.json()] == ordered_ids[:2]
    assert [item["id"] for item in second_page.json()] == ordered_ids[2:]
    assert filtered.headers["X-Total-Count"] == "3"
    assert [item["id"] for item in filtered.json()] == ordered_ids[1:2]


def test_ticket_summary_is_agency_scoped_and_accurate(api_client, login_as):
    api_client.post("/api/tickets", json={**ticket_payload(), "priority": "urgent"})
    api_client.post("/api/tickets", json={**ticket_payload(), "priority": "normal"})

    own_summary = api_client.get("/api/tickets/summary")
    assert own_summary.status_code == 200
    assert own_summary.json() == {"total": 2, "open": 2, "pending": 0, "urgent": 1}

    assert login_as("owen@southwind.example").status_code == 200
    other_summary = api_client.get("/api/tickets/summary")
    assert other_summary.status_code == 200
    assert other_summary.json() == {"total": 0, "open": 0, "pending": 0, "urgent": 0}


def test_ticket_creation_rejects_caller_supplied_identity(api_client):
    forged_identity = {**ticket_payload(), "agency_id": 2, "created_by_id": 4}
    assert api_client.post("/api/tickets", json=forged_identity).status_code == 422


def test_ticket_creation_rolls_back_when_initial_sla_response_fails(
    api_client, database_session, monkeypatch
):
    from fastapi import HTTPException

    import app.api.routes.tickets as ticket_routes

    def fail_sla_evaluation(*_args, **_kwargs):
        raise HTTPException(status_code=503, detail="SLA evaluation unavailable")

    monkeypatch.setattr(ticket_routes, "evaluate_ticket_sla", fail_sla_evaluation)
    before_count = database_session.query(Ticket).count()

    response = api_client.post("/api/tickets", json=ticket_payload())

    assert response.status_code == 503
    assert database_session.query(Ticket).count() == before_count


def test_ticket_api_validation_and_not_found_errors(api_client):
    invalid_payload = {**ticket_payload(), "subject": "   ", "priority": "critical"}
    assert api_client.post("/api/tickets", json=invalid_payload).status_code == 422
    assert api_client.get("/api/tickets/999").status_code == 404
    assert api_client.patch("/api/tickets/999", json={"status": "closed"}).status_code == 404
    assert api_client.patch("/api/tickets/1", json={"status": "unknown"}).status_code == 422
    assert api_client.patch("/api/tickets/1", json={}).status_code == 422


def test_ticket_directory_options_are_loaded_from_database(api_client):
    agencies = api_client.get("/api/agencies")
    users = api_client.get("/api/users", params={"agency_id": 1})

    assert agencies.status_code == 200
    assert agencies.json() == [{"id": 1, "name": "Northstar Travel"}]
    assert users.status_code == 200
    assert users.json()[0]["full_name"] == "Alex Morgan"
    assert users.json()[0]["role"] == "agent"


def test_related_ticket_suggestions_are_only_linked_after_confirmation(api_client):
    source_payload = {
        **ticket_payload(),
        "subject": "Flight cancellation",
        "description": "Airline cancelled the trip. PNR: ZX81QW",
    }
    match_payload = {
        **ticket_payload(),
        "subject": "New itinerary needed",
        "description": "Please arrange an update for booking reference ZX81QW.",
    }
    source = api_client.post("/api/tickets", json=source_payload).json()
    candidate = api_client.post("/api/tickets", json=match_payload).json()

    suggestions = api_client.get(f"/api/tickets/{source['id']}/related")
    assert suggestions.status_code == 200
    assert suggestions.json()[0]["id"] == candidate["id"]
    assert suggestions.json()[0]["match_type"] == "booking_reference"
    assert suggestions.json()[0]["is_linked"] is False

    confirmation = api_client.post(
        f"/api/tickets/{source['id']}/links",
        json={"linked_ticket_id": candidate["id"]},
    )
    assert confirmation.status_code == 201
    assert confirmation.json()["link_type"] == "related"

    linked = api_client.get(f"/api/tickets/{source['id']}/related")
    assert linked.json()[0]["is_linked"] is True
    assert api_client.post(
        f"/api/tickets/{source['id']}/links",
        json={"linked_ticket_id": candidate["id"]},
    ).status_code == 409


def test_cross_agency_users_and_tickets_are_isolated(api_client, login_as):
    ticket = api_client.post("/api/tickets", json=ticket_payload()).json()

    assert login_as("owen@southwind.example").status_code == 200
    assert api_client.get("/api/tickets").json() == []
    assert api_client.get(f"/api/tickets/{ticket['id']}").status_code == 404
    assert api_client.get("/api/users", params={"agency_id": 1}).status_code == 403


def test_agent_can_update_only_tickets_assigned_to_them(api_client, login_as):
    ticket = api_client.post(
        "/api/tickets", json={**ticket_payload(), "priority": "normal", "region": "North America"}
    ).json()
    assert login_as("alex@northstar.example").status_code == 200

    forbidden = api_client.patch(f"/api/tickets/{ticket['id']}", json={"status": "pending"})
    assert forbidden.status_code == 403

    assert login_as("erin@northstar.example").status_code == 200
    assignment = api_client.post(f"/api/tickets/{ticket['id']}/assign")
    assert assignment.status_code == 200
    assert login_as("alex@northstar.example").status_code == 200
    updated = api_client.patch(f"/api/tickets/{ticket['id']}", json={"status": "pending"})
    assert updated.status_code == 200
