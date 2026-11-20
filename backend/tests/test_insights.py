from datetime import datetime, timedelta, timezone

from app.db.models import Conversation, Ticket, TicketSLA


def make_resolved(api_client, database_session, subject, description, *, priority="normal", region="Europe", created=None, hours=4):
    response = api_client.post(
        "/api/tickets",
        json={"subject": subject, "description": description, "priority": priority, "region": region},
    )
    assert response.status_code == 201
    ticket_id = response.json()["id"]
    created = created or datetime(2025, 1, 2, 10, tzinfo=timezone.utc)
    ticket = database_session.get(Ticket, ticket_id)
    ticket.created_at = created
    ticket.status = "resolved"
    ticket.resolved_at = created + timedelta(hours=hours)
    sla = database_session.get(TicketSLA, ticket_id)
    sla.sla_status = "breached" if hours >= 8 else "on_track"
    database_session.commit()
    return ticket_id


def test_insights_measure_volume_resolution_sla_and_infer_recurring_themes(api_client, database_session):
    first = make_resolved(
        api_client, database_session, "Hotel overbooking and refund", "Hotel confirmed the room but had no room available; traveler requests a refund.", priority="high", hours=4
    )
    second = make_resolved(
        api_client, database_session, "Room unavailable at hotel", "Hotel overbooked the reservation and the traveler needs a refund for the missing room.", priority="normal", hours=6
    )
    third = make_resolved(
        api_client, database_session, "Hotel reservation not honored", "The hotel had overbooked and could not provide the room. Please arrange a refund.", priority="urgent", hours=10
    )
    database_session.add_all([
        Conversation(ticket_id=first, author_id=1, body="The hotel had no room and refund is still pending."),
        Conversation(ticket_id=first, author_id=2, body="internal_only_private phrase", is_internal=True),
        Conversation(ticket_id=second, author_id=1, body="Please check hotel room availability and refund."),
    ])
    database_session.commit()

    response = api_client.get("/api/insights", params={"date_from": "2025-01-01", "date_to": "2025-01-31"})
    assert response.status_code == 200
    insights = response.json()
    assert insights["total_tickets"] == 3
    assert insights["resolved_tickets"] == 3
    assert insights["average_resolution_hours"] == round((4 + 6 + 10) / 3, 2)
    assert insights["sla_sample_size"] == 3
    assert insights["sla_breach_rate"] == round(1 / 3, 4)
    assert insights["data_quality"]["public_conversation_ticket_count"] == 2
    assert insights["recurring_themes"]
    theme = insights["recurring_themes"][0]
    assert theme["evidence_kind"] == "inferred"
    assert theme["ticket_frequency"] >= 2
    assert theme["examples"]
    assert all("internal_only_private" not in item["excerpt"] for item in theme["examples"])
    assert insights["agency_issue_frequency"][0]["key"] == "Northstar Travel"
    assert insights["operational_area_frequency"][0] == {"key": "Europe", "count": 3}
    example_ids = {item["ticket_id"] for item in theme["examples"]}
    assert example_ids.issubset({first, second, third})

    filtered = api_client.get("/api/insights", params={"date_from": "2025-01-01", "date_to": "2025-01-31", "priority": "urgent"})
    assert filtered.status_code == 200
    assert filtered.json()["total_tickets"] == 1
    assert filtered.json()["resolved_tickets"] == 1


def test_insights_report_insufficient_theme_and_resolution_data(api_client, database_session):
    ticket_id = make_resolved(api_client, database_session, "Unusual one-off request", "No matching travel complaint.")
    ticket = database_session.get(Ticket, ticket_id)
    ticket.resolved_at = None
    database_session.delete(database_session.get(TicketSLA, ticket_id))
    database_session.commit()

    response = api_client.get("/api/insights")
    assert response.status_code == 200
    insights = response.json()
    assert insights["data_quality"]["theme_status"] == "insufficient_data"
    assert "At least 3" in insights["data_quality"]["theme_note"]
    assert insights["recurring_themes"] == []
    assert insights["average_resolution_hours"] is None
    assert insights["resolution_time_sample_size"] == 0
    assert insights["sla_breach_rate"] is None


def test_insights_enforce_agency_scope_and_date_validation(api_client):
    assert api_client.get("/api/insights", params={"agency_id": 2}).status_code == 403
    assert api_client.get("/api/insights", params={"date_from": "2025-02-01", "date_to": "2025-01-01"}).status_code == 422
