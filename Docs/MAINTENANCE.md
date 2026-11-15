# Maintenance

## Upstream sync

This repository tracks [`hjbaard/SolidWorks-MCP`](https://github.com/hjbaard/SolidWorks-MCP).
The fork relationship, commit baseline and step-by-step merge procedure are in
[`../UPSTREAM.md`](../UPSTREAM.md).

Key rule: upstream still has a single `session.py`; map each changed method into
the matching mixin under `src/solidworks_mcp/session/` and do not rewrite method
bodies while syncing.

## Dependency policy

- Runtime dependencies are deliberately small: `mcp` and Windows-only `pywin32`.
- `mcp` is pinned below 2.0 because 2.x renamed `FastMCP`; a major upgrade needs a
  deliberate migration PR, not a Dependabot merge.
- Dependabot runs weekly for `pip` and GitHub Actions.
- A dependency PR may merge only when all four CI jobs pass and the changelog
  explains any behaviour change.
- After changing `pyproject.toml`, refresh the lock file with `uv lock` and commit
  `uv.lock`.
- GitHub Actions are pinned by version tag. Prefer updating them through
  Dependabot, with a green CI run.

## Security response

- Use GitHub private vulnerability reporting (`Security` → `Report a
  vulnerability`); see [`../SECURITY.md`](../SECURITY.md).
- Do not disclose a vulnerability in a public issue before a fix is released.
- A security fix gets a patch release and a `Security` changelog entry.
- Rotate any credential that was ever committed; do not rely on history
  rewriting alone.

## Module ownership

| Area | Modules | Owner |
|---|---|---|
| MCP surface | `src/solidworks_mcp/app.py`, `server.py`, `tools/` | maintainer |
| COM plumbing | `com_worker.py`, `binding.py`, `constants.py`, `units.py` | maintainer |
| Part modelling | `session/solids.py`, `sweeps.py`, `holes.py`, `face_features.py`, `cuts.py` | maintainer |
| Modifiers | `session/fillets.py`, `chamfers_shells.py`, `mirrors.py`, `patterns_planes.py` | maintainer |
| Parameters/history | `session/parameters.py`, `feature_history.py`, `person_sketch.py` | maintainer |
| Inspection/printability | `session/inspection.py`, `printability.py`, `mesh_io.py` | maintainer |
| Assemblies | `session/assembly_core.py`, `assembly_mates.py`, `assembly_analysis.py` | maintainer |
| Export/IO | `session/export_io.py`, `session/mesh_io.py` | maintainer |
| Pure helpers | `mesh_tools.py`, `region_tools.py`, `sketch_constraints.py`, `free_sketch.py` | maintainer |

This table is a routing aid, not a lock: a change may touch several modules when
the behaviour genuinely crosses domains.

## Deprecation

- Announce a deprecation in `CHANGELOG.md` and the tool docstring.
- Keep the old tool working for at least one minor release.
- Remove it only in a major release.
- Update `README.md`, `guide.md` and the tests in the same change.

## Documentation upkeep

- `Docs/README.md` is the documentation index.
- A process change updates `Docs/ENGINEERING.md` and the relevant guide.
- A standard, tolerance or drawing-convention change updates
  `Docs/MODELING-STANDARDS.md` and `src/solidworks_mcp/guide.md`.
- A module/layer change updates `Docs/ARCHITECTURE.md`.
- A test/CI change updates `Docs/TESTING.md`.
- A release-process change updates `Docs/RELEASING.md`.
- A platform/version change updates `Docs/COMPATIBILITY.md`.
