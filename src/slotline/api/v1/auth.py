from fastapi import APIRouter, Depends, Response

from slotline.api.deps import AuthServiceDep, UserPrincipal, login_rate_limit
from slotline.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
)
from slotline.services.auth_service import TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(pair: TokenPair, response: Response) -> TokenResponse:
    response.headers["Cache-Control"] = "no-store"  # tokens must never sit in a shared cache
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post(
    "/signup",
    status_code=201,
    response_model=SignupResponse,
    dependencies=[Depends(login_rate_limit)],
    summary="Create an organisation and its owner",
)
async def signup(body: SignupRequest, auth: AuthServiceDep) -> SignupResponse:
    org, user = await auth.signup(
        organization_name=body.organization_name,
        email=body.email,
        password=body.password,
        timezone=body.timezone,
    )
    return SignupResponse.model_validate({"organization": org, "user": user})


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(login_rate_limit)],
    summary="Exchange email and password for tokens",
)
async def login(body: LoginRequest, response: Response, auth: AuthServiceDep) -> TokenResponse:
    return _token_response(await auth.login(body.email, body.password), response)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate a refresh token; reusing an old one revokes the whole family",
)
async def refresh(body: RefreshRequest, response: Response, auth: AuthServiceDep) -> TokenResponse:
    return _token_response(await auth.refresh(body.refresh_token), response)


@router.post("/logout", status_code=204, summary="Revoke the session of a refresh token")
async def logout(body: LogoutRequest, principal: UserPrincipal, auth: AuthServiceDep) -> Response:
    await auth.logout(principal, body.refresh_token)
    return Response(status_code=204)
