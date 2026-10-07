import uuid
from datetime import datetime
from typing import Self

from pydantic import model_validator

from slotline.domain.principal import Role
from slotline.schemas.common import Email, NewPassword, RequestModel, ResponseModel


class UserOut(ResponseModel):
    id: uuid.UUID
    email: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateUserRequest(RequestModel):
    email: Email
    password: NewPassword
    role: Role = Role.STAFF


class UpdateUserRequest(RequestModel):
    role: Role | None = None
    is_active: bool | None = None
    password: NewPassword | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> Self:
        if self.role is None and self.is_active is None and self.password is None:
            raise ValueError("Provide at least one of role, is_active or password.")
        return self
