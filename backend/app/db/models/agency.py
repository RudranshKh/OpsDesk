from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import TimestampMixin
from app.db.session import Base


class Agency(TimestampMixin, Base):
    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)

    users: Mapped[list["User"]] = relationship(back_populates="agency")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="agency")
