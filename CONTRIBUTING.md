# Contributing to TaskHub

TaskHub follows a lightweight branch-and-pull-request workflow based on GitHub Flow. Keep each change focused, testable, and easy to review.

## Development setup

Requirements:

- Python 3.11
- Docker Desktop
- Git

Create and activate a virtual environment:

    /opt/homebrew/bin/python3.11 -m venv .venv
    source .venv/bin/activate
    python --version

After the dependency files are available, install the project dependencies:

    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    python -m pip install -r requirements-dev.txt

Use `python -m pip` inside the virtual environment instead of a global `pip` command.

## Development workflow

1. Update the local `main` branch.
2. Create a short-lived branch for one feature or project concern.
3. Implement and test the scoped change.
4. Commit logical changes using Conventional Commits.
5. Push the branch and open a pull request.
6. Review the complete diff.
7. Merge only after the required checks pass.

Keep unrelated changes in separate pull requests.

## Branch naming

Use lowercase names with a short category prefix:

    feat/auth
    feat/workspace
    feat/task
    fix/task-assignment
    test/rbac
    docs/readme
    chore/docker-setup

Recommended prefixes:

- `feat`: new functionality
- `fix`: bug fix
- `test`: test changes
- `docs`: documentation changes
- `chore`: tooling, build, or project maintenance

## Commit messages

Follow the Conventional Commits format:

    <type>(<scope>): <short description>

Examples:

    feat(auth): implement token refresh
    fix(task): validate workspace membership
    test(rbac): cover viewer permissions
    docs(readme): update Docker setup
    chore(docker): add database healthcheck

Use concise, imperative descriptions.

## Python conventions

Follow PEP 8, PEP 257, and the project Ruff configuration.

- Use `snake_case` for modules, functions, and variables.
- Use `PascalCase` for classes.
- Use `UPPER_SNAKE_CASE` for constants.
- Add type hints to application code.
- Prefer clear and explicit implementations over unnecessary abstractions.
- Keep functions focused on one responsibility.
- Keep comments and docstrings concise and written in English.

## Database changes

Every database schema change must include an Alembic migration.

Before committing a migration:

- review the generated operations;
- verify the upgrade and downgrade behavior;
- confirm that unrelated schema changes are not included.

## Security and configuration

Do not commit:

- `.env` files;
- passwords;
- JWT secrets;
- API tokens;
- SMTP credentials;
- other sensitive configuration.

Use `.env.example` to document required environment variables with safe placeholder values.

## Pull requests

Each pull request should include:

- a concise summary;
- the implemented behavior or endpoints;
- migration impact, when applicable;
- instructions for testing;
- known limitations, if any.

Before requesting a merge, run:

    ruff format --check .
    ruff check .
    mypy app
    pytest

Review the complete diff before merging.

## References

- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [PEP 8 — Style Guide for Python Code](https://peps.python.org/pep-0008/)
- [PEP 257 — Docstring Conventions](https://peps.python.org/pep-0257/)
