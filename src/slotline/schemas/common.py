import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128  # the upper cap stops argon2 being used as a CPU-exhaustion lever

_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalise_email(value: str) -> str:
    """A conservative shape check, lowercased. Real validation is the email arriving (S9)."""
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL_SHAPE.match(email):
        raise ValueError("Enter a valid email address.")
    return email


Email = Annotated[str, AfterValidator(_normalise_email)]
NewPassword = Annotated[
    str, StringConstraints(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
]
# Login accepts any non-empty password up to the cap, so old or odd passwords still get a 401
LoginPassword = Annotated[str, StringConstraints(min_length=1, max_length=PASSWORD_MAX_LENGTH)]


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected, so a body can never smuggle in an
    `org_id` that something might later start to trust."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
