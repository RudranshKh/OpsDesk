from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, field_validator


SLAStatus = Literal["on_track", "approaching", "travel_urgent", "breached", "met"]


class TicketSLASummary(BaseModel):
    response_due_at: datetime
    resolution_due_at: datetime
    travel_deadline_at: datetime | None
    travel_deadline_type: Literal["check_in", "departure"] | None
    travel_data_status: Literal["available", "missing"]
    response_status: str
    resolution_status: str
    sla_status: SLAStatus
    response_remaining_seconds: int | None
    resolution_remaining_seconds: int | None
    evaluated_at: datetime

    @field_validator(
        "response_due_at", "resolution_due_at", "travel_deadline_at", "evaluated_at", mode="before"
    )
    @classmethod
    def datetime_values_are_explicit_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class SLAEscalationRead(BaseModel):
    id: int
    rule_key: Literal["approaching", "breached"]
    triggered_at: datetime
    assignment_id: int | None
    assigned_to: str | None
    summary: str

    @field_validator("triggered_at", mode="before")
    @classmethod
    def triggered_at_is_explicit_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class SLAOverviewRead(TicketSLASummary):
    ticket_id: int
    escalation_history: list[SLAEscalationRead]
