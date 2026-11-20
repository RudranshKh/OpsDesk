"""Provision a reserved, isolated demo workspace for public demo login."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.models import AgentProfile, Agency, Assignment, Conversation, Ticket, User
from app.services.sla import evaluate_ticket_sla

DEMO_AGENCY_NAME = "OpsDesk Public Demo"
DEMO_AGENCY_SLUG = "opsdesk-public-demo"
DEMO_USER_EMAIL = "demo@opsdesk-demo.invalid"
DEMO_AGENT_EMAILS = (
    "agent1@opsdesk-demo.invalid",
    "agent2@opsdesk-demo.invalid",
)


def _ensure_agency(db: Session) -> Agency:
    agency = db.scalar(select(Agency).where(Agency.slug == DEMO_AGENCY_SLUG))
    if agency is None:
        agency = Agency(name=DEMO_AGENCY_NAME, slug=DEMO_AGENCY_SLUG, is_demo=True)
        db.add(agency)
        db.flush()
    elif not agency.is_demo:
        raise RuntimeError("Reserved demo agency slug is already owned by a non-demo workspace.")
    return agency


def _ensure_user(
    db: Session,
    *,
    agency: Agency,
    email: str,
    full_name: str,
    role: str,
    regions: list[str],
) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            agency_id=agency.id,
            full_name=full_name,
            email=email,
            role=role,
            password_hash=None,
            is_active=True,
        )
        db.add(user)
        db.flush()
    elif user.agency_id != agency.id or user.role != role or not user.is_active:
        raise RuntimeError("Reserved demo account identity conflicts with an existing account.")

    profile = user.agent_profile
    if profile is None:
        user.agent_profile = AgentProfile(regions=regions, is_available=True)
    return user


def _ensure_ticket(
    db: Session,
    *,
    agency: Agency,
    creator: User,
    reference: str,
    subject: str,
    description: str,
    priority: str,
    status: str,
    region: str,
    created_at: datetime,
    resolved_at: datetime | None = None,
    departure_at: datetime | None = None,
) -> Ticket:
    ticket = db.scalar(select(Ticket).where(Ticket.reference == reference))
    if ticket is not None:
        if ticket.agency_id != agency.id:
            raise RuntimeError("Reserved demo ticket reference is already owned by another agency.")
        return ticket

    ticket = Ticket(
        reference=reference,
        agency_id=agency.id,
        created_by_id=creator.id,
        subject=subject,
        description=description,
        region=region,
        priority=priority,
        status=status,
        created_at=created_at,
        updated_at=resolved_at or created_at,
        resolved_at=resolved_at,
        departure_at=departure_at,
    )
    db.add(ticket)
    db.flush()
    return ticket


def _ensure_resolved_conversation(
    db: Session, *, ticket: Ticket, author: User, body: str
) -> None:
    exists = db.scalar(
        select(Conversation.id).where(
            Conversation.ticket_id == ticket.id,
            Conversation.author_id == author.id,
            Conversation.body == body,
            Conversation.is_internal.is_(False),
        )
    )
    if exists is None:
        created_at = ticket.resolved_at or ticket.created_at
        db.add(
            Conversation(
                ticket_id=ticket.id,
                author_id=author.id,
                body=body,
                is_internal=False,
                created_at=created_at,
                updated_at=created_at,
            )
        )


def _provision_once(db: Session) -> User:
    now = datetime.now(timezone.utc)
    agency = _ensure_agency(db)
    demo_user = _ensure_user(
        db,
        agency=agency,
        email=DEMO_USER_EMAIL,
        full_name="OpsDesk Demo User",
        role="escalation_manager",
        regions=["Global"],
    )
    agents = [
        _ensure_user(
            db,
            agency=agency,
            email=DEMO_AGENT_EMAILS[0],
            full_name="Demo Agent North",
            role="agent",
            regions=["Asia Pacific", "Europe"],
        ),
        _ensure_user(
            db,
            agency=agency,
            email=DEMO_AGENT_EMAILS[1],
            full_name="Demo Agent Global",
            role="agent",
            regions=["Global"],
        ),
    ]

    shared_reference = "ODDEMO-7254"
    open_ticket = _ensure_ticket(
        db,
        agency=agency,
        creator=demo_user,
        reference="PUBDEMO-001",
        subject="Hotel refund pending after booking cancellation",
        description=f"The property has not returned the deposit after cancellation. Booking reference: {shared_reference}. The traveler needs an update.",
        priority="high",
        status="open",
        region="Asia Pacific",
        created_at=now - timedelta(hours=1),
    )
    pending_ticket = _ensure_ticket(
        db,
        agency=agency,
        creator=demo_user,
        reference="PUBDEMO-002",
        subject="Cancellation refund not received from hotel",
        description=f"The hotel cancellation was confirmed but its deposit is still missing. Booking reference: {shared_reference}.",
        priority="normal",
        status="pending",
        region="Asia Pacific",
        created_at=now - timedelta(hours=4),
    )

    resolved_specs = (
        (
            "PUBDEMO-003",
            "Airline cancellation refund is delayed",
            "The airline cancelled the flight and the ticket refund has not arrived. The traveler is waiting for the cancellation refund.",
            "The carrier confirmed the refund and provided a transaction reference.",
        ),
        (
            "PUBDEMO-004",
            "Refund still missing after cancelled flight",
            "After the flight cancellation, the ticket refund remains pending. The traveler needs confirmation of the refund status.",
            "The airline completed the refund and sent the confirmation to the traveler.",
        ),
        (
            "PUBDEMO-005",
            "Follow-up on delayed airline refund",
            "The cancelled flight refund has not reached the traveler. Please check the airline refund status and share an update.",
            "The carrier located the refund and confirmed its payment date.",
        ),
    )
    resolved_tickets = []
    for index, (reference, subject, description, resolution) in enumerate(resolved_specs):
        created_at = now - timedelta(days=12 - index * 2)
        resolved_at = created_at + timedelta(hours=5 + index)
        resolved = _ensure_ticket(
            db,
            agency=agency,
            creator=demo_user,
            reference=reference,
            subject=subject,
            description=description,
            priority="normal",
            status="resolved",
            region="Europe",
            created_at=created_at,
            resolved_at=resolved_at,
        )
        _ensure_resolved_conversation(
            db,
            ticket=resolved,
            author=agents[index % len(agents)],
            body=resolution,
        )
        resolved_tickets.append(resolved)

    travel_ticket = _ensure_ticket(
        db,
        agency=agency,
        creator=demo_user,
        reference="PUBDEMO-006",
        subject="Urgent rebooking before departure",
        description="A schedule change shortened the connection and the traveler needs an alternate itinerary.",
        priority="urgent",
        status="open",
        region="Europe",
        created_at=now,
        departure_at=now + timedelta(hours=2),
    )

    active_assignment = db.scalar(
        select(Assignment.id).where(
            Assignment.ticket_id == open_ticket.id,
            Assignment.unassigned_at.is_(None),
        )
    )
    if active_assignment is None:
        db.add(
            Assignment(
                ticket_id=open_ticket.id,
                user_id=agents[0].id,
                assigned_by_id=demo_user.id,
                assigned_at=now - timedelta(minutes=10),
                routing_explanation="Initial assignment in the isolated demo workspace.",
            )
        )

    for ticket in (open_ticket, pending_ticket, travel_ticket, *resolved_tickets):
        evaluate_ticket_sla(db, ticket, now=now, auto_escalate=False)
    return demo_user


def provision_demo_user(db: Session) -> User:
    """Idempotently ensure demo records, tolerating a concurrent first login."""
    for attempt in range(2):
        try:
            user = _provision_once(db)
            db.commit()
            return user
        except IntegrityError:
            db.rollback()
            if attempt:
                raise
        except OperationalError as error:
            db.rollback()
            is_sqlite_lock = "locked" in str(error).casefold()
            if not is_sqlite_lock or attempt:
                raise
    raise RuntimeError("Demo workspace provisioning did not complete.")
