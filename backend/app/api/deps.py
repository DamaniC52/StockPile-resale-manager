"""Shared route dependencies: database session, current user, owned objects."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.item import Item
from app.models.user import User

# tokenUrl is documentation only: it tells /docs where to get a token. The
# scheme's job here is to pull the bearer token out of the Authorization header.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    # WWW-Authenticate is required by RFC 6750 on a 401 from a bearer scheme.
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id = decode_access_token(token)
    if user_id is None:
        raise unauthorized

    # Re-read the user every request: a token is a stale snapshot, so a
    # deactivated account must not keep working until its token expires.
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_owned_item(item_id: int, db: DbSession, user: CurrentUser) -> Item:
    """Load an item belonging to the caller, or 404.

    Ownership is filtered in the query rather than checked afterwards, so no
    route can forget it. Never use db.get(Item, item_id) on a tenant table: it
    skips the filter and may return a cached object without querying at all.
    """
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        # 404 rather than 403: a 403 would confirm the row exists and belongs to
        # someone else, letting an attacker enumerate valid ids.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


OwnedItem = Annotated[Item, Depends(get_owned_item)]
