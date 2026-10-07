import uuid
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        org_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(
            org_id=org_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def revoke_family(self, org_id: uuid.UUID, family_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.org_id == org_id,
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def revoke_all_for_user(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        now: datetime,
        *,
        except_family_id: uuid.UUID | None = None,
    ) -> None:
        stmt = update(RefreshToken).where(
            RefreshToken.org_id == org_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        if except_family_id is not None:
            stmt = stmt.where(RefreshToken.family_id != except_family_id)
        await self._session.execute(stmt.values(revoked_at=now))
