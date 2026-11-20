from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RoutingCandidateScoreRead(BaseModel):
    agent_id: int
    agent_name: str
    agent_role: str
    regional_expertise: list[str]
    available: bool
    regional_match: Literal["exact", "global", "none"]
    region_points: int
    priority_points: int
    workload: int
    workload_points: int
    availability_points: int
    total_score: int
    explanation: str


class RoutingAssignmentRead(BaseModel):
    id: int
    ticket_id: int
    agent_id: int
    agent_name: str
    agent_role: str
    agent_regions: list[str]
    workload: int
    score: int | None
    explanation: str
    assigned_at: datetime
    candidate_scores: list[RoutingCandidateScoreRead] = Field(default_factory=list)


class RoutingProfileUpdate(BaseModel):
    regions: list[str] = Field(max_length=20)
    is_available: bool

    @field_validator("regions")
    @classmethod
    def normalize_regions(cls, regions: list[str]) -> list[str]:
        cleaned = [region.strip() for region in regions]
        if any(not region or len(region) > 80 for region in cleaned):
            raise ValueError("Regions must contain 1 to 80 characters")
        normalized = {region.casefold() for region in cleaned}
        if len(normalized) != len(cleaned):
            raise ValueError("Regions must be unique")
        return cleaned


class RoutingProfileRead(BaseModel):
    user_id: int
    user_name: str
    user_role: str
    regions: list[str]
    is_available: bool
    has_profile: bool
