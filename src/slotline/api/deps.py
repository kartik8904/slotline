import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Query, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from slotline.clock import Clock
from slotline.config import Settings
from slotline.domain.principal import Principal, Role, Scope
from slotline.errors import AppError, ErrorCode, forbidden, unauthenticated
from slotline.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor
from slotline.security.tokens import JwtKeyring
from slotline.services.api_keys_service import ApiKeysService
from slotline.services.auth_service import AuthService
from slotline.services.users_service import UsersService
from slotline.uow import UnitOfWork

# auto_error=False: a missing credential becomes our Problem Details 401, not FastAPI's 403
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth", description="Staff JWT")
api_key_scheme = APIKeyHeader(
    name="X-API-Key", auto_error=False, scheme_name="ApiKeyAuth", description="Machine client key"
)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


def get_uow(request: Request) -> UnitOfWork:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return UnitOfWork(factory)


ClockDep = Annotated[Clock, Depends(get_clock)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]


def get_auth_service(request: Request, uow: UowDep, clock: ClockDep) -> AuthService:
    keyring: JwtKeyring = request.app.state.keyring
    return AuthService(uow, clock, keyring, request.app.state.settings)


def get_users_service(uow: UowDep, clock: ClockDep) -> UsersService:
    return UsersService(uow, clock)


def get_api_keys_service(uow: UowDep, clock: ClockDep) -> ApiKeysService:
    return ApiKeysService(uow, clock)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UsersServiceDep = Annotated[UsersService, Depends(get_users_service)]
ApiKeysServiceDep = Annotated[ApiKeysService, Depends(get_api_keys_service)]


async def login_rate_limit(request: Request) -> None:
    """Placeholder hook for the login and signup rate limit.

    Session 7 replaces this body with the Redis limiter (10 attempts a minute per IP, failing
    open when Redis is down, C12). Routes already depend on it, so nothing else changes then.
    """


async def current_principal(
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    api_key: Annotated[str | None, Depends(api_key_scheme)],
    auth: AuthServiceDep,
) -> Principal:
    """Authenticates a Bearer JWT (staff) or an X-API-Key (machine). The org comes from here."""
    if bearer is not None and api_key is not None:
        raise AppError(
            400,
            ErrorCode.INVALID_REQUEST,
            "Invalid request",
            "Send either a Bearer token or an API key, not both.",
        )
    if bearer is not None:
        principal = await auth.authenticate_bearer(bearer.credentials)
    elif api_key:
        principal = await auth.authenticate_api_key(api_key)
    else:
        raise unauthenticated()
    structlog.contextvars.bind_contextvars(org_id=str(principal.org_id))
    return principal


PrincipalDep = Annotated[Principal, Depends(current_principal)]


async def current_user(principal: PrincipalDep) -> Principal:
    """For endpoints that only make sense for a staff user, not an API key."""
    if not principal.is_user:
        raise forbidden("This endpoint is for staff users, not API keys.")
    return principal


UserPrincipal = Annotated[Principal, Depends(current_user)]


async def require_owner(principal: UserPrincipal) -> Principal:
    if principal.role != Role.OWNER:
        raise forbidden("The owner role is required.")
    return principal


OwnerPrincipal = Annotated[Principal, Depends(require_owner)]


def require_scope(scope: Scope) -> Callable[..., Awaitable[Principal]]:
    """For endpoints open to API keys: staff always pass, keys need the scope."""

    async def dependency(principal: PrincipalDep) -> Principal:
        if not principal.has_scope(scope):
            raise forbidden(f"The {scope.value} scope is required.")
        return principal

    return dependency


class Pagination:
    """`?limit=50&cursor=…` (plan conventions: cursor pagination, never offset, limit ≤ 100)."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        cursor: Annotated[str | None, Query(max_length=64)] = None,
    ) -> None:
        self.limit = limit
        self.after: uuid.UUID | None = decode_cursor(cursor)


PaginationDep = Annotated[Pagination, Depends()]
