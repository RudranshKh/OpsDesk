import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.schemas.insights import (
    ComplaintTheme,
    CountMetric,
    GroupFrequency,
    InsightQuality,
    InsightsRead,
    ThemeExample,
    VolumePoint,
)
from app.db.models import ActivityLog, Conversation, Ticket, TicketSLA

MIN_THEME_TICKETS = 3
MIN_CLUSTER_SIZE = 2
THEME_SIMILARITY = 0.18
TOKEN_RE = re.compile(r"[a-z][a-z0-9]{2,}")
STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been", "before",
    "being", "but", "can", "could", "did", "does", "for", "from", "have", "help",
    "here", "how", "into", "its", "just", "need", "not", "our", "please", "request",
    "she", "should", "that", "their", "there", "these", "they", "this", "ticket", "travel",
    "traveler", "was", "were", "what", "when", "which", "who", "will", "with", "would",
    "your", "booking", "flight", "airline", "customer", "service", "case", "issue",
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _tokens(text: str) -> list[str]:
    return [word for word in TOKEN_RE.findall(text.lower()) if word not in STOP_WORDS]


def _cluster_themes(documents: list[dict]) -> list[ComplaintTheme]:
    if len(documents) < MIN_THEME_TICKETS:
        return []
    frequencies = [Counter(doc["tokens"]) for doc in documents]
    df = Counter()
    for counts in frequencies:
        df.update(counts.keys())
    n = len(documents)
    vectors: list[dict[str, float]] = []
    for counts in frequencies:
        vector = {
            term: (1 + math.log(count)) * (math.log((n + 1) / (df[term] + 1)) + 1)
            for term, count in counts.items()
        }
        norm = math.sqrt(sum(weight * weight for weight in vector.values())) or 1
        vectors.append({term: weight / norm for term, weight in vector.items()})

    parents = list(range(n))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for left in range(n):
        for right in range(left + 1, n):
            score = sum(weight * vectors[right].get(term, 0.0) for term, weight in vectors[left].items())
            if score >= THEME_SIMILARITY:
                root_left, root_right = find(left), find(right)
                if root_left != root_right:
                    parents[root_right] = root_left

    clusters: dict[int, list[int]] = defaultdict(list)
    for index in range(n):
        clusters[find(index)].append(index)

    themes = []
    for indices in clusters.values():
        distinct_tickets = {documents[index]["ticket"].id for index in indices}
        if len(distinct_tickets) < MIN_CLUSTER_SIZE:
            continue
        term_weights: Counter[str] = Counter()
        for index in indices:
            term_weights.update(vectors[index])
        terms = [term for term, _weight in term_weights.most_common(3)]
        if not terms:
            continue
        examples = [
            ThemeExample(
                ticket_id=documents[index]["ticket"].id,
                reference=documents[index]["ticket"].reference,
                subject=documents[index]["ticket"].subject,
                excerpt=documents[index]["text"][:240],
            )
            for index in sorted(indices, key=lambda idx: (-sum(vectors[idx].values()), documents[idx]["ticket"].id))[:3]
        ]
        themes.append(
            ComplaintTheme(
                label=" · ".join(term.title() for term in terms),
                terms=terms,
                ticket_frequency=len(distinct_tickets),
                similarity_threshold=THEME_SIMILARITY,
                examples=examples,
            )
        )
    return sorted(themes, key=lambda theme: (-theme.ticket_frequency, theme.label))


