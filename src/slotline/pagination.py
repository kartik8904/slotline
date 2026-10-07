"""Cursor pagination. The cursor is the last id returned; UUID v7 ids sort by creation time."""

import base64
import binascii
import uuid
from collections.abc import Sequence
from typing import Protocol

from slotline.errors import field_error

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class HasId(Protocol):
    @property
    def id(self) -> uuid.UUID: ...


def encode_cursor(last_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(last_id.bytes).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> uuid.UUID | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return uuid.UUID(bytes=base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError):
        raise field_error("query.cursor", "Invalid cursor.", "invalid_cursor") from None


def paginate[T: HasId](rows: Sequence[T], limit: int) -> tuple[list[T], str | None]:
    """`rows` were fetched with limit + 1; an extra row means there is a next page."""
    items = list(rows[:limit])
    next_cursor = encode_cursor(items[-1].id) if len(rows) > limit and items else None
    return items, next_cursor
