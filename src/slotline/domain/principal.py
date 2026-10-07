"""Who is calling: a staff user (role decides access) or an API key (scopes decide access)."""

import uuid
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    STAFF = "staff"


class Scope(StrEnum):
    """What an API key may do. Staff users implicitly hold every scope."""

    AVAILABILITY_READ = "availability:read"
    CUSTOMERS_READ = "customers:read"
    CUSTOMERS_WRITE = "customers:write"
    BOOKINGS_READ = "bookings:read"
    BOOKINGS_WRITE = "bookings:write"
    WAITLIST_READ = "waitlist:read"
    WAITLIST_WRITE = "waitlist:write"


ALL_SCOPES: frozenset[str] = frozenset(scope.value for scope in Scope)


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. `org_id` always comes from the credential, never the request."""

    org_id: uuid.UUID
    role: Role | None  # None for API keys
    scopes: frozenset[str]
    user_id: uuid.UUID | None = None
    key_id: uuid.UUID | None = None
    # The refresh-token family this access token was issued from (users only)
    session_family_id: uuid.UUID | None = None

    @property
    def is_user(self) -> bool:
        return self.user_id is not None

    def has_scope(self, scope: Scope) -> bool:
        return scope.value in self.scopes
