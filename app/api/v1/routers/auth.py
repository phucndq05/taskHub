from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import AuthServiceDep
from app.schemas.auth import RefreshTokenRequest, TokenResponse
from app.schemas.user import UserRead, UserRegister
from app.services.auth import (
    DuplicateEmailError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)

router = APIRouter(prefix="/auth", tags=["auth"])

BEARER_HEADERS = {"WWW-Authenticate": "Bearer"}


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: UserRegister,
    service: AuthServiceDep,
) -> UserRead:
    try:
        return await service.register(request)
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc


@router.post(
    "/login",
    response_model=TokenResponse,
    description="Use the OAuth2 form username field for the user's email address.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Email or password is incorrect.",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "The user account is inactive.",
        },
    },
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: AuthServiceDep,
) -> TokenResponse:
    try:
        return await service.login(form_data.username, form_data.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers=BEARER_HEADERS,
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        ) from exc


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: RefreshTokenRequest,
    service: AuthServiceDep,
) -> TokenResponse:
    try:
        return await service.refresh(request.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers=BEARER_HEADERS,
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        ) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: RefreshTokenRequest,
    service: AuthServiceDep,
) -> Response:
    try:
        await service.logout(request.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers=BEARER_HEADERS,
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
