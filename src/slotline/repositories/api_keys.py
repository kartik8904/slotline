import uuid
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.models import ApiKey


class ApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        org_id: uuid.UUID,
        *,
        name: str,
        prefix: str,
        key_hash: str,
        scopes: list[str],
    ) -> ApiKey:
        key = ApiKey(org_id=org_id, name=name, prefix=prefix, key_hash=key_hash, scopes=scopes)
        self._session.add(key)
        await self._session.flush()
        return key

    async def get(self, org_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        stmt = select(ApiKey).where(ApiKey.org_id == org_id, ApiKey.id == key_id)
        return (await self._session.scalars(stmt)).one_or_none()

    async def list_page(
        self, org_id: uuid.UUID, *, limit: int, after: uuid.UUID | None
    ) -> list[ApiKey]:
        stmt = select(ApiKey).where(ApiKey.org_id == org_id).order_by(ApiKey.id).limit(limit + 1)
        if after is not None:
            stmt = stmt.where(ApiKey.id > after)
        return list((await self._session.scalars(stmt)).all())

    async def revoke(self, org_id: uuid.UUID, key_id: uuid.UUID, now: datetime) -> None:
        """Idempotent: a key that is already revoked keeps its original revoked_at."""
        await self._session.execute(
            update(ApiKey)
            .where(ApiKey.org_id == org_id, ApiKey.id == key_id, ApiKey.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def touch_last_used(
        self, org_id: uuid.UUID, key_id: uuid.UUID, now: datetime, older_than: datetime
    ) -> None:
        """Writes last_used_at only when it is missing or stale, to avoid a write per request."""
        await self._session.execute(
            update(ApiKey)
            .where(
                ApiKey.org_id == org_id,
                ApiKey.id == key_id,
                or_(ApiKey.last_used_at.is_(None), ApiKey.last_used_at < older_than),
            )
            .values(last_used_at=now)
        )
