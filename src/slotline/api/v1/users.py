import uuid

from fastapi import APIRouter, Response

from slotline.api.deps import OwnerPrincipal, PaginationDep, UsersServiceDep
from slotline.schemas.common import Page
from slotline.schemas.users import CreateUserRequest, UpdateUserRequest, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=201, response_model=UserOut, summary="Add a staff member")
async def create_user(
    body: CreateUserRequest, principal: OwnerPrincipal, service: UsersServiceDep
) -> UserOut:
    user = await service.create(principal, email=body.email, password=body.password, role=body.role)
    return UserOut.model_validate(user)


@router.get("", response_model=Page[UserOut], summary="List staff")
async def list_users(
    principal: OwnerPrincipal, service: UsersServiceDep, page: PaginationDep
) -> Page[UserOut]:
    users, next_cursor = await service.list_users(principal, limit=page.limit, after=page.after)
    return Page[UserOut](items=[UserOut.model_validate(u) for u in users], next_cursor=next_cursor)


@router.get("/{user_id}", response_model=UserOut, summary="One staff member")
async def get_user(
    user_id: uuid.UUID, principal: OwnerPrincipal, service: UsersServiceDep
) -> UserOut:
    return UserOut.model_validate(await service.get(principal, user_id))


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    summary="Change role, active flag or reset the password",
)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    principal: OwnerPrincipal,
    service: UsersServiceDep,
) -> UserOut:
    user = await service.update(
        principal,
        user_id,
        role=body.role,
        is_active=body.is_active,
        password=body.password,
    )
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204, summary="Deactivate a staff member")
async def deactivate_user(
    user_id: uuid.UUID, principal: OwnerPrincipal, service: UsersServiceDep
) -> Response:
    await service.deactivate(principal, user_id)
    return Response(status_code=204)
