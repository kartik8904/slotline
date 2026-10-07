import uuid

from fastapi import APIRouter, Response

from slotline.api.deps import ApiKeysServiceDep, OwnerPrincipal, PaginationDep
from slotline.schemas.api_keys import ApiKeyCreated, ApiKeyOut, CreateApiKeyRequest
from slotline.schemas.common import Page

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", status_code=201, response_model=ApiKeyCreated, summary="Create an API key")
async def create_api_key(
    body: CreateApiKeyRequest,
    response: Response,
    principal: OwnerPrincipal,
    service: ApiKeysServiceDep,
) -> ApiKeyCreated:
    """The full key is in this response only. Store it now; it can't be shown again."""
    api_key, key = await service.create(
        principal, name=body.name, scopes=[scope.value for scope in body.scopes]
    )
    response.headers["Cache-Control"] = "no-store"
    return ApiKeyCreated.model_validate(
        {**ApiKeyOut.model_validate(api_key).model_dump(), "key": key}
    )


@router.get("", response_model=Page[ApiKeyOut], summary="List API keys (never the secrets)")
async def list_api_keys(
    principal: OwnerPrincipal, service: ApiKeysServiceDep, page: PaginationDep
) -> Page[ApiKeyOut]:
    keys, next_cursor = await service.list_keys(principal, limit=page.limit, after=page.after)
    return Page[ApiKeyOut](
        items=[ApiKeyOut.model_validate(k) for k in keys], next_cursor=next_cursor
    )


@router.delete("/{key_id}", status_code=204, summary="Revoke an API key")
async def revoke_api_key(
    key_id: uuid.UUID, principal: OwnerPrincipal, service: ApiKeysServiceDep
) -> Response:
    await service.revoke(principal, key_id)
    return Response(status_code=204)
