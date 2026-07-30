from enum import StrEnum


class UserRole(StrEnum):
    """System-level user roles."""

    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class WorkspaceMemberRole(StrEnum):
    """Workspace membership roles."""

    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class ProjectStatus(StrEnum):
    """Project lifecycle states."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TaskStatus(StrEnum):
    """Task workflow states."""

    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"


class TaskPriority(StrEnum):
    """Task priority levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    """Return explicit enum values for PostgreSQL enum storage."""
    return [member.value for member in enum_class]
