"""Full-text search on the stored tsvector, with a trigram branch for bare words."""

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.search.base import SearchHit, is_bare_word, normalize_query

# Below this a word_similarity match is mostly noise. Tuned by hand: "jorda"
# against "Jordan 4 Retro Bred" scores 0.83, the typo "jordn" 0.67, unrelated
# words well under 0.4.
TRIGRAM_THRESHOLD = 0.45


class PostgresSearchService:
    """Two matching strategies, because they fail in opposite directions.

    Full-text matches whole stemmed words, so "jordan retro" finds "Jordan 4
    Retro Bred" but "jorda" finds nothing. Trigrams match character sequences,
    so "jorda" and the typo "jordn" both hit, but a multi-word query scores
    poorly. Taking the better score covers typing mid-word.

    word_similarity rather than similarity: the latter compares the query
    against the whole name, so a short query against a long name scores low
    however well it matches one word (0.24 vs 0.83 for the example above).
    """

    def _statement(self, user_id: int, query: str, limit: int) -> Select:
        # websearch_to_tsquery accepts what people type: bare words, "quoted
        # phrases", OR, and -exclusions. to_tsquery raises on a stray quote.
        tsq = func.websearch_to_tsquery("english", query)

        # Cover-density ranking: matched lexemes close together outrank the
        # same lexemes scattered apart.
        score = func.ts_rank_cd(Item.search_vector, tsq)
        matches = Item.search_vector.op("@@")(tsq)

        if is_bare_word(query):
            # Explicit comparison rather than the <% operator, whose threshold
            # is a session GUC the connection pool would not carry.
            fuzzy = func.word_similarity(query, Item.name)
            score = func.greatest(score, fuzzy)
            matches = or_(matches, fuzzy > TRIGRAM_THRESHOLD)

        score = score.label("score")
        return (
            select(Item.id, score)
            .where(Item.user_id == user_id, matches)
            .order_by(score.desc(), Item.purchased_at.desc(), Item.id.desc())
            .limit(limit)
        )

    def search(
        self, db: Session, *, user_id: int, query: str, limit: int = 50
    ) -> list[SearchHit]:
        query = normalize_query(query)
        if not query:
            return []
        rows = db.execute(self._statement(user_id, query, limit)).all()
        return [SearchHit(item_id=r.id, score=float(r.score)) for r in rows]
