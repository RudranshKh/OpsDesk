from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.sla import TicketSLASummary

TicketStatus = Literal["open", "pending", "resolved", "closed"]
TicketPriority = Literal["low", "normal", "high", "urgent"]


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    region: str | None = Field(default=None, max_length=80)
    check_in_at: datetime | None = None
    departure_at: datetime | None = None
    priority: TicketPriority = "normal"

    @field_validator("subject")
    @classmethod
    def subject_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Subject cannot be blank")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("check_in_at", "departure_at")
    @classmethod
    def travel_dates_need_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Travel date and time must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    region: str | None = Field(default=None, max_length=80)
    check_in_at: datetime | None = None
    departure_at: datetime | None = None
    status: TicketStatus | None = None
    priority: TicketPriority | None = None

    @field_validator("status", "priority", mode="before")
    @classmethod
    def status_and_priority_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value

    @field_validator("subject")
    @classmethod
    def subject_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Subject cannot be null")
        value = value.strip()
        if not value:
            raise ValueError("Subject cannot be blank")
        return value

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("check_in_at", "departure_at")
    @classmethod
    def travel_dates_need_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Travel date and time must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None

    @model_validator(mode="after")
    def require_an_update(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class AgencyOption(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class UserOption(BaseModel):
    id: int
    agency_id: int
    full_name: str
    email: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class TicketRead(BaseModel):
    id: int
    reference: str
    agency_id: int
    agency_name: str
    created_by_id: int
    created_by_name: str
    subject: str
    description: str | None
    region: str | None
    check_in_at: datetime | None
    departure_at: datetime | None
    status: TicketStatus
    priority: TicketPriority
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    sla: "TicketSLASummary"

    @field_validator(
        "check_in_at", "departure_at", "created_at", "updated_at", "resolved_at", mode="before"
    )
    @classmethod
    def datetime_values_are_explicit_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
