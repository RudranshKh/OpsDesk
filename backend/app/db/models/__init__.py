"""Model registry; importing this module registers every table on ``Base``."""

from app.db.models.agency import Agency
from app.db.models.auth import LoginRateLimit, RevokedToken
from app.db.models.operations import ActivityLog, Assignment, Conversation
from app.db.models.sla import SLAEscalation, TicketSLA
from app.db.models.ticket import Ticket, TicketLink
from app.db.models.user import AgentProfile, USER_ROLES, User

__all__ = [
    "USER_ROLES",
    "ActivityLog",
    "Agency",
    "AgentProfile",
    "Assignment",
    "RevokedToken",
    "SLAEscalation",
    "TicketSLA",
    "Conversation",
    "LoginRateLimit",
    "Ticket",
    "TicketLink",
    "User",
]
