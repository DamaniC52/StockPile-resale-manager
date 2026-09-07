"""User account — the tenant boundary."""

from typing import TYPE_CHECKING

from sqlalchemy import Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.item import Item


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(server_default="true")

    items: Mapped[list["Item"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Functional index so `WHERE lower(email) = ?` is both unique and indexed.
        Index("uq_users_lower_email", func.lower(email), unique=True),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
