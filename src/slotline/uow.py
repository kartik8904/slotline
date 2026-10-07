"""Unit of work: `async with uow:` is one database transaction owned by a service."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from slotline.repositories.api_keys import ApiKeyRepository
from slotline.repositories.credential_lookup import CredentialLookup
from slotline.repositories.organizations import OrganizationRepository
from slotline.repositories.refresh_tokens import RefreshTokenRepository
from slotline.repositories.users import UserRepository


class UnitOfWork:
    """Commits when the block ends cleanly, rolls back when it raises.

    It can be entered more than once (each time opens a fresh session), but never nested.
    Anything that must survive an error response (a failed-login counter, a revoked token
    family) is written inside the block, and the error is raised after the block has exited.
    """

    session: AsyncSession
    organizations: OrganizationRepository
    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    api_keys: ApiKeyRepository
    lookup: CredentialLookup

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self.session = self._session_factory()
        await self.session.begin()
        self.organizations = OrganizationRepository(self.session)
        self.users = UserRepository(self.session)
        self.refresh_tokens = RefreshTokenRepository(self.session)
        self.api_keys = ApiKeyRepository(self.session)
        self.lookup = CredentialLookup(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()
