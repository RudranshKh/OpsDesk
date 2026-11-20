from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import TimestampMixin
from app.db.session import Base


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'pending', 'resolved', 'closed')", name="ck_tickets_status"
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')", name="ck_tickets_priority"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    agency_id: Mapped[int] = mapped_column(
        ForeignKey("agencies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(80), index=True)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    departure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", server_default="open")
    priority: Mapped[str] = mapped_column(String(24), nullable=False, default="normal", server_default="normal")

    agency: Mapped["Agency"] = relationship(back_populates="tickets")
    created_by: Mapped["User"] = relationship(back_populates="created_tickets")
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True
    )
    links: Mapped[list["TicketLink"]] = relationship(
        back_populates="ticket", foreign_keys="TicketLink.ticket_id",
        cascade="all, delete-orphan", passive_deletes=True
    )
    linked_from: Mapped[list["TicketLink"]] = relationship(
        back_populates="linked_ticket", foreign_keys="TicketLink.linked_ticket_id",
        cascade="all, delete-orphan", passive_deletes=True
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True
    )
    sla: Mapped["TicketSLA | None"] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )
    sla_escalations: Mapped[list["SLAEscalation"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True
    )


class TicketLink(TimestampMixin, Base):
    __tablename__ = "ticket_links"
    __table_args__ = (
        CheckConstraint("ticket_id <> linked_ticket_id", name="ck_ticket_links_not_self"),
        CheckConstraint(
            "link_type IN ('related', 'duplicate', 'blocks', 'blocked_by')",
            name="ck_ticket_links_type",
        ),
        UniqueConstraint("ticket_id", "linked_ticket_id", "link_type", name="uq_ticket_links_pair_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    linked_ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    link_type: Mapped[str] = mapped_column(String(24), nullable=False, default="related", server_default="related")

    ticket: Mapped["Ticket"] = relationship(back_populates="links", foreign_keys=[ticket_id])
    linked_ticket: Mapped["Ticket"] = relationship(back_populates="linked_from", foreign_keys=[linked_ticket_id])
