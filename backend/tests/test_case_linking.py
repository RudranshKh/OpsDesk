from app.db.models import Ticket
from app.services.case_linking import find_related_tickets


def make_ticket(ticket_id: int, subject: str, description: str | None = None) -> Ticket:
    return Ticket(
        id=ticket_id,
        agency_id=1,
        reference=f"OPS-{ticket_id:04d}",
        created_by_id=1,
        subject=subject,
        description=description,
        status="open",
        priority="normal",
    )


def test_exact_booking_reference_is_matched_first():
    source = make_ticket(
        1,
        "Flight cancellation",
        "The airline cancelled the trip. PNR: ZX81QW",
    )
    exact = make_ticket(2, "Hotel question", "Booking reference ZX81QW needs a new itinerary.")
    text_match = make_ticket(3, "Flight cancellation and rebooking", "Airline cancelled trip.")

    matches = find_related_tickets(source, [text_match, exact])

    assert [match.ticket.id for match in matches] == [2, 3]
    assert matches[0].match_type == "booking_reference"
    assert matches[0].similarity_score == 1.0
    assert "ZX81QW" in matches[0].explanation


def test_tfidf_cosine_finds_similar_ticket_content():
    source = make_ticket(
        1,
        "Flight cancellation and rebooking in Singapore",
        "The airline cancelled the evening flight from Delhi to Singapore. Please arrange a hotel and rebooking.",
    )
    similar = make_ticket(
        2,
        "Rebook cancelled evening flight to Singapore",
        "The Delhi flight was cancelled by the airline. Arrange a hotel stay and rebooking for the traveler.",
    )

    matches = find_related_tickets(source, [similar])

    assert len(matches) == 1
    assert matches[0].ticket.id == 2
    assert matches[0].match_type == "content"
    assert 0.18 <= matches[0].similarity_score < 1.0
    assert "Similar ticket wording" in matches[0].explanation


def test_unrelated_ticket_is_not_suggested():
    source = make_ticket(1, "Flight cancellation and rebooking", "Airline cancelled the trip from Delhi.")
    unrelated = make_ticket(
        2,
        "Passport renewal appointment",
        "Schengen visa documents are due before the summer conference.",
    )

    assert find_related_tickets(source, [unrelated]) == []
