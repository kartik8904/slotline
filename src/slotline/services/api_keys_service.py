import uuid

import structlog

from slotline.clock import Clock
from slotline.domain.principal import Principal
from slotline.errors import not_found
from slotline.models import ApiKey
from slotline.pagination import paginate
from slotline.security.api_keys import generate_api_key
from slotline.uow import UnitOfWork

log = structlog.get_logger()


class ApiKeysService:
    """Owner-only management of machine credentials. The secret is returned once, at creation."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def create(
        self, principal: Principal, *, name: str, scopes: list[str]
    ) -> tuple[ApiKey, str]:
        new_key = generate_api_key()
        async with self._uow as uow:
            api_key = await uow.api_keys.add(
                principal.org_id,
                name=name,
                prefix=new_key.prefix,
                key_hash=new_key.key_hash,
                scopes=scopes,
            )
        log.info("api_key_created", org_id=str(principal.org_id), key_id=str(api_key.id))
        return api_key, new_key.key

    async def list_keys(
        self, principal: Principal, *, limit: int, after: uuid.UUID | None
    ) -> tuple[list[ApiKey], str | None]:
        async with self._uow as uow:
            rows = await uow.api_keys.list_page(principal.org_id, limit=limit, after=after)
        return paginate(rows, limit)

    async def revoke(self, principal: Principal, key_id: uuid.UUID) -> None:
        async with self._uow as uow:
            if await uow.api_keys.get(principal.org_id, key_id) is None:
                raise not_found("API key not found.")
            await uow.api_keys.revoke(principal.org_id, key_id, self._clock.now())
        log.info("api_key_revoked", org_id=str(principal.org_id), key_id=str(key_id))
