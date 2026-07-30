import ast
from pathlib import Path

from sqlalchemy import CheckConstraint, Enum, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import class_mapper, configure_mappers
from sqlalchemy.sql.schema import Column, ColumnDefault, Table

from app import models
from app.db.base import NAMING_CONVENTION, Base
from app.db.mixins import utc_now
from app.models.enums import (
    ProjectStatus,
    TaskPriority,
    TaskStatus,
    UserRole,
    WorkspaceMemberRole,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_MODELS_DIR = PROJECT_ROOT / "app" / "models"

EXPECTED_TABLES = {
    "users",
    "workspaces",
    "workspace_members",
    "projects",
    "tasks",
    "labels",
    "task_labels",
    "comments",
    "refresh_tokens",
}

EXPECTED_COLUMNS = {
    "users": {
        "id",
        "email",
        "full_name",
        "hashed_password",
        "role",
        "is_active",
        "created_at",
        "updated_at",
    },
    "workspaces": {"id", "name", "owner_id", "created_at", "updated_at"},
    "workspace_members": {"workspace_id", "user_id", "role", "joined_at"},
    "projects": {
        "id",
        "workspace_id",
        "name",
        "description",
        "status",
        "created_by",
        "created_at",
        "updated_at",
    },
    "tasks": {
        "id",
        "project_id",
        "assignee_id",
        "title",
        "description",
        "status",
        "priority",
        "due_date",
        "created_by",
        "created_at",
        "updated_at",
    },
    "labels": {"id", "project_id", "name", "color", "created_at"},
    "task_labels": {"task_id", "label_id"},
    "comments": {"id", "task_id", "author_id", "content", "created_at"},
    "refresh_tokens": {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "revoked_at",
        "created_at",
    },
}

EXPECTED_PRIMARY_KEYS = {
    "users": ("id",),
    "workspaces": ("id",),
    "workspace_members": ("workspace_id", "user_id"),
    "projects": ("id",),
    "tasks": ("id",),
    "labels": ("id",),
    "task_labels": ("task_id", "label_id"),
    "comments": ("id",),
    "refresh_tokens": ("id",),
}

EXPECTED_FOREIGN_KEYS = {
    ("workspaces", "owner_id", "users", "id", "RESTRICT"),
    ("workspace_members", "workspace_id", "workspaces", "id", "CASCADE"),
    ("workspace_members", "user_id", "users", "id", "CASCADE"),
    ("projects", "workspace_id", "workspaces", "id", "RESTRICT"),
    ("projects", "created_by", "users", "id", "RESTRICT"),
    ("tasks", "project_id", "projects", "id", "RESTRICT"),
    ("tasks", "assignee_id", "users", "id", "SET NULL"),
    ("tasks", "created_by", "users", "id", "RESTRICT"),
    ("labels", "project_id", "projects", "id", "RESTRICT"),
    ("task_labels", "task_id", "tasks", "id", "CASCADE"),
    ("task_labels", "label_id", "labels", "id", "CASCADE"),
    ("comments", "task_id", "tasks", "id", "CASCADE"),
    ("comments", "author_id", "users", "id", "RESTRICT"),
    ("refresh_tokens", "user_id", "users", "id", "CASCADE"),
}

EXPECTED_NULLABILITY = {
    "users": {
        "id": False,
        "email": False,
        "full_name": False,
        "hashed_password": False,
        "role": False,
        "is_active": False,
        "created_at": False,
        "updated_at": False,
    },
    "workspaces": {
        "id": False,
        "name": False,
        "owner_id": False,
        "created_at": False,
        "updated_at": False,
    },
    "workspace_members": {
        "workspace_id": False,
        "user_id": False,
        "role": False,
        "joined_at": False,
    },
    "projects": {
        "id": False,
        "workspace_id": False,
        "name": False,
        "description": True,
        "status": False,
        "created_by": False,
        "created_at": False,
        "updated_at": False,
    },
    "tasks": {
        "id": False,
        "project_id": False,
        "assignee_id": True,
        "title": False,
        "description": True,
        "status": False,
        "priority": False,
        "due_date": True,
        "created_by": False,
        "created_at": False,
        "updated_at": False,
    },
    "labels": {
        "id": False,
        "project_id": False,
        "name": False,
        "color": False,
        "created_at": False,
    },
    "task_labels": {"task_id": False, "label_id": False},
    "comments": {
        "id": False,
        "task_id": False,
        "author_id": False,
        "content": False,
        "created_at": False,
    },
    "refresh_tokens": {
        "id": False,
        "user_id": False,
        "token_hash": False,
        "expires_at": False,
        "revoked_at": True,
        "created_at": False,
    },
}

EXPECTED_ENUM_COLUMNS = {
    ("users", "role"): ("user_role", UserRole, ("ADMIN", "MEMBER")),
    ("workspace_members", "role"): (
        "workspace_member_role",
        WorkspaceMemberRole,
        ("OWNER", "EDITOR", "VIEWER"),
    ),
    ("projects", "status"): ("project_status", ProjectStatus, ("ACTIVE", "ARCHIVED")),
    ("tasks", "status"): (
        "task_status",
        TaskStatus,
        ("TODO", "IN_PROGRESS", "IN_REVIEW", "DONE"),
    ),
    ("tasks", "priority"): (
        "task_priority",
        TaskPriority,
        ("LOW", "MEDIUM", "HIGH", "URGENT"),
    ),
}

EXPECTED_ORDINARY_INDEXES = {
    "projects": {
        "ix_projects_workspace_id_status": ("workspace_id", "status"),
    },
    "tasks": {
        "ix_tasks_project_id_status": ("project_id", "status"),
        "ix_tasks_project_id_priority": ("project_id", "priority"),
        "ix_tasks_project_id_assignee_id": ("project_id", "assignee_id"),
        "ix_tasks_project_id_created_at": ("project_id", "created_at"),
    },
}

EXPECTED_RELATIONSHIPS = {
    models.User: {
        "owned_workspaces": ("Workspace", True, "owner", False),
        "memberships": ("WorkspaceMember", True, "user", True),
        "created_projects": ("Project", True, "creator", False),
        "assigned_tasks": ("Task", True, "assignee", False),
        "created_tasks": ("Task", True, "creator", False),
        "comments": ("Comment", True, "author", False),
        "refresh_tokens": ("RefreshToken", True, "user", True),
    },
    models.Workspace: {
        "owner": ("User", False, "owned_workspaces", False),
        "memberships": ("WorkspaceMember", True, "workspace", True),
        "projects": ("Project", True, "workspace", False),
    },
    models.WorkspaceMember: {
        "workspace": ("Workspace", False, "memberships", False),
        "user": ("User", False, "memberships", False),
    },
    models.Project: {
        "workspace": ("Workspace", False, "projects", False),
        "creator": ("User", False, "created_projects", False),
        "tasks": ("Task", True, "project", False),
        "labels": ("Label", True, "project", False),
    },
    models.Task: {
        "project": ("Project", False, "tasks", False),
        "assignee": ("User", False, "assigned_tasks", False),
        "creator": ("User", False, "created_tasks", False),
        "task_label_associations": ("TaskLabel", True, "task", True),
        "comments": ("Comment", True, "task", True),
    },
    models.Label: {
        "project": ("Project", False, "labels", False),
        "task_label_associations": ("TaskLabel", True, "label", True),
    },
    models.TaskLabel: {
        "task": ("Task", False, "task_label_associations", False),
        "label": ("Label", False, "task_label_associations", False),
    },
    models.Comment: {
        "task": ("Task", False, "comments", False),
        "author": ("User", False, "comments", False),
    },
    models.RefreshToken: {
        "user": ("User", False, "refresh_tokens", False),
    },
}


def table(table_name: str) -> Table:
    return Base.metadata.tables[table_name]


def column(table_name: str, column_name: str) -> Column[object]:
    return table(table_name).c[column_name]


def primary_key_columns(table_name: str) -> tuple[str, ...]:
    return tuple(primary_key.name for primary_key in table(table_name).primary_key)


def foreign_key_inventory() -> set[tuple[str, str, str, str, str | None]]:
    return {
        (
            table_object.name,
            foreign_key.parent.name,
            foreign_key.column.table.name,
            foreign_key.column.name,
            foreign_key.ondelete,
        )
        for table_object in Base.metadata.tables.values()
        for foreign_key in table_object.foreign_keys
    }


def unique_constraint_inventory(table_name: str) -> set[tuple[str, tuple[str, ...]]]:
    inventory: set[tuple[str, tuple[str, ...]]] = set()
    for constraint in table(table_name).constraints:
        if isinstance(constraint, UniqueConstraint):
            constraint_name = constraint.name
            assert isinstance(constraint_name, str)
            inventory.add(
                (
                    constraint_name,
                    tuple(
                        constraint_column.name
                        for constraint_column in constraint.columns
                    ),
                )
            )
    return inventory


def default_arg(column_object: Column[object]) -> object:
    default = column_object.default
    assert isinstance(default, ColumnDefault)
    return default.arg


def onupdate_arg(column_object: Column[object]) -> object:
    onupdate = column_object.onupdate
    assert isinstance(onupdate, ColumnDefault)
    return onupdate.arg


def assert_uses_utc_now(default_callable: object) -> None:
    assert callable(default_callable)
    assert getattr(default_callable, "__name__", "") == utc_now.__name__
    assert getattr(default_callable, "__module__", "") == utc_now.__module__


def index_inventory(table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        index.name or "": tuple(index_column.name for index_column in index.columns)
        for index in table(table_name).indexes
    }


def enum_column(table_name: str, column_name: str) -> Enum:
    column_type = column(table_name, column_name).type
    assert isinstance(column_type, Enum)
    return column_type


def relationship_inventory(
    model_class: type[object],
) -> dict[str, tuple[str, bool, str | None, bool]]:
    mapper = class_mapper(model_class)
    return {
        relationship.key: (
            relationship.mapper.class_.__name__,
            relationship.uselist is True,
            relationship.back_populates,
            relationship.passive_deletes is True,
        )
        for relationship in mapper.relationships
    }


def test_metadata_uses_expected_naming_convention() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_metadata_contains_exact_canonical_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_metadata_contains_exact_columns() -> None:
    assert {
        table_name: set(table_object.columns.keys())
        for table_name, table_object in Base.metadata.tables.items()
    } == EXPECTED_COLUMNS


def test_metadata_contains_exact_primary_keys() -> None:
    assert {
        table_name: primary_key_columns(table_name) for table_name in EXPECTED_TABLES
    } == EXPECTED_PRIMARY_KEYS


def test_metadata_contains_exact_foreign_keys_and_ondelete() -> None:
    assert foreign_key_inventory() == EXPECTED_FOREIGN_KEYS
    assert len(foreign_key_inventory()) == 14


def test_metadata_contains_exact_column_nullability() -> None:
    assert {
        table_name: {
            column_name: column_object.nullable
            for column_name, column_object in table_object.columns.items()
        }
        for table_name, table_object in Base.metadata.tables.items()
    } == EXPECTED_NULLABILITY


def test_enum_columns_use_explicit_native_postgresql_values() -> None:
    for (
        table_name,
        column_name,
    ), (enum_name, enum_class, enum_values) in EXPECTED_ENUM_COLUMNS.items():
        column_type = enum_column(table_name, column_name)

        assert column_type.enum_class is enum_class
        assert column_type.name == enum_name
        assert column_type.native_enum is True
        assert tuple(column_type.enums) == enum_values
        assert tuple(member.value for member in enum_class) == enum_values
        assert column(table_name, column_name).server_default is None


def test_metadata_contains_only_canonical_unique_constraints() -> None:
    assert unique_constraint_inventory("users") == {("uq_users_email", ("email",))}
    assert unique_constraint_inventory("labels") == {
        ("uq_labels_project_id_name", ("project_id", "name"))
    }
    assert {
        table_name: unique_constraint_inventory(table_name)
        for table_name in EXPECTED_TABLES - {"users", "labels"}
    } == {table_name: set() for table_name in EXPECTED_TABLES - {"users", "labels"}}


def test_metadata_contains_only_canonical_indexes() -> None:
    assert index_inventory("projects") == EXPECTED_ORDINARY_INDEXES["projects"]
    assert index_inventory("tasks") == EXPECTED_ORDINARY_INDEXES["tasks"]

    workspace_member_indexes = index_inventory("workspace_members")
    assert workspace_member_indexes == {
        "ix_workspace_members_one_owner_per_workspace": ("workspace_id",)
    }

    tables_without_indexes = EXPECTED_TABLES - {
        "projects",
        "tasks",
        "workspace_members",
    }
    assert {
        table_name: index_inventory(table_name) for table_name in tables_without_indexes
    } == {table_name: {} for table_name in tables_without_indexes}


def test_workspace_owner_partial_unique_index() -> None:
    owner_index = next(
        index
        for index in table("workspace_members").indexes
        if index.name == "ix_workspace_members_one_owner_per_workspace"
    )
    predicate = owner_index.dialect_options["postgresql"]["where"]
    compiled_predicate = str(
        predicate.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert owner_index.unique is True
    assert tuple(index_column.name for index_column in owner_index.columns) == (
        "workspace_id",
    )
    assert "workspace_members.role = 'OWNER'" in compiled_predicate


def test_metadata_has_no_check_constraints() -> None:
    assert {
        table_name: [
            constraint
            for constraint in table_object.constraints
            if isinstance(constraint, CheckConstraint)
        ]
        for table_name, table_object in Base.metadata.tables.items()
    } == {table_name: [] for table_name in EXPECTED_TABLES}


def test_task_status_and_priority_have_no_defaults() -> None:
    for column_name in ("status", "priority"):
        task_column = column("tasks", column_name)

        assert task_column.default is None
        assert task_column.server_default is None


def test_user_is_active_has_python_and_server_defaults() -> None:
    is_active = column("users", "is_active")

    assert is_active.default is not None
    assert default_arg(is_active) is True
    assert is_active.server_default is not None


def test_timestamp_columns_use_application_defaults_and_onupdate() -> None:
    timestamp_tables = {"users", "workspaces", "projects", "tasks"}
    created_only_tables = {"labels", "comments", "refresh_tokens"}

    for table_name in timestamp_tables | created_only_tables:
        created_at = column(table_name, "created_at")
        assert created_at.default is not None
        assert_uses_utc_now(default_arg(created_at))
        assert created_at.server_default is None

    for table_name in timestamp_tables:
        updated_at = column(table_name, "updated_at")
        assert updated_at.default is not None
        assert_uses_utc_now(default_arg(updated_at))
        assert updated_at.onupdate is not None
        assert_uses_utc_now(onupdate_arg(updated_at))
        assert updated_at.server_default is None

    for table_name in created_only_tables | {"workspace_members", "task_labels"}:
        assert "updated_at" not in table(table_name).columns

    joined_at = column("workspace_members", "joined_at")
    assert joined_at.default is not None
    assert_uses_utc_now(default_arg(joined_at))
    assert joined_at.server_default is None
    assert set(table("task_labels").columns.keys()) == {"task_id", "label_id"}


def test_relationship_mappers_configure_with_expected_inventory() -> None:
    configure_mappers()

    assert {
        model_class.__name__: relationship_inventory(model_class)
        for model_class in EXPECTED_RELATIONSHIPS
    } == {
        model_class.__name__: relationships
        for model_class, relationships in EXPECTED_RELATIONSHIPS.items()
    }


def test_only_required_relationships_use_passive_deletes() -> None:
    passive_relationships = {
        (model_class.__name__, relationship_name)
        for model_class in EXPECTED_RELATIONSHIPS
        for relationship_name, relationship in relationship_inventory(
            model_class
        ).items()
        if relationship[3]
    }

    assert passive_relationships == {
        ("User", "memberships"),
        ("User", "refresh_tokens"),
        ("Workspace", "memberships"),
        ("Task", "task_label_associations"),
        ("Task", "comments"),
        ("Label", "task_label_associations"),
    }


def test_no_direct_many_to_many_or_refresh_token_self_reference() -> None:
    assert "labels" not in relationship_inventory(models.Task)
    assert "tasks" not in relationship_inventory(models.Label)
    assert "replaced_by_token_id" not in table("refresh_tokens").columns

    refresh_token_fks = {
        (foreign_key.parent.name, foreign_key.column.table.name)
        for foreign_key in table("refresh_tokens").foreign_keys
    }
    assert refresh_token_fks == {("user_id", "users")}


def test_no_invitation_or_notification_tables() -> None:
    assert "workspace_invitations" not in Base.metadata.tables
    assert "notifications" not in Base.metadata.tables


def test_model_package_does_not_import_application_module_or_database_runtime() -> None:
    forbidden_imports = {"app.main", "app.db.session"}

    for model_file in APP_MODELS_DIR.glob("*.py"):
        tree = ast.parse(model_file.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)

        assert imported_modules.isdisjoint(forbidden_imports)
