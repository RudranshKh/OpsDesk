from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.api.schemas.tickets import TicketPriority


class CountMetric(BaseModel):
    label: str
    count: int


class VolumePoint(BaseModel):
    period: str
    count: int


class ThemeExample(BaseModel):
    ticket_id: int
    reference: str
    subject: str
    excerpt: str


class ComplaintTheme(BaseModel):
    label: str
    terms: list[str]
    ticket_frequency: int
    evidence_kind: Literal["inferred"] = "inferred"
    similarity_threshold: float
    examples: list[ThemeExample]


class GroupFrequency(BaseModel):
    key: str
    count: int


class InsightQuality(BaseModel):
    theme_status: Literal["available", "insufficient_data"]
    theme_note: str
    resolved_text_sample_size: int
    public_conversation_ticket_count: int
    resolution_time_sample_size: int
    sla_sample_size: int
    invalid_resolution_timestamp_count: int


class InsightsRead(BaseModel):
    date_from: date | None
    date_to: date | None
    agency_id: int
    priority: TicketPriority | None
    total_tickets: int
    resolved_tickets: int
    average_resolution_hours: float | None
    resolution_time_sample_size: int
    sla_breach_rate: float | None
    sla_breached_tickets: int
    sla_sample_size: int
    conversation_tickets: int
    volume_over_time: list[VolumePoint]
    priority_breakdown: list[CountMetric]
    status_breakdown: list[CountMetric]
    agency_issue_frequency: list[GroupFrequency]
    operational_area_frequency: list[GroupFrequency]
    recurring_themes: list[ComplaintTheme]
    data_quality: InsightQuality
