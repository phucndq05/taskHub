from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

CommentContent = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class CommentCreate(BaseModel):
    """Request body for creating a task comment."""

    content: CommentContent

    model_config = ConfigDict(extra="forbid")


class CommentRead(BaseModel):
    """Response body for a task comment."""

    id: UUID
    task_id: UUID
    author_id: UUID
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
