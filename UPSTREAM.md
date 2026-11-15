# Upstream relationship

This repository is a **fork** of
[`hjbaard/SolidWorks-MCP`](https://github.com/hjbaard/SolidWorks-MCP), created
from upstream `main` at commit `58ca7bf` (`v0.20.0`, 2026-11-13).

## What comes from upstream

- The SolidWorks COM integration, constants, modelling knowledge and the
  `SolidWorksSession` method bodies.
- The modelling guide (`src/solidworks_mcp/guide.md`), tool surface and docs.
- MIT-licensed code; the original copyright notice is preserved in `LICENSE` and
  `NOTICE`.

## What this fork adds

- A domain-modular `session/` package (the upstream single `session.py` is split
  into mixins; method bodies are unchanged).
- PR CI (lint, format, mypy, unit tests, package build), Dependabot, coverage
  reporting and a reproducible `uv.lock`.
- Engineering standards, architecture docs, contribution/security templates.
- Fork-safe release guards: the upstream publish workflow cannot publish from
  this repository.

The fork does **not** claim the upstream PyPI package or the
`io.github.hjbaard/solidworks-mcp` MCP Registry identity. Do not publish from this
fork under that name.

## Syncing upstream

Upstream still uses the monolithic `session.py`, so a plain `git merge
upstream/main` will conflict. The practical workflow is:

```powershell
git fetch upstream
git log --oneline HEAD..upstream/main
git diff HEAD..upstream/main -- src/solidworks_mcp/session.py
```

Then:

1. Identify the changed methods in the upstream `session.py` diff.
2. Apply each change to the matching mixin module in `src/solidworks_mcp/session/`
   (use `rg "def <method>" src/solidworks_mcp/session` to locate it).
3. Apply non-session changes normally (`server.py`, `constants.py`, docs, tests).
4. Run `uv run pytest -m "not solidworks"`, Ruff and mypy.
5. Run the relevant SolidWorks integration tests before merging.

For a large upstream release, consider merging the upstream commit first on a
temporary branch, then replaying the split with `git diff` and a mapping table.
Keep the split mechanical: do not rewrite upstream method bodies while syncing.

## Attribution

Upstream author: Henk Jan Baard (`hjbaard`). If you redistribute this fork, keep
the MIT license text and the `NOTICE` file.
