from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import TimestampMixin
from app.db.session import Base


class Agency(TimestampMixin, Base):
    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", index=True)

    users: Mapped[list["User"]] = relationship(back_populates="agency")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="agency")
