# Releasing

**English** | [简体中文](zh-CN/RELEASING.md)

This fork does **not** publish the upstream PyPI package or the public MCP
Registry entry. A release here is a GitHub release with source and build
artifacts. The upstream publish workflow is guarded and only runs in
`hjbaard/SolidWorks-MCP`.

## Versioning

Follow [Semantic Versioning](https://semver.org/):

- **patch** — bug fix, no public tool change;
- **minor** — new tool, new argument, new capability;
- **major** — breaking tool signature, result shape, or minimum platform change.

The version must agree in all three places:

1. `pyproject.toml` → `[project].version`
2. `server.json` → `version` and `packages[0].version`
3. `src/solidworks_mcp/__init__.py` → `__version__`

`tests/test_packaging.py` enforces the agreement.

## Changelog

Add a section under `## [Unreleased]` in `CHANGELOG.md` while developing. At
release time, rename it to the new version and date, then add a fresh
`[Unreleased]` heading. Group entries as `Added`, `Changed`, `Fixed`, `Removed`
or `Security`.

## Release checklist

```powershell
uv sync --extra dev

uv run pytest -m "not solidworks"
uv run pytest -m solidworks          # on a machine with SOLIDWORKS
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest -m "not solidworks" --cov=solidworks_mcp --cov-report=term-missing
uv build
uv run twine check dist/*
```

Then:

- [ ] CI is green on `main`.
- [ ] `CHANGELOG.md` has the release section.
- [ ] Version is bumped in all three files.
- [ ] README/guide reflect user-facing changes.
- [ ] The working tree is clean.
- [ ] A signed tag `vX.Y.Z` is created and pushed.
- [ ] A GitHub release is created from the tag.
- [ ] The release notes link the changelog and note any breaking change.
- [ ] No PyPI or MCP Registry publish is attempted from this fork.

## Tag and release

```powershell
git checkout main
git pull --ff-only
git tag -a v0.21.0 -m "v0.21.0"
git push origin v0.21.0

gh release create v0.21.0 --title "0.21.0" --notes-file Docs/RELEASE_NOTES_0.21.0.md
```

Build artifacts may be attached manually:

```powershell
uv build
gh release upload v0.21.0 dist/solidworks_mcp-0.21.0-py3-none-any.whl dist/solidworks_mcp-0.21.0.tar.gz
```

## Hotfix

1. Branch from the release tag: `git switch -c hotfix/v0.21.1 v0.21.0`.
2. Apply the minimal fix and add a regression test.
3. Bump the patch version, update the changelog and open a PR to `main`.
4. After merge, tag `v0.21.1` and publish a GitHub release.

## Rollback

- A bad release is superseded by a new patch release; do not move or delete a
  published tag.
- If a release workflow fails before publishing, fix the workflow and re-run it
  from the same tag.
- If a dependency update breaks the build, revert the dependency commit and
  refresh `uv.lock` with `uv lock`.

## Fork policy

- The fork's GitHub releases are for this repository only.
- The upstream `publish.yml` is kept for reference and guarded by
  `github.repository == 'hjbaard/SolidWorks-MCP'`.
- If this fork ever needs its own package, rename the distribution and the MCP
  server identity first; do not reuse `solidworks-mcp` or
  `io.github.hjbaard/solidworks-mcp`.
