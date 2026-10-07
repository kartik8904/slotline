import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from slotline.security.tokens import (
    ACCESS_TOKEN_TTL,
    JwtKeyring,
    TokenError,
    decode_access_token,
    encode_access_token,
    new_refresh_token,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
K1, K2 = "1" * 64, "2" * 64
USER, ORG, FAMILY = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
RING = JwtKeyring({"k1": K1}, "k1")


def encode(ring: JwtKeyring = RING, now: datetime = NOW) -> str:
    return encode_access_token(ring, user_id=USER, org_id=ORG, family_id=FAMILY, now=now)


def forge(
    payload_overrides: dict[str, Any] | None = None,
    *,
    key: str = K1,
    alg: str = "HS256",
    kid: str | None = "k1",
    drop: tuple[str, ...] = (),
) -> str:
    payload: dict[str, Any] = {
        "iss": "slotline",
        "sub": str(USER),
        "org": str(ORG),
        "fam": str(FAMILY),
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + ACCESS_TOKEN_TTL).timestamp()),
        **(payload_overrides or {}),
    }
    for name in drop:
        payload.pop(name)
    headers = {"kid": kid} if kid else {}
    return jwt.encode(payload, key, algorithm=alg, headers=headers)


def test_header_carries_kid_and_algorithm() -> None:
    header = jwt.get_unverified_header(encode())
    assert header["kid"] == "k1"
    assert header["alg"] == "HS256"


def test_round_trip() -> None:
    claims = decode_access_token(RING, encode(), NOW)
    assert (claims.user_id, claims.org_id, claims.family_id) == (USER, ORG, FAMILY)
    assert claims.expires_at == NOW + ACCESS_TOKEN_TTL


def test_valid_until_fifteen_minutes_then_expired() -> None:
    token = encode()
    decode_access_token(RING, token, NOW + ACCESS_TOKEN_TTL - timedelta(seconds=1))
    with pytest.raises(TokenError):
        decode_access_token(RING, token, NOW + ACCESS_TOKEN_TTL)
    assert ACCESS_TOKEN_TTL == timedelta(minutes=15)


def test_signature_from_another_key_is_rejected() -> None:
    with pytest.raises(TokenError):
        decode_access_token(RING, forge(key=K2), NOW)


def test_unknown_kid_and_missing_kid_are_rejected() -> None:
    with pytest.raises(TokenError):
        decode_access_token(RING, forge(kid="other"), NOW)
    with pytest.raises(TokenError):
        decode_access_token(RING, forge(kid=None), NOW)


def test_rotation_old_tokens_verify_until_the_old_key_is_removed() -> None:
    old_token = encode(JwtKeyring({"k1": K1}, "k1"))
    rotated = JwtKeyring({"k1": K1, "k2": K2}, "k2")
    assert decode_access_token(rotated, old_token, NOW).user_id == USER
    new_token = encode(rotated)
    assert jwt.get_unverified_header(new_token)["kid"] == "k2"
    assert decode_access_token(rotated, new_token, NOW).user_id == USER
    old_key_removed = JwtKeyring({"k2": K2}, "k2")
    with pytest.raises(TokenError):
        decode_access_token(old_key_removed, old_token, NOW)


def test_alg_none_is_rejected() -> None:
    unsigned = jwt.encode(
        {
            "iss": "slotline",
            "sub": str(USER),
            "org": str(ORG),
            "fam": str(FAMILY),
            "iat": 1,
            "exp": 4_000_000_000,
        },
        None,
        algorithm="none",
        headers={"kid": "k1"},
    )
    with pytest.raises(TokenError):
        decode_access_token(RING, unsigned, NOW)


def test_other_hmac_algorithm_is_rejected() -> None:
    with pytest.raises(TokenError):
        decode_access_token(RING, forge(alg="HS384"), NOW)


@pytest.mark.parametrize("claim", ["sub", "org", "fam", "exp", "iat"])
def test_missing_claims_are_rejected(claim: str) -> None:
    with pytest.raises(TokenError):
        decode_access_token(RING, forge(drop=(claim,)), NOW)


def test_wrong_issuer_and_malformed_ids_are_rejected() -> None:
    with pytest.raises(TokenError):
        decode_access_token(RING, forge({"iss": "someone-else"}), NOW)
    with pytest.raises(TokenError):
        decode_access_token(RING, forge({"sub": "not-a-uuid"}), NOW)
    with pytest.raises(TokenError):
        decode_access_token(RING, forge({"exp": "tomorrow"}), NOW)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x"])
def test_garbage_is_rejected(garbage: str) -> None:
    with pytest.raises(TokenError):
        decode_access_token(RING, garbage, NOW)


def test_refresh_tokens_are_long_and_unique() -> None:
    first, second = new_refresh_token(), new_refresh_token()
    assert first != second
    assert len(first) >= 43
