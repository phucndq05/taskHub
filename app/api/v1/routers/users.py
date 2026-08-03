from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentActiveUserDep, UserServiceDep
from app.schemas.user import PasswordChangeRequest, UserProfileUpdate, UserRead
from app.services.user import (
    IncorrectCurrentPasswordError,
    NoProfileChangesError,
    SamePasswordError,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def get_me(current_user: CurrentActiveUserDep) -> UserRead:
    return UserRead.model_validate(current_user)


@router.patch("/me", response_model=UserRead)
async def update_me(
    request: UserProfileUpdate,
    current_user: CurrentActiveUserDep,
    service: UserServiceDep,
) -> UserRead:
    try:
        return await service.update_profile(current_user, request)
    except NoProfileChangesError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No profile changes provided",
        ) from exc


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: PasswordChangeRequest,
    current_user: CurrentActiveUserDep,
    service: UserServiceDep,
) -> Response:
    try:
        await service.change_password(current_user, request)
    except IncorrectCurrentPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password",
        ) from exc
    except SamePasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
