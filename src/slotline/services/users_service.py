import uuid

import structlog

from slotline.clock import Clock
from slotline.domain.lockout import after_success
from slotline.domain.principal import Principal, Role
from slotline.errors import AppError, ErrorCode, not_found
from slotline.models import User
from slotline.pagination import paginate
from slotline.security.passwords import hash_password
from slotline.uow import UnitOfWork

log = structlog.get_logger()


class UsersService:
    """Owner-only staff management. Every call is scoped to the principal's organisation."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def create(self, principal: Principal, *, email: str, password: str, role: Role) -> User:
        password_hash = await hash_password(password)
        async with self._uow as uow:
            user = await uow.users.add(
                principal.org_id, email=email, password_hash=password_hash, role=role.value
            )
            if user is None:
                raise AppError(
                    409, ErrorCode.EMAIL_EXISTS, "Email already registered", "Use another email."
                )
        log.info("user_created", org_id=str(principal.org_id), user_id=str(user.id))
        return user

    async def list_users(
        self, principal: Principal, *, limit: int, after: uuid.UUID | None
    ) -> tuple[list[User], str | None]:
        async with self._uow as uow:
            rows = await uow.users.list_page(principal.org_id, limit=limit, after=after)
        return paginate(rows, limit)

    async def get(self, principal: Principal, user_id: uuid.UUID) -> User:
        async with self._uow as uow:
            user = await uow.users.get(principal.org_id, user_id)
        if user is None:
            raise not_found("User not found.")
        return user

    async def update(
        self,
        principal: Principal,
        user_id: uuid.UUID,
        *,
        role: Role | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> User:
        password_hash = await hash_password(password) if password is not None else None
        async with self._uow as uow:
            now = self._clock.now()
            # Lock the active owners first, in id order, for every update. Two owners demoting
            # each other then queue up instead of both seeing "another owner exists".
            owners = await uow.users.lock_active_owners(principal.org_id)
            user = await uow.users.get_for_update(principal.org_id, user_id)
            if user is None:
                raise not_found("User not found.")

            old_role, old_active = user.role, user.is_active
            new_role = role.value if role is not None else old_role
            new_active = is_active if is_active is not None else old_active
            was_active_owner = old_active and old_role == Role.OWNER.value
            stays_active_owner = new_active and new_role == Role.OWNER.value
            if was_active_owner and not stays_active_owner and len(owners) == 1:
                raise AppError(
                    409,
                    ErrorCode.LAST_OWNER,
                    "Last owner",
                    "An organisation must keep at least one active owner.",
                )

            await uow.users.set_role_and_active(
                principal.org_id, user.id, role=role.value if role else None, is_active=is_active
            )
            if password_hash is not None:
                await uow.users.set_password_hash(principal.org_id, user.id, password_hash)
            if password_hash is not None or (new_active and not old_active):
                # An owner resetting a password, or reactivating someone, also clears a lockout
                await uow.users.set_lockout(principal.org_id, user.id, after_success())
            if password_hash is not None or new_active != old_active or new_role != old_role:
                await uow.refresh_tokens.revoke_all_for_user(principal.org_id, user.id, now)
            await uow.session.refresh(user)
        log.info("user_updated", org_id=str(principal.org_id), user_id=str(user_id))
        return user

    async def deactivate(self, principal: Principal, user_id: uuid.UUID) -> None:
        """DELETE /users/{id}: users are deactivated, never removed, so history keeps its actors."""
        await self.update(principal, user_id, is_active=False)
