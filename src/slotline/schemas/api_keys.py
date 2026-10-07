import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from slotline.domain.principal import Scope
from slotline.schemas.common import RequestModel, ResponseModel


def _unique(scopes: list[Scope]) -> list[Scope]:
    return list(dict.fromkeys(scopes))


class CreateApiKeyRequest(RequestModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    scopes: Annotated[list[Scope], Field(min_length=1), AfterValidator(_unique)]


class ApiKeyOut(ResponseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="The full API key. It is shown once and can't be retrieved.")
