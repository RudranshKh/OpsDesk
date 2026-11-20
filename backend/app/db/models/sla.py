from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import TimestampMixin
from app.db.session import Base


class TicketSLA(TimestampMixin, Base):
    __tablename__ = "ticket_slas"
    __table_args__ = (
        CheckConstraint(
            "sla_status IN ('on_track', 'approaching', 'travel_urgent', 'breached', 'met')",
            name="ck_ticket_slas_status",
        ),
        CheckConstraint(
            "travel_data_status IN ('available', 'missing')",
            name="ck_ticket_slas_travel_data_status",
        ),
    )

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    travel_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    travel_deadline_type: Mapped[str | None] = mapped_column(String(24))
    travel_data_status: Mapped[str] = mapped_column(String(16), nullable=False, default="missing")
    response_status: Mapped[str] = mapped_column(String(16), nullable=False, default="on_track")
    resolution_status: Mapped[str] = mapped_column(String(16), nullable=False, default="on_track")
    sla_status: Mapped[str] = mapped_column(String(20), nullable=False, default="on_track")
    response_remaining_seconds: Mapped[int | None] = mapped_column(Integer)
    resolution_remaining_seconds: Mapped[int | None] = mapped_column(Integer)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    ticket: Mapped["Ticket"] = relationship(back_populates="sla")


class SLAEscalation(Base):
    __tablename__ = "sla_escalations"
    __table_args__ = (
        CheckConstraint(
            "rule_key IN ('approaching', 'breached')", name="ck_sla_escalations_rule"
        ),
        UniqueConstraint("ticket_id", "rule_key", name="uq_sla_escalations_ticket_rule"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_key: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id", ondelete="SET NULL"), index=True
    )
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    ticket: Mapped["Ticket"] = relationship(back_populates="sla_escalations")
    assignment: Mapped["Assignment | None"] = relationship()
