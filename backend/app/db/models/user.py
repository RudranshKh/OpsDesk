from sqlalchemy import Boolean, CheckConstraint, ForeignKey, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import TimestampMixin
from app.db.session import Base

USER_ROLES = ("admin", "agent", "escalation_manager")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'agent', 'escalation_manager')", name="ck_users_role"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(
        ForeignKey("agencies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="agent", server_default="agent")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    agency: Mapped["Agency"] = relationship(back_populates="users")
    created_tickets: Mapped[list["Ticket"]] = relationship(back_populates="created_by")
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="user", foreign_keys="Assignment.user_id"
    )
    made_assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="assigned_by", foreign_keys="Assignment.assigned_by_id"
    )
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="author")
    activity_logs: Mapped[list["ActivityLog"]] = relationship(back_populates="actor")
    agent_profile: Mapped["AgentProfile | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class AgentProfile(TimestampMixin, Base):
    """Routing expertise and availability for an agent or escalation manager."""

    __tablename__ = "agent_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    regions: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    user: Mapped["User"] = relationship(back_populates="agent_profile")