def build_insights(
    db: Session,
    *,
    agency_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    priority: str | None = None,
) -> InsightsRead:
    statement = (
        select(Ticket)
        .where(Ticket.agency_id == agency_id)
        .options(joinedload(Ticket.agency))
        .order_by(Ticket.created_at, Ticket.id)
    )
    if date_from is not None:
        statement = statement.where(
            Ticket.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to is not None:
        statement = statement.where(
            Ticket.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )
    if priority is not None:
        statement = statement.where(Ticket.priority == priority)
    tickets = list(db.scalars(statement).unique().all())
    ticket_ids = [ticket.id for ticket in tickets]
    resolved = [ticket for ticket in tickets if ticket.status in {"resolved", "closed"}]

    conversations = []
    if ticket_ids:
        conversations = list(
            db.scalars(
                select(Conversation)
                .where(Conversation.ticket_id.in_(ticket_ids), Conversation.is_internal.is_(False))
                .order_by(Conversation.created_at, Conversation.id)
            ).all()
        )
    conversations_by_ticket: dict[int, list[str]] = defaultdict(list)
    for conversation in conversations:
        conversations_by_ticket[conversation.ticket_id].append(conversation.body)
    public_conversation_tickets = len(conversations_by_ticket)

    theme_documents = []
    for ticket in resolved:
        pieces = [ticket.subject or "", ticket.description or "", *conversations_by_ticket[ticket.id]]
        text = " ".join(piece.strip() for piece in pieces if piece and piece.strip())
        tokens = _tokens(text)
        if tokens:
            theme_documents.append({"ticket": ticket, "text": text, "tokens": tokens})
    themes = _cluster_themes(theme_documents)

    resolution_times = {ticket.id: ticket.resolved_at for ticket in resolved if ticket.resolved_at is not None}
    if resolved:
        status_events = db.scalars(
            select(ActivityLog)
            .where(
                ActivityLog.ticket_id.in_([ticket.id for ticket in resolved]),
                ActivityLog.event_type == "ticket.status_changed",
            )
            .order_by(ActivityLog.created_at, ActivityLog.id)
        ).all()
        for event in status_events:
            details = event.details or {}
            if details.get("to") in {"resolved", "closed"}:
                resolution_times.setdefault(event.ticket_id, event.created_at)

    resolution_hours = []
    invalid_resolution_count = 0
    for ticket in resolved:
        resolved_at = resolution_times.get(ticket.id)
        if resolved_at is None:
            continue
        elapsed = (_aware(resolved_at) - _aware(ticket.created_at)).total_seconds() / 3600
        if elapsed < 0:
            invalid_resolution_count += 1
        else:
            resolution_hours.append(elapsed)
    average_resolution = sum(resolution_hours) / len(resolution_hours) if resolution_hours else None

    sla_rows = []
    if ticket_ids:
        sla_rows = list(
            db.execute(
                select(TicketSLA.ticket_id, TicketSLA.sla_status).where(TicketSLA.ticket_id.in_(ticket_ids))
            ).all()
        )
    breached_count = sum(1 for _ticket_id, state in sla_rows if state == "breached")

    volume_months: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for ticket in tickets:
        created = _aware(ticket.created_at)
        volume_months[created.strftime("%Y-%m")] += 1
        priority_counts[ticket.priority] += 1
        status_counts[ticket.status] += 1

    agency_counts: Counter[str] = Counter(ticket.agency.name for ticket in resolved)
    area_counts: Counter[str] = Counter(
        ticket.region.strip() for ticket in resolved if ticket.region and ticket.region.strip()
    )

    theme_status = "available" if len(theme_documents) >= MIN_THEME_TICKETS else "insufficient_data"
    if theme_status == "insufficient_data":
        theme_note = f"At least {MIN_THEME_TICKETS} resolved tickets with usable text are needed to infer themes; {len(theme_documents)} available."
    elif themes:
        theme_note = "Themes are inferred from resolved ticket subjects, descriptions, and public conversation text using local TF-IDF similarity."
    else:
        theme_note = "There is enough resolved ticket text, but no cluster met the minimum recurrence and similarity thresholds."
    return InsightsRead(
        date_from=date_from,
        date_to=date_to,
        agency_id=agency_id,
        priority=priority,
        total_tickets=len(tickets),
        resolved_tickets=len(resolved),
        average_resolution_hours=round(average_resolution, 2) if average_resolution is not None else None,
        resolution_time_sample_size=len(resolution_hours),
        sla_breach_rate=round(breached_count / len(sla_rows), 4) if sla_rows else None,
        sla_breached_tickets=breached_count,
        sla_sample_size=len(sla_rows),
        conversation_tickets=public_conversation_tickets,
        volume_over_time=[VolumePoint(period=period, count=count) for period, count in sorted(volume_months.items())],
        priority_breakdown=[CountMetric(label=key, count=priority_counts[key]) for key in ("urgent", "high", "normal", "low") if priority_counts[key]],
        status_breakdown=[CountMetric(label=key, count=status_counts[key]) for key in ("open", "pending", "resolved", "closed") if status_counts[key]],
        agency_issue_frequency=[GroupFrequency(key=key, count=count) for key, count in agency_counts.most_common()],
        operational_area_frequency=[GroupFrequency(key=key, count=count) for key, count in area_counts.most_common()],
        recurring_themes=themes,
        data_quality=InsightQuality(
            theme_status=theme_status,
            theme_note=theme_note,
            resolved_text_sample_size=len(theme_documents),
            public_conversation_ticket_count=public_conversation_tickets,
            resolution_time_sample_size=len(resolution_hours),
            sla_sample_size=len(sla_rows),
            invalid_resolution_timestamp_count=invalid_resolution_count,
        ),
    )
