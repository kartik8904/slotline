import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.domain.lockout import LockoutState
from slotline.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, org_id: uuid.UUID, *, email: str, password_hash: str, role: str
    ) -> User | None:
        """None when the email is taken: emails are unique across all organisations (C1)."""
        stmt = (
            insert(User)
            .values(org_id=org_id, email=email, password_hash=password_hash, role=role)
            .on_conflict_do_nothing(index_elements=["email"])
            .returning(User)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get(self, org_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.org_id == org_id, User.id == user_id)
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_for_update(self, org_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.org_id == org_id, User.id == user_id).with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    async def list_page(
        self, org_id: uuid.UUID, *, limit: int, after: uuid.UUID | None
    ) -> list[User]:
        stmt = select(User).where(User.org_id == org_id).order_by(User.id).limit(limit + 1)
        if after is not None:
            stmt = stmt.where(User.id > after)
        return list((await self._session.scalars(stmt)).all())

    async def lock_active_owners(self, org_id: uuid.UUID) -> list[User]:
        """Row-locks the active owners, so two owners can't demote each other at the same time."""
        stmt = (
            select(User)
            .where(User.org_id == org_id, User.role == "owner", User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
        return list((await self._session.scalars(stmt)).all())

    async def set_lockout(self, org_id: uuid.UUID, user_id: uuid.UUID, state: LockoutState) -> None:
        await self._session.execute(
            update(User)
            .where(User.org_id == org_id, User.id == user_id)
            .values(
                failed_login_count=state.failed_count,
                failed_login_window_started_at=state.window_started_at,
                locked_until=state.locked_until,
            )
        )

    async def set_password_hash(
        self, org_id: uuid.UUID, user_id: uuid.UUID, password_hash: str
    ) -> None:
        await self._session.execute(
            update(User)
            .where(User.org_id == org_id, User.id == user_id)
            .values(password_hash=password_hash)
        )

    async def set_role_and_active(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> None:
        values: dict[str, str | bool] = {}
        if role is not None:
            values["role"] = role
        if is_active is not None:
            values["is_active"] = is_active
        if values:
            await self._session.execute(
                update(User).where(User.org_id == org_id, User.id == user_id).values(**values)
            )
