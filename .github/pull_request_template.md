## What changed

<!-- A short description of the change and the user-visible effect. -->

## Why

<!-- The problem this solves, or the issue it closes. -->

## Checklist

- [ ] `uv run pytest -m "not solidworks"` passes.
- [ ] `uv run ruff check src tests` passes.
- [ ] `uv run ruff format --check src tests` passes.
- [ ] `uv run mypy` passes.
- [ ] A SolidWorks integration test was run if the change touches COM behaviour,
      or the PR explains why it could not be run.
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`.
- [ ] User-facing docs (`README.md`, `src/solidworks_mcp/guide.md`) are updated.
- [ ] Public tool names or signatures did not change, or the change is called out
      explicitly as a breaking change.
- [ ] No new dependency was added without a short rationale.
