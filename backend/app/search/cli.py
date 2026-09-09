"""Operational commands for the search index.

    python -m app.search.cli reindex   # rebuild from Postgres, swap alias
    python -m app.search.cli drain     # apply the outbox backlog now
    python -m app.search.cli status    # pending rows and alias target
"""

import argparse
import logging
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.search import get_indexer
from app.search.outbox import drain, pending_count


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="app.search.cli")
    parser.add_argument("command", choices=["reindex", "drain", "status"])
    args = parser.parse_args(argv)

    indexer = get_indexer()
    if indexer is None:
        print(f"SEARCH_BACKEND is {get_settings().SEARCH_BACKEND!r}; nothing to do")
        return 1

    with SessionLocal() as db:
        if args.command == "reindex":
            name = indexer.reindex(db)
            print(f"alias {indexer.alias} -> {name}")
        elif args.command == "drain":
            total = 0
            while n := drain(db, indexer):
                total += n
            print(f"applied {total} change(s); {pending_count(db)} still pending")
        else:
            targets = list(indexer.client.indices.get_alias(name=indexer.alias).keys())
            print(f"alias {indexer.alias} -> {targets}")
            print(f"pending outbox rows: {pending_count(db)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
