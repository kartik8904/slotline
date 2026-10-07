import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from slotline.clock import Clock
from slotline.config import Settings
from slotline.domain.lockout import LockoutState, after_failure, after_success, is_locked
from slotline.domain.org_settings import default_org_settings
from slotline.domain.principal import ALL_SCOPES, Principal, Role
from slotline.domain.slugs import slugify
from slotline.errors import AppError, ErrorCode, field_error, forbidden, unauthenticated
from slotline.ids import new_uuid7
from slotline.logging_config import mask_tail
from slotline.models import ApiKey, Organization, User
from slotline.security.api_keys import looks_like_api_key
from slotline.security.hashing import sha256_hex
from slotline.security.passwords import hash_password, needs_rehash, verify_dummy, verify_password
from slotline.security.tokens import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    JwtKeyring,
    TokenError,
    decode_access_token,
    encode_access_token,
    new_refresh_token,
)
from slotline.uow import UnitOfWork

log = structlog.get_logger()

SLUG_ATTEMPTS = 5
# last_used_at is written at most this often per key, so authenticating isn't a write per request
API_KEY_TOUCH_INTERVAL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class MeInfo:
    organization: Organization
    user: User | None
    api_key: ApiKey | None


def _lockout_state(user: User) -> LockoutState:
    return LockoutState(
        user.failed_login_count, user.failed_login_window_started_at, user.locked_until
    )


def _user_id(principal: Principal) -> uuid.UUID:
    if principal.user_id is None:  # routes already reject API keys; this is the backstop
        raise forbidden("This action is for staff users, not API keys.")
    return principal.user_id


