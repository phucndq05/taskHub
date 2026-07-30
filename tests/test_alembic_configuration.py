import ast
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
ALEMBIC_DIR = PROJECT_ROOT / "alembic"
ALEMBIC_ENV = ALEMBIC_DIR / "env.py"
ALEMBIC_TEMPLATE = ALEMBIC_DIR / "script.py.mako"


def build_alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def test_alembic_config_loads_expected_paths() -> None:
    config = build_alembic_config()

    assert config.config_file_name == str(ALEMBIC_INI)
    assert config.get_main_option("script_location") == str(ALEMBIC_DIR)
    assert config.get_main_option("prepend_sys_path") == "."
    assert config.get_main_option("path_separator") == "os"


def test_alembic_config_does_not_store_database_credentials() -> None:
    config = build_alembic_config()
    ini_contents = ALEMBIC_INI.read_text(encoding="utf-8")

    assert config.get_main_option("sqlalchemy.url") == ""
    assert "taskhub_dev_password" not in ini_contents
    assert "postgresql+asyncpg://taskhub" not in ini_contents
    assert "localhost" not in ini_contents


def test_script_directory_loads_initial_revision() -> None:
    config = build_alembic_config()
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    bases = script.get_bases()

    assert Path(script.dir).resolve() == ALEMBIC_DIR
    assert len(heads) == 1
    assert heads == bases

    revision = script.get_revision(heads[0])
    assert revision is not None
    assert revision.down_revision is None


def test_required_alembic_files_and_initial_revision_exist() -> None:
    versions_dir = ALEMBIC_DIR / "versions"
    revision_files = sorted(versions_dir.glob("*.py"))

    assert ALEMBIC_ENV.is_file()
    assert ALEMBIC_TEMPLATE.is_file()
    assert versions_dir.is_dir()
    assert len(revision_files) == 1
    assert revision_files[0].name.endswith("_create_initial_schema.py")
    assert not (versions_dir / "__init__.py").exists()
    assert not (versions_dir / ".gitkeep").exists()
    assert not (versions_dir / "README").exists()


def test_alembic_config_percent_escaping_round_trip() -> None:
    config = build_alembic_config()
    raw_url = "postgresql+asyncpg://user:p%25word@example.invalid/example_test"
    config.set_main_option("sqlalchemy.url", raw_url.replace("%", "%%"))

    assert config.get_main_option("sqlalchemy.url") == raw_url


def test_alembic_env_has_safe_imports_and_no_schema_creation() -> None:
    tree = ast.parse(ALEMBIC_ENV.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    imported_names: set[str] = set()
    called_names: set[str] = set()
    called_attributes: set[str] = set()
    target_metadata_values: list[ast.expr] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imported_modules.add(node.module)
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_attributes.add(node.func.attr)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "target_metadata":
                    target_metadata_values.append(node.value)

    assert "app.main" not in imported_modules
    assert "app.db.session" not in imported_modules
    assert "app" in imported_modules
    assert "models" in imported_names
    assert "create_engine" not in imported_names
    assert "Session" not in imported_names
    assert "create_all" not in called_names
    assert "create_all" not in called_attributes
    assert len(target_metadata_values) == 1
    target_metadata_value = target_metadata_values[0]
    assert isinstance(target_metadata_value, ast.Attribute)
    assert target_metadata_value.attr == "metadata"
    base_attribute = target_metadata_value.value
    assert isinstance(base_attribute, ast.Attribute)
    assert base_attribute.attr == "Base"
    assert isinstance(base_attribute.value, ast.Name)
    assert base_attribute.value.id == "models"
