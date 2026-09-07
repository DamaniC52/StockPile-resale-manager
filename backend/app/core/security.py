"""Password hashing and access-token encoding.

Uses bcrypt directly rather than passlib, which is unmaintained and breaks
against bcrypt 5.x.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()

# bcrypt hashes at most 72 bytes and raises above that. Enforced at the schema
# layer so the error surfaces as a 422, not a 500.
BCRYPT_MAX_BYTES = 72


# A real bcrypt hash of a throwaway value, used to spend the same CPU time on a
# login attempt for an unknown email as for a known one. Without it, response
# latency alone reveals which emails are registered.
DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.NlG3B7NEDDkTeGvDf6ZvGqfmi/JHpJa"


def hash_password(password: str) -> str:
    """Hash a password with a per-password random salt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        # Malformed stored hash, or an over-length password.
        return False


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    # `sub` must be a string per RFC 7519; `exp` is enforced by the decoder.
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Return the user id from a valid token, or None if it is unusable."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            # Pinning the algorithm list is security-critical: trusting the
            # token's own `alg` header allows algorithm-confusion attacks.
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        # Covers bad signature, expiry, and malformed tokens alike. The caller
        # returns 401 without distinguishing, so nothing is leaked.
        return None

    subject = payload.get("sub")
    if subject is None:
        return None
    try:
        return int(subject)
    except (TypeError, ValueError):
        return None
