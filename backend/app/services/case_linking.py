import math
import re
from collections import Counter
from dataclasses import dataclass

from app.db.models import Ticket

MIN_CONTENT_SIMILARITY = 0.18

BOOKING_REFERENCE_PATTERN = re.compile(
    r"(?:\bPNR\b|\bbooking\s+(?:reference|ref(?:erence)?|number|no\.?|id|code)\b|"
    r"\breservation\s+(?:reference|ref|number|code)\b)"
    r"\s*(?:(?:is|:|#|no\.?)\s*)?([A-Z0-9][A-Z0-9-]{3,19})",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
STOP_WORDS = {
    "a", "about", "after", "and", "are", "as", "at", "be", "been", "before",
    "but", "by", "can", "for", "from", "has", "have", "he", "her", "his",
    "i", "in", "is", "it", "its", "me", "my", "of", "on", "or", "our",
    "she", "that", "the", "their", "them", "there", "they", "this", "to",
    "was", "we", "were", "will", "with", "you", "your", "booking", "reference",
    "ticket", "traveler", "travel", "case",
}


@dataclass(frozen=True)
class RelatedMatch:
    ticket: Ticket
    similarity_score: float
    explanation: str
    match_type: str


def _ticket_text(ticket: Ticket) -> str:
    return f"{ticket.subject or ''} {ticket.description or ''}"


def _booking_references(text: str) -> set[str]:
    return {match.group(1).strip("-").upper() for match in BOOKING_REFERENCE_PATTERN.finditer(text)}


def _tokens(text: str) -> list[str]:
    return [token for token in TOKEN_PATTERN.findall(text.lower()) if token not in STOP_WORDS]


def _tfidf_vectors(documents: list[list[str]]) -> list[dict[str, float]]:
    frequencies = [Counter(document) for document in documents]
    document_frequency: Counter[str] = Counter()
    for document in frequencies:
        document_frequency.update(document.keys())

    document_count = len(documents)
    vectors: list[dict[str, float]] = []
    for term_counts in frequencies:
        vector = {}
        for term, count in term_counts.items():
            term_frequency = 1 + math.log(count)
            inverse_document_frequency = math.log(
                (document_count + 1) / (document_frequency[term] + 1)
            ) + 1
            vector[term] = term_frequency * inverse_document_frequency
        vectors.append(vector)
    return vectors


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
    right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    dot_product = sum(weight * right.get(term, 0.0) for term, weight in left.items())
    return dot_product / (left_norm * right_norm)


def find_related_tickets(
    ticket: Ticket,
    candidates: list[Ticket],
    *,
    min_similarity: float = MIN_CONTENT_SIMILARITY,
) -> list[RelatedMatch]:
    """Rank exact labeled booking references before TF-IDF content matches."""
    source_text = _ticket_text(ticket)
    source_references = _booking_references(source_text)
    exact_matches: list[RelatedMatch] = []
    text_candidates: list[Ticket] = []

    for candidate in candidates:
        candidate_references = _booking_references(_ticket_text(candidate))
        shared_references = sorted(source_references & candidate_references)
        if shared_references:
            reference = shared_references[0]
            exact_matches.append(
                RelatedMatch(
                    ticket=candidate,
                    similarity_score=1.0,
                    explanation=f"Exact booking reference match: {reference}.",
                    match_type="booking_reference",
                )
            )
        else:
            text_candidates.append(candidate)

    if not text_candidates:
        return exact_matches

    documents = [_tokens(source_text)] + [_tokens(_ticket_text(item)) for item in text_candidates]
    vectors = _tfidf_vectors(documents)
    source_vector = vectors[0]
    text_matches: list[RelatedMatch] = []

    for candidate, candidate_vector in zip(text_candidates, vectors[1:]):
        score = _cosine_similarity(source_vector, candidate_vector)
        if score < min_similarity:
            continue
        shared_terms = sorted(
            (term for term in set(source_vector) & set(candidate_vector)),
            key=lambda term: source_vector[term] * candidate_vector[term],
            reverse=True,
        )[:3]
        terms = ", ".join(f"“{term}”" for term in shared_terms)
        explanation = (
            f"Similar ticket wording: {terms}."
            if terms
            else "Similar ticket subject and description."
        )
        text_matches.append(
            RelatedMatch(
                ticket=candidate,
                similarity_score=score,
                explanation=explanation,
                match_type="content",
            )
        )

    text_matches.sort(key=lambda match: (-match.similarity_score, match.ticket.id))
    exact_matches.sort(key=lambda match: match.ticket.id)
    return exact_matches + text_matches