class AuthService:
    def __init__(
        self, uow: UnitOfWork, clock: Clock, keyring: JwtKeyring, settings: Settings
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._keyring = keyring
        self._settings = settings

    # --- signup -------------------------------------------------------------------------

    async def signup(
        self, *, organization_name: str, email: str, password: str, timezone: str | None
    ) -> tuple[Organization, User]:
        password_hash = await hash_password(password)
        base_slug = slugify(organization_name)
        async with self._uow as uow:
            org = None
            for attempt in range(SLUG_ATTEMPTS):
                slug = base_slug if attempt == 0 else f"{base_slug}-{secrets.token_hex(2)}"
                org = await uow.organizations.create(
                    name=organization_name,
                    slug=slug,
                    timezone=timezone or self._settings.default_timezone,
                    settings=default_org_settings(),
                )
                if org is not None:
                    break
            if org is None:
                raise RuntimeError("could not find a free organisation slug")
            user = await uow.users.add(
                org.id, email=email, password_hash=password_hash, role=Role.OWNER.value
            )
            if user is None:
                # Raising inside the block rolls the organisation back too
                raise AppError(
                    409, ErrorCode.EMAIL_EXISTS, "Email already registered", "Use another email."
                )
        log.info("signup", org_id=str(org.id), user_id=str(user.id), email=mask_tail(email))
        return org, user

    # --- login, refresh, logout --------------------------------------------------------

    async def login(self, email: str, password: str) -> TokenPair:
        pair: TokenPair | None = None
        async with self._uow as uow:
            now = self._clock.now()
            user = await uow.lookup.get_user_by_email_for_update(email)
            if user is None or not user.is_active:
                await verify_dummy(password)
            else:
                state = _lockout_state(user)
                if is_locked(state, now):
                    # Same 401 as a wrong password (C2); the attempt isn't counted again
                    await verify_dummy(password)
                    log.warning("login_while_locked", org_id=str(user.org_id))
                elif await verify_password(user.password_hash, password):
                    if state != LockoutState():
                        await uow.users.set_lockout(user.org_id, user.id, after_success())
                    if needs_rehash(user.password_hash):
                        await uow.users.set_password_hash(
                            user.org_id, user.id, await hash_password(password)
                        )
                    pair = await self._issue_tokens(uow, user, new_uuid7(), now)
                else:
                    new_state = after_failure(state, now)
                    await uow.users.set_lockout(user.org_id, user.id, new_state)
                    log.warning(
                        "login_failed",
                        org_id=str(user.org_id),
                        email=mask_tail(email),
                        failed_count=new_state.failed_count,
                        locked=is_locked(new_state, now),
                    )
        # Raised after the block exits, so the failure counter above has been committed
        if pair is None:
            raise unauthenticated()
        return pair

    async def refresh(self, refresh_token: str) -> TokenPair:
        token_hash = sha256_hex(refresh_token)
        pair: TokenPair | None = None
        async with self._uow as uow:
            now = self._clock.now()
            claimed = await uow.lookup.revoke_refresh_token_if_active(token_hash, now)
            if claimed is None:
                # Not claimable: unknown, or already used. Using a rotated token again means
                # two parties hold it, so the whole family dies (and the commit keeps it dead).
                reused = await uow.lookup.get_refresh_token(token_hash)
                if reused is not None:
                    await uow.refresh_tokens.revoke_family(reused.org_id, reused.family_id, now)
                    log.warning(
                        "refresh_token_reuse_detected",
                        org_id=str(reused.org_id),
                        user_id=str(reused.user_id),
                        family_id=str(reused.family_id),
                    )
            elif claimed.expires_at > now:
                user = await uow.users.get(claimed.org_id, claimed.user_id)
                if user is not None and user.is_active:
                    pair = await self._issue_tokens(uow, user, claimed.family_id, now)
        if pair is None:
            raise unauthenticated()
        return pair

    async def logout(self, principal: Principal, refresh_token: str) -> None:
        """Revokes the refresh token's family. Unknown or someone else's token is a quiet no-op."""
        user_id = _user_id(principal)
        token_hash = sha256_hex(refresh_token)
        async with self._uow as uow:
            token = await uow.lookup.get_refresh_token(token_hash)
            if token and token.org_id == principal.org_id and token.user_id == user_id:
                await uow.refresh_tokens.revoke_family(
                    token.org_id, token.family_id, self._clock.now()
                )

    async def _issue_tokens(
        self, uow: UnitOfWork, user: User, family_id: uuid.UUID, now: datetime
    ) -> TokenPair:
        refresh_token = new_refresh_token()
        await uow.refresh_tokens.add(
            user.org_id,
            user_id=user.id,
            family_id=family_id,
            token_hash=sha256_hex(refresh_token),
            expires_at=now + REFRESH_TOKEN_TTL,
        )
        access_token = encode_access_token(
            self._keyring, user_id=user.id, org_id=user.org_id, family_id=family_id, now=now
        )
        return TokenPair(access_token, refresh_token, int(ACCESS_TOKEN_TTL.total_seconds()))

    # --- authenticating requests -------------------------------------------------------

    async def authenticate_bearer(self, token: str) -> Principal:
        try:
            claims = decode_access_token(self._keyring, token, self._clock.now())
        except TokenError:
            raise unauthenticated() from None
        async with self._uow as uow:
            # Read the user on every request: deactivation and role changes apply at once,
            # instead of after the 15 minutes an access token would otherwise stay valid.
            user = await uow.users.get(claims.org_id, claims.user_id)
        if user is None or not user.is_active:
            raise unauthenticated()
        return Principal(
            org_id=user.org_id,
            role=Role(user.role),
            scopes=ALL_SCOPES,
            user_id=user.id,
            session_family_id=claims.family_id,
        )

    async def authenticate_api_key(self, key: str) -> Principal:
        if not looks_like_api_key(key):
            raise unauthenticated()
        async with self._uow as uow:
            now = self._clock.now()
            api_key = await uow.lookup.get_api_key_by_hash(sha256_hex(key))
            if api_key is None or api_key.revoked_at is not None:
                raise unauthenticated()
            await uow.api_keys.touch_last_used(
                api_key.org_id,
                api_key.id,
                now,
                older_than=now - timedelta(seconds=API_KEY_TOUCH_INTERVAL_SECONDS),
            )
        return Principal(
            org_id=api_key.org_id,
            role=None,
            scopes=frozenset(api_key.scopes),
            key_id=api_key.id,
        )

    # --- /me ---------------------------------------------------------------------------

    async def me(self, principal: Principal) -> MeInfo:
        async with self._uow as uow:
            org = await uow.organizations.get(principal.org_id)
            user = (
                await uow.users.get(principal.org_id, principal.user_id)
                if principal.user_id
                else None
            )
            api_key = (
                await uow.api_keys.get(principal.org_id, principal.key_id)
                if principal.key_id
                else None
            )
        if org is None or (user is None and api_key is None):
            raise unauthenticated()
        return MeInfo(organization=org, user=user, api_key=api_key)

    async def change_password(
        self, principal: Principal, current_password: str, new_password: str
    ) -> None:
        """Wrong guesses count towards lockout like login, so a stolen access token can't be
        used to brute-force the current password."""
        user_id = _user_id(principal)
        changed = False
        async with self._uow as uow:
            now = self._clock.now()
            user = await uow.users.get_for_update(principal.org_id, user_id)
            if user is None or not user.is_active:
                raise unauthenticated()
            state = _lockout_state(user)
            if is_locked(state, now):
                await verify_dummy(current_password)
            elif await verify_password(user.password_hash, current_password):
                changed = True
                await uow.users.set_password_hash(
                    user.org_id, user.id, await hash_password(new_password)
                )
                await uow.users.set_lockout(user.org_id, user.id, after_success())
                await uow.refresh_tokens.revoke_all_for_user(
                    user.org_id, user.id, now, except_family_id=principal.session_family_id
                )
            else:
                await uow.users.set_lockout(user.org_id, user.id, after_failure(state, now))
        if not changed:
            raise field_error(
                "body.current_password", "Current password is incorrect.", "incorrect_password"
            )
        log.info("password_changed", org_id=str(principal.org_id), user_id=str(user_id))
