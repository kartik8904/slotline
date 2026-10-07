"""Short-lived access JWTs (HS256, with a `kid` so signing keys can rotate) and refresh tokens."""

import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

from slotline.config import Settings

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)
ALGORITHM = "HS256"
ISSUER = "slotline"


class TokenError(Exception):
    """The token is malformed, forged, unknown-key or expired. Callers answer 401."""


@dataclass(frozen=True, slots=True)
class JwtKeyring:
    keys: Mapping[str, str]
    active_kid: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "JwtKeyring":
        if settings.jwt_active_kid is None:  # Settings validation makes this unreachable
            raise ValueError("JWT_ACTIVE_KID is not set")
        keys = {kid: secret.get_secret_value() for kid, secret in settings.jwt_keys.items()}
        return cls(keys=keys, active_kid=settings.jwt_active_kid)


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    org_id: uuid.UUID
    family_id: uuid.UUID
    expires_at: datetime


def encode_access_token(
    keyring: JwtKeyring,
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    family_id: uuid.UUID,
    now: datetime,
) -> str:
    payload = {
        "iss": ISSUER,
        "sub": str(user_id),
        "org": str(org_id),
        "fam": str(family_id),
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(
        payload,
        keyring.keys[keyring.active_kid],
        algorithm=ALGORITHM,
        headers={"kid": keyring.active_kid},
    )


def decode_access_token(keyring: JwtKeyring, token: str, now: datetime) -> AccessClaims:
    """Verify signature, issuer and claims. Expiry is checked here against the injected Clock,
    not by PyJWT, so tests can move time without minting tokens with past timestamps."""
    try:
        header = jwt.get_unverified_header(token)
        key = keyring.keys.get(str(header.get("kid")))
        if key is None or header.get("alg") != ALGORITHM:
            raise TokenError("unknown key or algorithm")
        payload = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={
                "require": ["exp", "iat", "sub", "org", "fam"],
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
        expires = payload["exp"]
        if not isinstance(expires, int) or now.timestamp() >= expires:
            raise TokenError("expired")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            org_id=uuid.UUID(payload["org"]),
            family_id=uuid.UUID(payload["fam"]),
            expires_at=datetime.fromtimestamp(expires, tz=now.tzinfo),
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise TokenError(str(exc)) from exc


def new_refresh_token() -> str:
    """Opaque 256-bit random value. Only its SHA-256 hash is stored."""
    return secrets.token_urlsafe(32)
