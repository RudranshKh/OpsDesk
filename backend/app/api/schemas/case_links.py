from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RelatedTicketRead(BaseModel):
    id: int
    reference: str
    subject: str
    status: Literal["open", "pending", "resolved", "closed"]
    priority: Literal["low", "normal", "high", "urgent"]
    created_at: datetime
    similarity_score: float = Field(ge=0, le=1)
    explanation: str
    match_type: Literal["booking_reference", "content"]
    is_linked: bool


class ConfirmTicketLinkRequest(BaseModel):
    linked_ticket_id: int = Field(gt=0)


class TicketLinkRead(BaseModel):
    id: int
    ticket_id: int
    linked_ticket_id: int
    link_type: str
    created_at: datetime
