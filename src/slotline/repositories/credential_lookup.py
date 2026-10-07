"""The only queries that run before the tenant is known (plan C21).

Login, token refresh and API-key authentication start from a credential, and the credential is
what tells us the organisation. Everything after these lookups goes through the org-scoped
repositories using the `org_id` found here. The repository scan test allows exactly this module.
"""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.models import ApiKey, RefreshToken, User


class CredentialLookup:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email_for_update(self, email: str) -> User | None:
        """Row-locks the user so parallel login attempts for one account run one at a time."""
        stmt = select(User).where(User.email == email).with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    async def revoke_refresh_token_if_active(
        self, token_hash: str, now: datetime
    ) -> RefreshToken | None:
        """Atomically claims a refresh token for rotation: exactly one caller gets the row."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(RefreshToken)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        return (await self._session.scalars(stmt)).one_or_none()
