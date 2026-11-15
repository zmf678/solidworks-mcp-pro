# Contributing

Thanks for improving SolidWorks MCP. This is a Windows-first project: the unit
suite runs anywhere, but integration tests need a licensed, running SOLIDWORKS.

## Development setup

```powershell
git clone git@github.com:zmf678/solidworks-mcp-pro.git
cd solidworks-mcp-pro
uv sync --extra dev
```

All commands below assume the `uv` environment. To run the server from the
checkout instead of `uvx`, point your MCP client at
`.venv\Scripts\python.exe -m solidworks_mcp.server`.

## Checks before opening a pull request

```powershell
uv run pytest -m "not solidworks"
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

If your change touches COM behaviour, also run the integration suite with
SolidWorks open:

```powershell
uv run pytest -m solidworks
```

CI runs the unit layer, lint, format, mypy and a package build. Integration tests
are intentionally local because GitHub runners do not have SolidWorks.

## Where code goes

- `server.py`: MCP tool declarations only. Add a thin wrapper here.
- `src/solidworks_mcp/session/<domain>.py`: modelling operations. Put a new
  operation in the mixin that owns its domain.
- `src/solidworks_mcp/<helper>.py`: pure, testable helpers that do not need a
  live SolidWorks instance.
- `tests/`: one test module per domain. Unit tests must not require SolidWorks;
  mark integration tests with `@pytest.mark.solidworks`.

See `Docs/ARCHITECTURE.md` for the full module map, `Docs/TESTING.md` for the
test strategy and `Docs/ENGINEERING.md` for the definition of done.

## Commit and branch style

- Branch from `main`, use a short descriptive name (`fix/hole-face-selection`,
  `refactor/session-split`).
- Prefer Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`,
  `chore:`.
- Keep refactors behaviour-preserving and separate from feature changes.
- Do not commit local paths, sample CAD files, generated exports or secrets.

## Pull requests

Use the PR template. A PR should explain:

1. what changed and why;
2. how it was tested, including whether the SolidWorks integration suite ran;
3. any public tool/API impact;
4. the changelog entry.

Small, focused PRs are easier to review than a mixed refactor + feature PR.

## Upstream

This repository is a fork. Changes that also benefit upstream should be kept
isolated enough to propose there. See `UPSTREAM.md`.
