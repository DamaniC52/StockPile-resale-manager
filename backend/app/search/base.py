"""The search interface and the query rules every backend shares."""

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SearchHit:
    item_id: int
    score: float


class SearchService(Protocol):
    """Ranked item ids for a query, scoped to one user.

    Ids rather than rows, deliberately. An external index has no ORM objects to
    return, and the caller loads from Postgres either way — so a result can be
    at most slightly stale (an item indexed but since deleted drops out of the
    IN() lookup), never wrong (it cannot show data the database no longer has).
    """

    def search(
        self, db: Session, *, user_id: int, query: str, limit: int = 50
    ) -> list[SearchHit]: ...


# A single bare word: letters, digits, dots and hyphens, nothing else.
_BARE_WORD = re.compile(r"^[\w.\-]+$", re.UNICODE)


def is_bare_word(query: str) -> bool:
    """Whether fuzzy and prefix matching should run alongside exact matching.

    Only for a single word with no operators. This rule is shared by every
    backend because it protects query semantics, not performance: "nike -dunk"
    excludes Dunk in the exact branch, but the raw string is still fuzzily
    similar to "Nike Dunk Low Panda", and OR-ing a fuzzy branch in would let the
    excluded row back. A query with spaces or operators is one the user finished
    typing; fuzzy matching exists for the half-typed word before that.
    """
    return bool(_BARE_WORD.match(query)) and not query.startswith("-")


def normalize_query(query: str) -> str:
    return " ".join(query.split())
