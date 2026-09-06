"""User account — the tenant boundary for the whole application."""

from typing import TYPE_CHECKING

from sqlalchemy import Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    # Imported only for type checkers, not at runtime. This is how you get
    # `Mapped[list["Item"]]` to type-check without creating a circular import
    # (user imports item, item imports user). SQLAlchemy resolves the string
    # "Item" from its own registry at mapper-configuration time, so the real
    # import genuinely isn't needed.
    from app.models.item import Item


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Stored as the user typed it (so we can display it back correctly), but
    # uniqueness and lookup are case-insensitive via the functional index below.
    email: Mapped[str] = mapped_column(String(255))

    # The column name says what it holds. Naming it `password` invites someone
    # to one day assign a plaintext value to it; `hashed_password` does not.
    # bcrypt output is 60 chars; 255 leaves room to migrate to argon2 later.
    hashed_password: Mapped[str] = mapped_column(String(255))

    is_active: Mapped[bool] = mapped_column(server_default="true")

    items: Mapped[list["Item"]] = relationship(
        back_populates="user",
        # cascade at the ORM level; the FK also has ON DELETE CASCADE so the
        # database enforces it even for deletes that bypass the ORM.
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # A FUNCTIONAL unique index: the index is built on lower(email), not on
        # email. Two consequences, both wanted:
        #
        #   1. "Dave@x.com" and "dave@x.com" collide -> no duplicate accounts.
        #   2. The login query `WHERE lower(email) = lower(:input)` can USE this
        #      index. A plain index on `email` could not — Postgres will not use
        #      an index on a column when the query wraps that column in a
        #      function. The index expression has to match the query expression.
        #
        # The alternative is the `citext` extension (a case-insensitive text
        # type), which is tidier but adds an extension dependency.
        Index("uq_users_lower_email", func.lower(email), unique=True),
    )

    def __repr__(self) -> str:
        # A real __repr__ makes debugging and test failures readable. Never
        # include hashed_password — reprs end up in logs and error trackers.
        return f"<User id={self.id} email={self.email!r}>"
