"""Create a repeatable, local OpsDesk showcase dataset without replacing user data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import getpass
import os

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.init import initialize_database
from app.db.models import (
    ActivityLog,
    AgentProfile,
    Agency,
    Assignment,
    Conversation,
    Ticket,
    TicketLink,
    User,
)
from app.db.session import SessionLocal
from app.services.sla import evaluate_ticket_sla

DEMO_PASSWORD_ENV = "OPSDESK_DEMO_PASSWORD"
MIN_DEMO_PASSWORD_LENGTH = 12


def _get_demo_password() -> str:
    """Read an explicitly configured local seed password without displaying it."""
    password = os.getenv(DEMO_PASSWORD_ENV)
    if password is None:
        try:
            password = getpass.getpass("Local demo account password (minimum 12 characters): ")
            confirmation = getpass.getpass("Confirm local demo account password: ")
        except (EOFError, KeyboardInterrupt) as error:
            raise RuntimeError(
                f"Demo seeding needs {DEMO_PASSWORD_ENV} or an interactive password prompt."
            ) from error
        if password != confirmation:
            raise ValueError("Demo passwords do not match.")

    if len(password) < MIN_DEMO_PASSWORD_LENGTH:
        raise ValueError("Demo password must contain at least 12 characters.")
    return password


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

AGENCIES = (
    ("opsdesk-demo", "OpsDesk Demo Agency"),
    ("meridian-demo", "Meridian Travel Group"),
    ("horizon-demo", "Horizon Business Travel"),
)

# Reference, agency, subject, details, priority, status, area, booking ref,
# age in days for completed records / age in hours for active SLA scenarios,
# resolution hours, resolution note, and travel-deadline offset (from seed time
# for active records, or ticket creation for completed records).
TICKETS = (
    ("DEMO-OPS-001", "opsdesk-demo", "Missed connection after schedule change", "The carrier moved the inbound flight and the traveler may miss the Singapore connection. PNR: ZX81QW. Please confirm protected rerouting.", "urgent", "open", "Asia Pacific", "ZX81QW", 0, 0.17, 0, "", 0),
    ("DEMO-OPS-002", "opsdesk-demo", "Hotel cancellation fee dispute", "The property charged a cancellation fee after the itinerary was changed by the airline. Booking reference: HTL74219. Traveler requests a waiver.", "high", "open", "Europe", "", 0, 1.5, 0, "", 0),
    ("DEMO-OPS-003", "opsdesk-demo", "Refund pending for cancelled flight", "Airline cancellation was confirmed but the refund has not appeared. PNR: ZX81QW. Traveler needs a status update before rebooking.", "normal", "pending", "Asia Pacific", "ZX81QW", 0, 9, 0, "", 0),
    ("DEMO-OPS-004", "opsdesk-demo", "Carrier cancellation refund follow-up", "Carrier cancelled the same itinerary and the traveler is waiting for the refund. PNR: ZX81QW. Please verify the refund reference.", "high", "resolved", "Asia Pacific", "ZX81QW", 3, 0, 5.5, "The carrier confirmed the refund and the traveler received the transaction reference.", 48),
    ("DEMO-OPS-005", "opsdesk-demo", "Delayed baggage delivery", "One checked bag did not arrive at the destination. The baggage desk opened file SGN4821 and delivery to the hotel is requested.", "high", "resolved", "Asia Pacific", "", 5, 0, 8, "The airline located the bag and arranged delivery to the hotel.", 0),
    ("DEMO-OPS-006", "opsdesk-demo", "Wheelchair assistance not on airport record", "Wheelchair assistance was requested during booking but is missing from the airport service record. Flight departs tomorrow morning.", "normal", "closed", "North America", "", 7, 0, 3, "Airport special assistance confirmed the wheelchair request for both flight segments.", 30),
    ("DEMO-OPS-007", "opsdesk-demo", "Hotel overbooking and refund request", "The confirmed room was unavailable on arrival because the hotel overbooked. Booking reference: HTL55X22. Traveler paid for an alternate property.", "urgent", "resolved", "Europe", "HTL55X22", 4, 0, 6, "The hotel reimbursed the alternate stay and confirmed the original reservation was cancelled without penalty.", 0),
    ("DEMO-OPS-008", "opsdesk-demo", "Room unavailable at confirmed property", "Hotel could not provide the booked room and offered a different room category. Booking reference: HTL55X22. Traveler requests a refund for the difference.", "high", "resolved", "Europe", "HTL55X22", 6, 0, 9, "The property refunded the room-category difference and emailed an updated folio.", 0),
    ("DEMO-OPS-009", "opsdesk-demo", "Airport transfer did not arrive", "The pre-booked driver was not at arrivals after the long-haul flight. Transfer voucher TR-88410 is attached to the itinerary.", "normal", "closed", "Europe", "", 12, 0, 2.5, "The transfer desk refunded the missed pickup and arranged a replacement car.", 0),
    ("DEMO-OPS-010", "meridian-demo", "Guest room not ready before check-in", "Traveler has arrived early and the property cannot confirm when the reserved room will be ready. Hotel reference: MDN-43821.", "low", "open", "Middle East", "", 0, 1, 0, "", 2),
    ("DEMO-OPS-011", "meridian-demo", "Urgent ticket reissue after name correction", "The passport name was corrected but the reissued ticket still shows the old spelling. PNR: MR8K2T. Departure is later today.", "urgent", "pending", "Europe", "", 0, 0.08, 0, "", 0),
    ("DEMO-OPS-012", "meridian-demo", "Hotel reservation marked unpaid", "The hotel says the prepaid booking has no payment on file. Confirmation code: QZ33L8. Please send the agency payment receipt.", "high", "resolved", "South Asia", "QZ33L8", 2, 0, 3, "Finance resent the virtual card authorization and the hotel confirmed payment.", 24),
    ("DEMO-OPS-013", "meridian-demo", "Prepaid stay not recognized by hotel", "Front desk cannot locate the prepaid room and is asking the traveler to pay again. Confirmation code: QZ33L8.", "urgent", "resolved", "South Asia", "QZ33L8", 8, 0, 2, "The hotel reconciled the agency voucher and confirmed no additional charge was due.", 0),
    ("DEMO-OPS-014", "meridian-demo", "Airport pickup voucher has wrong terminal", "The transfer voucher lists Terminal 1 but the updated itinerary arrives at Terminal 3. Booking code: MRN-55102.", "normal", "closed", "North America", "", 14, 0, 4, "The supplier updated the pickup terminal and sent the traveler a corrected voucher.", 0),
    ("DEMO-OPS-015", "meridian-demo", "Paid seat assignment missing", "The airline seat map shows no assignment although seats were purchased for the family. PNR: LK5M7P. Please restore adjacent seats.", "high", "resolved", "Europe", "", 18, 0, 7, "The carrier restored adjacent seats and confirmed the paid seat fee remained applied.", 0),
    ("DEMO-OPS-016", "meridian-demo", "Cancelled segment refund not received", "A cancelled domestic segment is still showing as ticketed and the refund has not posted. PNR: AB4N9R.", "normal", "pending", "South Asia", "", 0, 2, 0, "", 0),
    ("DEMO-OPS-017", "meridian-demo", "Passport name correction on hotel booking", "The hotel confirmation has the previous surname while the passport and flight ticket show the updated name. Hotel ref: HZ-90213.", "low", "closed", "Europe", "", 21, 0, 5, "The hotel updated the guest name and reissued the confirmation.", 0),
    ("DEMO-OPS-018", "horizon-demo", "Schedule change threatens client meeting", "A carrier schedule change reduced the connection to 35 minutes. PNR: HZ7P3C. Traveler must arrive before a client meeting.", "high", "open", "North America", "", 0, 0.33, 0, "", 0),
    ("DEMO-OPS-019", "horizon-demo", "Business visa support letter missing", "Consulate appointment is in four days and the employer support letter has not been issued. Traveler needs the approved company itinerary.", "high", "resolved", "South Asia", "", 9, 0, 18, "The travel desk issued the signed support letter and confirmed the appointment checklist.", 0),
    ("DEMO-OPS-020", "horizon-demo", "Hotel air conditioning outage", "The assigned room has no working air conditioning and the property cannot offer another room. Confirmation: HZ-66420.", "normal", "resolved", "Middle East", "", 11, 0, 10, "The property moved the traveler to a working room and waived the first night.", 0),
    ("DEMO-OPS-021", "horizon-demo", "Baggage fee charged twice", "The carrier charged the same checked-bag fee at online check-in and again at the airport. Receipt total is duplicated.", "low", "closed", "North America", "", 27, 0, 12, "The carrier reversed the duplicate baggage fee and sent a receipt by email.", 0),
    ("DEMO-OPS-022", "horizon-demo", "Overbooked hotel cannot honor room type", "The property is sold out and cannot provide the accessible room confirmed on the itinerary. Booking reference: HZ-77104.", "high", "pending", "Europe", "", 0, 1.6, 0, "", 0),
    ("DEMO-OPS-023", "horizon-demo", "Airline cancellation requires alternate routing", "The airline cancelled the first leg and the replacement itinerary misses the onward connection. PNR: HZ9D2F.", "urgent", "resolved", "North America", "", 13, 0, 3, "The airline protected the onward connection and issued the replacement itinerary.", 0),
    ("DEMO-OPS-024", "horizon-demo", "Missed connection after inbound delay", "Inbound delay caused a missed connection and the traveler was rebooked overnight. PNR: HZ9D2F. Hotel and meal support are requested.", "urgent", "resolved", "North America", "", 16, 0, 4, "The carrier provided hotel and meal vouchers and confirmed the next-day connection.", 0),
    ("DEMO-OPS-025", "horizon-demo", "Multi-city booking has duplicate segment", "The final itinerary contains two copies of the Singapore to Sydney segment. PNR: HZ3T8V. Please verify ticket coupons before travel.", "normal", "closed", "Asia Pacific", "", 35, 0, 9, "Ticketing removed the duplicate segment and confirmed the corrected fare calculation.", 0),
)


def _ensure_user(
    session, agency: Agency, email: str, name: str, role: str, demo_password: str
) -> tuple[User, bool]:
    user = session.scalar(select(User).where(User.email == email))
    created = user is None
    if user is None:
        user = User(
            agency_id=agency.id,
            full_name=name,
            email=email,
            role=role,
            password_hash=hash_password(demo_password),
        )
        session.add(user)
        session.flush()
    elif user.agency_id != agency.id or user.role != role:
        raise RuntimeError(
            f"Demo account collision for {email}: existing agency or role differs; no user data was changed."
        )
    elif user.password_hash is None:
        # Initialize the absent credential once; never replace an existing password hash.
        user.password_hash = hash_password(demo_password)
    if role in {"agent", "escalation_manager"} and user.agent_profile is None:
        user.agent_profile = AgentProfile(regions=["Global"], is_available=True)
    return user, created


def _ensure_conversation(session, ticket: Ticket, author: User, body: str, created_at: datetime, is_internal: bool = False) -> None:
    existing = session.scalar(
        select(Conversation.id).where(
            Conversation.ticket_id == ticket.id,
            Conversation.author_id == author.id,
            Conversation.body == body,
            Conversation.is_internal.is_(is_internal),
        )
    )
    if existing is None:
        session.add(
            Conversation(
                ticket_id=ticket.id,
                author_id=author.id,
                body=body,
                is_internal=is_internal,
                created_at=created_at,
                updated_at=created_at,
            )
        )


def _ensure_activity(session, ticket: Ticket, actor: User, event_type: str, summary: str, details: dict, created_at: datetime) -> None:
    existing = session.scalar(
        select(ActivityLog.id).where(
            ActivityLog.ticket_id == ticket.id,
            ActivityLog.event_type == event_type,
            ActivityLog.summary == summary,
        )
    )
    if existing is None:
        session.add(
            ActivityLog(
                ticket_id=ticket.id,
                actor_id=actor.id,
                event_type=event_type,
                summary=summary,
                details=details,
                created_at=created_at,
            )
        )


def _ensure_assignment(session, ticket: Ticket, agent: User, admin: User, assigned_at: datetime) -> None:
    active = session.scalar(
        select(Assignment.id).where(
            Assignment.ticket_id == ticket.id,
            Assignment.unassigned_at.is_(None),
        )
    )
    if active is None:
        session.add(
            Assignment(
                ticket_id=ticket.id,
                user_id=agent.id,
                assigned_by_id=admin.id,
                assigned_at=assigned_at,
                routing_explanation="Demo assignment for showcasing the OpsDesk workflow.",
            )
        )


def _ensure_link(session, source: Ticket, target: Ticket) -> None:
    existing = session.scalar(
        select(TicketLink.id).where(
            TicketLink.link_type == "related",
            or_(
                (TicketLink.ticket_id == source.id) & (TicketLink.linked_ticket_id == target.id),
                (TicketLink.ticket_id == target.id) & (TicketLink.linked_ticket_id == source.id),
            ),
        )
    )
    if existing is None:
        session.add(TicketLink(ticket_id=source.id, linked_ticket_id=target.id, link_type="related"))


def seed_demo_data(session_factory=SessionLocal, database_engine=None) -> None:
    """Seed local SQLite only; production seeding is disabled."""
    if settings.app_env in {"production", "prod"}:
        raise RuntimeError("Demo seeding is disabled when APP_ENV is production.")

    if database_engine is None:
        if not settings.database_url.startswith("sqlite"):
            raise RuntimeError("The OpsDesk demo dataset is intended for local SQLite development only.")
    else:
        if database_engine.dialect.name != "sqlite":
            raise RuntimeError("The OpsDesk demo dataset is intended for local SQLite development only.")

    demo_password = _get_demo_password()
    if database_engine is None:
        initialize_database()
    else:
        initialize_database(database_engine)
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        agencies: dict[str, Agency] = {}
        for slug, name in AGENCIES:
            agency = session.scalar(select(Agency).where(Agency.slug == slug))
            if agency is None:
                agency = Agency(name=name, slug=slug)
                session.add(agency)
                session.flush()
            agencies[slug] = agency

        agents: dict[str, list[User]] = {}
        admins: dict[str, User] = {}
        managers: dict[str, User] = {}
        new_users = 0
        for index, (slug, _name) in enumerate(AGENCIES):
            if index == 0:
                people = (
                    ("agent@opsdesk.local", "Alex Morgan", "agent"),
                    ("agent2@opsdesk.local", "Jamie Chen", "agent"),
                    ("manager@opsdesk.local", "Erin Patel", "escalation_manager"),
                    ("admin@opsdesk.local", "Nora Williams", "admin"),
                )
            else:
                domain = f"{slug}.local"
                people = (
                    (f"agent1@{domain}", "Taylor Singh", "agent"),
                    (f"agent2@{domain}", "Morgan Lee", "agent"),
                    (f"manager@{domain}", "Casey Rivera", "escalation_manager"),
                    (f"admin@{domain}", "Jordan Brooks", "admin"),
                )
            users = []
            for email, name, role in people:
                user, created = _ensure_user(
                    session, agencies[slug], email, name, role, demo_password
                )
                new_users += int(created)
                if role == "agent":
                    users.append(user)
                elif role == "admin":
                    admins[slug] = user
                elif role == "escalation_manager":
                    managers[slug] = user
            agents[slug] = users
        session.commit()

        tickets: dict[str, Ticket] = {}
        created_tickets = 0
        for row in TICKETS:
            (reference, slug, subject, description, priority, status, region, booking_ref, age_days, age_hours, duration_hours, resolution_note, travel_hours) = row
            if age_hours:
                created_at = now - timedelta(hours=age_hours)
            else:
                created_at = now - timedelta(days=age_days)
            resolved_at = created_at + timedelta(hours=duration_hours) if status in {"resolved", "closed"} else None
            ticket = session.scalar(select(Ticket).where(Ticket.reference == reference))
            if ticket is None:
                travel_base = created_at if status in {"resolved", "closed"} else now
                travel_at = travel_base + timedelta(hours=travel_hours) if travel_hours else None
                if booking_ref and booking_ref.casefold() not in description.casefold():
                    description = f"{description} Booking reference: {booking_ref}."
                ticket = Ticket(
                    reference=reference,
                    agency_id=agencies[slug].id,
                    created_by_id=agents[slug][0].id,
                    subject=subject,
                    description=description,
                    region=region,
                    check_in_at=travel_at if travel_hours and reference == "DEMO-OPS-010" else None,
                    departure_at=travel_at if travel_hours and reference != "DEMO-OPS-010" else None,
                    priority=priority,
                    status=status,
                    created_at=created_at,
                    updated_at=resolved_at or created_at,
                    resolved_at=resolved_at,
                )
                session.add(ticket)
                session.flush()
                created_tickets += 1
                _ensure_activity(
                    session,
                    ticket,
                    admins[slug],
                    "demo.seeded_ticket",
                    "Created by the OpsDesk demo dataset.",
                    {"seed": "opsdesk-demo-v1"},
                    created_at,
                )
            else:
                marker = session.scalar(
                    select(ActivityLog.id).where(
                        ActivityLog.ticket_id == ticket.id,
                        ActivityLog.event_type == "demo.seeded_ticket",
                    )
                )
                if ticket.agency_id != agencies[slug].id or marker is None:
                    raise RuntimeError(f"Ticket reference collision for {reference}; existing ticket was not changed.")
            tickets[reference] = ticket

            assigned_agent = agents[slug][int(reference[-3:]) % len(agents[slug])]
            actual_created_at = _aware(ticket.created_at)
            _ensure_assignment(session, ticket, assigned_agent, admins[slug], actual_created_at + timedelta(minutes=4))
            if ticket.status in {"resolved", "closed"} and ticket.resolved_at is not None:
                actual_resolved_at = _aware(ticket.resolved_at)
                response_at = min(actual_resolved_at, actual_created_at + timedelta(minutes=18 + (ticket.id % 13)))
                _ensure_conversation(
                    session,
                    ticket,
                    assigned_agent,
                    f"We coordinated with the airline or travel supplier. Resolution: {resolution_note}",
                    response_at,
                )
                _ensure_activity(
                    session,
                    ticket,
                    admins[slug],
                    "ticket.status_changed",
                    f"Ticket status changed from pending to {ticket.status}.",
                    {"from": "pending", "to": ticket.status},
                    actual_resolved_at,
                )
            elif ticket.status == "pending" and reference in {"DEMO-OPS-003", "DEMO-OPS-016"}:
                _ensure_conversation(
                    session,
                    ticket,
                    assigned_agent,
                    "We have contacted the carrier and are waiting for written confirmation before changing the itinerary.",
                    now - timedelta(minutes=5),
                    is_internal=True,
                )

        session.flush()
        for left, right in (
            ("DEMO-OPS-003", "DEMO-OPS-004"),
            ("DEMO-OPS-007", "DEMO-OPS-008"),
            ("DEMO-OPS-012", "DEMO-OPS-013"),
            ("DEMO-OPS-023", "DEMO-OPS-024"),
        ):
            _ensure_link(session, tickets[left], tickets[right])

        for _reference, ticket in tickets.items():
            evaluate_ticket_sla(session, ticket, now=now)
        session.commit()

    print(f"Demo workspace ready: {len(AGENCIES)} agencies, {new_users} new accounts, {created_tickets} new tickets.")
    print("Primary logins: agent@opsdesk.local / manager@opsdesk.local / admin@opsdesk.local")


if __name__ == "__main__":
    seed_demo_data()
