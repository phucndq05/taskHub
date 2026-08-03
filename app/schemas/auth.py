from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyToken = Annotated[str, StringConstraints(min_length=1)]


class TokenResponse(BaseModel):
    """Response body for issued authentication tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Request body containing a refresh token."""

    refresh_token: NonEmptyToken

    model_config = ConfigDict(extra="forbid")
