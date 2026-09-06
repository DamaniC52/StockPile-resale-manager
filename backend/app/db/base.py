"""Declarative base and the conventions every model inherits.

Everything in this file is a decision made *once* so that no model has to
repeat it. Getting these right up front is much cheaper than migrating a
column type across seven tables later.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import DateTime, MetaData, Numeric, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# --------------------------------------------------------------------------
# Constraint naming convention
# --------------------------------------------------------------------------
# Left to itself, Postgres invents names for constraints and indexes, and
# Alembic's autogenerate then produces migrations full of machine-generated
# gibberish that you cannot review or reliably drop by name.
#
# Declaring the pattern here means every constraint gets a predictable name
# like `ck_items_quantity_positive`, so a migration diff reads like English.
# This is boilerplate worth memorising — it goes in every SQLAlchemy project.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------
# `Annotated` lets us name a reusable type. Writing `Mapped[Money]` on a model
# now produces a Postgres NUMERIC(12, 2) column and a Python Decimal.
#
# Money is NEVER a float. `float` is IEEE-754 binary floating point, which
# cannot represent 0.10 exactly — 0.1 + 0.2 == 0.30000000000000004. Postgres
# `numeric` stores base-10 digit groups and is exact, and psycopg hands it back
# as `decimal.Decimal`, which is also exact. Rounding then happens only where
# you explicitly ask for it.
#
# (12, 2) means 12 total digits, 2 after the decimal point: up to
# 9,999,999,999.99. Ample for resale, and the scale of 2 makes "cents" the
# smallest storable unit, so a stray fraction of a cent can't silently appear.
Money = Annotated[Decimal, 12, 2]


class Base(DeclarativeBase):
    """Shared declarative base. Every model subclasses this."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Maps Python annotations -> SQL column types, so models stay readable:
    # `Mapped[Money]` instead of `mapped_column(Numeric(12, 2))` seven times.
    type_annotation_map = {
        Money: Numeric(12, 2),
        # TIMESTAMPTZ everywhere, never naive TIMESTAMP.
        #
        # `timestamp without time zone` stores wall-clock digits with no record
        # of which zone they meant. The moment you have a user in another
        # timezone — or you deploy to a server set to UTC while developing on a
        # laptop set to Eastern — you cannot recover the true instant. That's
        # unrecoverable data loss, and it silently corrupts every profit-by-month
        # chart. TIMESTAMPTZ stores a real instant; store UTC, convert on display.
        datetime: DateTime(timezone=True),
    }


class TimestampMixin:
    """Adds created_at / updated_at to a model.

    `server_default=func.now()` means *Postgres* fills these in, not Python.
    That matters: the database clock is a single source of truth, whereas
    application servers (or a background job, or a psql session) can disagree.
    It also means rows inserted outside the ORM still get correct timestamps.

    `onupdate` is applied by SQLAlchemy on ORM updates. A bulk
    `UPDATE items SET ...` in raw SQL would bypass it — the fully robust version
    is a Postgres trigger. Worth knowing the limitation; not worth a trigger yet.
    """

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
