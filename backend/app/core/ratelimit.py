"""A small fixed-window rate limiter for the auth endpoints.

In-process and in-memory, which is a real limitation worth stating: the window
is per worker, so N workers allow N times the limit, and a restart forgets
everything. Redis would fix both. For a single-instance deployment whose threat
is a script guessing passwords, this raises the cost enough to matter without
adding a datastore.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> float | None:
        """Record a hit. Returns seconds to wait if over the limit, else None."""
        now = time.monotonic()
        hits = self._hits[key]

        # Drop timestamps that have aged out of the window. Doing this on read
        # keeps memory bounded without a background sweep.
        cutoff = now - self.window
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            return round(hits[0] + self.window - now, 1)

        hits.append(now)
        if not hits:
            self._hits.pop(key, None)
        return None


def _client_key(request: Request) -> str:
    """Identify the caller.

    Render terminates TLS and proxies, so request.client.host is the proxy.
    X-Forwarded-For's first entry is the original client. It is spoofable by
    anyone talking to the origin directly, which is acceptable here: this
    limits casual abuse, it is not an authorization boundary.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


_settings = get_settings()
_auth_limiter = SlidingWindowLimiter(
    _settings.AUTH_RATE_LIMIT, _settings.AUTH_RATE_WINDOW_SECONDS
)


def rate_limit_auth(request: Request) -> None:
    """Dependency for signup and login."""
    retry_after = _auth_limiter.check(f"auth:{_client_key(request)}")
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again shortly.",
            # RFC 6585: tell the client how long to wait.
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
