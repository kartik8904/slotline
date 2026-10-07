from fastapi import APIRouter, Response

from slotline.api.deps import AuthServiceDep, PrincipalDep, UserPrincipal
from slotline.schemas.auth import ChangePasswordRequest, MeResponse

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeResponse, summary="The current user or API key")
async def me(principal: PrincipalDep, auth: AuthServiceDep) -> MeResponse:
    info = await auth.me(principal)
    return MeResponse.model_validate(
        {
            "type": "user" if info.user is not None else "api_key",
            "organization": info.organization,
            "role": principal.role,
            "scopes": sorted(principal.scopes),
            "user": info.user,
            "api_key": info.api_key,
        }
    )


@router.post(
    "/password",
    status_code=204,
    summary="Change your own password; your other sessions are signed out",
)
async def change_password(
    body: ChangePasswordRequest, principal: UserPrincipal, auth: AuthServiceDep
) -> Response:
    await auth.change_password(principal, body.current_password, body.new_password)
    return Response(status_code=204)
