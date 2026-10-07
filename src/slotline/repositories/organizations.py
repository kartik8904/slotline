import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.models import Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, name: str, slug: str, timezone: str, settings: dict[str, Any]
    ) -> Organization | None:
        """Creates a tenant (so there is no org_id yet). None when the slug is taken."""
        stmt = (
            insert(Organization)
            .values(name=name, slug=slug, timezone=timezone, settings=settings)
            .on_conflict_do_nothing(index_elements=["slug"])
            .returning(Organization)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get(self, org_id: uuid.UUID) -> Organization | None:
        return await self._session.get(Organization, org_id)
