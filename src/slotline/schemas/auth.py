import uuid
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, StringConstraints

from slotline.domain.principal import Role
from slotline.schemas.api_keys import ApiKeyOut
from slotline.schemas.common import Email, LoginPassword, NewPassword, RequestModel, ResponseModel
from slotline.schemas.users import UserOut


def _valid_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError("Use an IANA time zone name such as Asia/Kolkata.") from None
    return value


Timezone = Annotated[str, AfterValidator(_valid_timezone)]


class OrganizationOut(ResponseModel):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str


class SignupRequest(RequestModel):
    organization_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    email: Email
    password: NewPassword
    timezone: Timezone | None = None


class SignupResponse(ResponseModel):
    organization: OrganizationOut
    user: UserOut


class LoginRequest(RequestModel):
    email: Email
    password: LoginPassword


class RefreshRequest(RequestModel):
    refresh_token: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class LogoutRequest(RefreshRequest):
    pass


class TokenResponse(ResponseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  # the OAuth token type, not a secret
    expires_in: int


class ChangePasswordRequest(RequestModel):
    current_password: LoginPassword
    new_password: NewPassword


class MeResponse(ResponseModel):
    type: Literal["user", "api_key"]
    organization: OrganizationOut
    role: Role | None
    scopes: list[str]
    user: UserOut | None = None
    api_key: ApiKeyOut | None = None
