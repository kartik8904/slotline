import secrets
from dataclasses import dataclass

from slotline.security.hashing import sha256_hex

KEY_PREFIX = "sl_live_"
DISPLAY_PREFIX_LENGTH = 12  # "sl_live_" plus 4 characters: enough to recognise a key, not use it


@dataclass(frozen=True, slots=True)
class NewApiKey:
    key: str  # shown to the caller once, never stored
    prefix: str
    key_hash: str


def generate_api_key() -> NewApiKey:
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return NewApiKey(key=key, prefix=key[:DISPLAY_PREFIX_LENGTH], key_hash=sha256_hex(key))


def looks_like_api_key(value: str) -> bool:
    return value.startswith(KEY_PREFIX)
