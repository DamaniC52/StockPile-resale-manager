"""FastAPI application entry point.

Routers get registered here as we add them (auth, items, sales, dashboard).
Keeping this file thin — app construction and wiring only, no business logic —
means you can read it in ten seconds to see what the service exposes.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

settings = get_settings()

app = FastAPI(
    title="FlipTrack API",
    description="Resale inventory and profit/loss tracking.",
    version="0.1.0",
)

# Browsers block cross-origin requests unless the server opts in. The Vite dev
# server runs on :5173 while the API runs on :8000 — different ports mean
# different origins, so without this the frontend's fetch() fails.
#
# In development we ALSO proxy /api through Vite, which sidesteps CORS entirely.
# This middleware is what makes the deployed setup work (Vercel -> Render), where
# there is no shared dev server to proxy through.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Liveness + database reachability check.

    Deliberately executes `SELECT 1` rather than just returning {"status": "ok"}.
    A health check that doesn't touch its dependencies will happily report green
    while the database is unreachable — which is worse than having no health
    check at all, because it actively misleads you during an incident.

    Note the distinction: this is a *readiness* check (can I serve traffic?),
    not a *liveness* check (is the process alive?). Render uses this endpoint to
    decide whether a deploy succeeded.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Return the failure as data rather than raising, so the endpoint still
        # answers and tells you *which* component is broken. (In production you'd
        # also return HTTP 503 here so load balancers stop routing traffic.)
        return {"status": "degraded", "db": "unreachable"}
    return {"status": "ok", "db": "connected"}
