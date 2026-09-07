"""Request and response schemas for authentication."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import BCRYPT_MAX_BYTES


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=BCRYPT_MAX_BYTES)

    @field_validator("password")
    @classmethod
    def within_bcrypt_limit(cls, value: str) -> str:
        # max_length counts characters; bcrypt's limit is bytes, and non-ASCII
        # characters cost more than one.
        if len(value.encode()) > BCRYPT_MAX_BYTES:
            raise ValueError(f"password must be at most {BCRYPT_MAX_BYTES} bytes")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    # Lets FastAPI build this straight from an ORM instance.
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
