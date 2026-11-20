from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    ActivityLog,
    Agency,
    Assignment,
    Conversation,
    Ticket,
    TicketLink,
    User,
)


def test_model_relationships(database_session):
    agency = Agency(name="Northstar Travel", slug="northstar")
    admin = User(
        agency=agency,
        full_name="Alex Admin",
        email="alex@example.test",
        role="admin",
    )
    agent = User(
        agency=agency,
        full_name="Sam Agent",
        email="sam@example.test",
        role="agent",
    )
    first_ticket = Ticket(
        agency=agency,
        created_by=admin,
        reference="OPS-1001",
        subject="Flight schedule changed",
    )
    second_ticket = Ticket(
        agency=agency,
        created_by=admin,
        reference="OPS-1002",
        subject="Traveler needs an update",
    )
    first_ticket.assignments.append(Assignment(user=agent, assigned_by=admin))
    first_ticket.links.append(TicketLink(linked_ticket=second_ticket, link_type="related"))
    first_ticket.conversations.append(
        Conversation(author=agent, body="I am checking the new schedule.")
    )
    first_ticket.activity_logs.append(
        ActivityLog(actor=admin, event_type="ticket.created", summary="Ticket opened")
    )

    database_session.add(first_ticket)
    database_session.commit()

    loaded_ticket = database_session.query(Ticket).filter_by(reference="OPS-1001").one()
    loaded_agency = database_session.query(Agency).filter_by(slug="northstar").one()

    assert loaded_ticket.agency.name == "Northstar Travel"
    assert loaded_ticket.created_by.role == "admin"
    assert loaded_ticket.assignments[0].user.email == "sam@example.test"
    assert loaded_ticket.assignments[0].assigned_by.email == "alex@example.test"
    assert loaded_ticket.links[0].linked_ticket.reference == "OPS-1002"
    assert loaded_ticket.conversations[0].author.email == "sam@example.test"
    assert loaded_ticket.activity_logs[0].actor.email == "alex@example.test"
    assert {ticket.reference for ticket in loaded_agency.tickets} == {"OPS-1001", "OPS-1002"}


def test_role_and_ticket_link_constraints_are_enforced(database_session):
    agency = Agency(name="Northstar Travel", slug="northstar")
    user = User(
        agency=agency,
        full_name="Invalid Role",
        email="invalid@example.test",
        role="owner",
    )
    database_session.add(user)
    with pytest.raises(IntegrityError):
        database_session.commit()
    database_session.rollback()

    agency = Agency(name="Northstar Travel", slug="northstar")
    user = User(agency=agency, full_name="Alex Admin", email="alex@example.test", role="admin")
    ticket = Ticket(agency=agency, created_by=user, reference="OPS-1001", subject="Self link")
    ticket.links.append(TicketLink(linked_ticket=ticket, link_type="related"))
    database_session.add(ticket)
    with pytest.raises(IntegrityError):
        database_session.commit()


def test_assignment_history_timestamp_constraint(database_session):
    agency = Agency(name="Northstar Travel", slug="northstar")
    user = User(agency=agency, full_name="Alex Admin", email="alex@example.test", role="admin")
    ticket = Ticket(agency=agency, created_by=user, reference="OPS-1001", subject="Assignment")
    ticket.assignments.append(
        Assignment(
            user=user,
            assigned_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            unassigned_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    database_session.add(ticket)

    with pytest.raises(IntegrityError):
        database_session.commit()
