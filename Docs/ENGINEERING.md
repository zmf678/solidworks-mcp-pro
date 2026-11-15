# Engineering standards

This repository is an engineering-hardened fork of
[`hjbaard/SolidWorks-MCP`](https://github.com/hjbaard/SolidWorks-MCP). The upstream
project supplies the modelling engine and the tool surface; this fork adds the
engineering controls below. The aim is to keep the proven behaviour while making
the codebase easier to change, review and release.

## 1. Non-negotiable principles

1. **Behaviour first.** Refactors preserve the public MCP tool names, arguments
   and result shapes. A refactor that changes behaviour is a feature change and
   needs its own tests and changelog entry.
2. **One COM session, one thread.** SolidWorks COM is STA and thread-affine.
   Every COM call goes through `ComWorker` on the dedicated `solidworks-com`
   thread. Never call COM from the asyncio event loop or a worker pool.
3. **Errors are data.** A failed tool returns `{"ok": false, "error": "..."}`.
   Raw COM exceptions and stack traces must not reach the agent.
4. **Every mutation verifies itself.** A modelling call returns measured volume,
   mass and bounding box, and dimensions or mates are measured back after a
   rebuild. A call that cannot do what was asked fails loud instead of returning
   plausible but wrong geometry.
5. **A fixed, typed tool surface.** There is no arbitrary-code or shell tool.
   The agent can only call the declared MCP tools.
6. **Local only.** The server talks to a running SolidWorks instance over COM.
   It makes no network calls and stores no credentials.
7. **Small, explicit modules.** A module has one reason to change. If a module
   grows past roughly 600 lines or takes on a second domain, split it.
8. **GB is the default modelling and drawing standard.** Millimetres, first-angle
   projection, GB hole/thread tables and GB drawing templates where supplied.
   ISO remains an explicit fallback (`standard="ISO"`); the mapping and
   non-claims are in [`MODELING-STANDARDS.md`](MODELING-STANDARDS.md).

## 2. Required checks

| Area | Standard | Enforced by |
|---|---|---|
| Python | 3.11+, `src/` layout, setuptools build backend | `pyproject.toml`, CI |
| Formatting | Ruff formatter, 120-column lines | `ruff format --check src tests` |
| Linting | Ruff `E4`, `E7`, `E9`, `F`, `I`, `UP` | `ruff check src tests` |
| Typing | Public functions annotated; mypy covers the core modules first | `uv run mypy` |
| Unit tests | No SolidWorks required; fast and deterministic | `pytest -m "not solidworks"` |
| Integration tests | `solidworks` marker; real SolidWorks; hand-calculated expectations | local run before merge |
| Coverage | Statement + branch coverage, floor 35%, report uploaded | `pytest --cov`, CI artifact |
| Packaging | sdist + wheel build, metadata check | `uv build`, `twine check` |
| Versioning | SemVer; `pyproject.toml`, `server.json`, `__version__` agree | `tests/test_packaging.py` |
| Changelog | Every user-visible change under `[Unreleased]` | PR checklist |
| Security | No secrets, no network calls, no arbitrary code execution | review + `SECURITY.md` |

## 3. Definition of done

A change is done only when all of the following are true:

- [ ] The behaviour is covered by a unit test, or by an integration test when it
      touches COM/SolidWorks.
- [ ] `uv run pytest -m "not solidworks"` passes.
- [ ] `uv run ruff check src tests` and `uv run ruff format --check src tests` pass.
- [ ] `uv run mypy` passes.
- [ ] `CHANGELOG.md` has an `[Unreleased]` entry.
- [ ] User-facing docs are updated (`README.md`, `src/solidworks_mcp/guide.md`,
      or `Docs/`).
- [ ] No public tool name or argument changed without an explicit breaking-change
      note.
- [ ] No new runtime dependency was added without a rationale in the PR.
- [ ] No secret, token, local path or machine-specific sample file is committed.

## 4. Module boundaries

```
src/solidworks_mcp/
  server.py          entry point and re-exports; keeps `python -m` / console script
  app.py             FastMCP instance, connect-time instructions, guide resource, dispatch
  tools/             MCP tool declarations by domain
    core.py          lifecycle and connection tools
    solids.py        extrusion, revolve, sweep, loft, planes, ribs
    features.py      holes, threads, face features, cuts, fillets, patterns, shells
    sketch.py        sketch reading and person-authored sketches
    inspection.py    dimensions, equations, history, materials, bodies, printability
    io.py            documents, export, screenshots, drawings
    assembly.py      assemblies, components, mates, interference, motion
  com_worker.py      one dedicated STA thread; serialises all COM calls
  binding.py         early-binding plumbing around generated typelib wrappers
  constants.py       enum values read from the installed SolidWorks typelib
  units.py           mm <-> m and degrees <-> radians at the COM boundary
  errors.py          SolidWorksError -> agent-facing {ok:false,error}
  mesh_tools.py      pure STL/3MF geometry helpers
  region_tools.py    pure swept-region helpers
  sketch_constraints.py  pure sketch degree-of-freedom planner
  free_sketch.py     free-sketch planning helpers
  session/
    __init__.py      composes SolidWorksSession from the domain mixins
    _constants.py    class-level constants shared by the mixins
    _decorators.py   _reads_only and other shared decorators
    core.py          connection, documents, guarded calls, COM-thread helpers
    geometry.py      default planes, face/edge selection, extrude helper
    sketching.py     sketch drawing and polygon/constraint helpers
    solids.py        box, extruded profile, spline, disc, cylinder, cone, revolve
    sweeps.py        sweeps, lofts and ribs
    holes.py         holes, counterbores, threads, Hole Wizard
    face_features.py features on planar faces (holes, bosses, pads, text)
    cuts.py          profile cuts, pockets, slots
    fillets.py       fillets, variable fillets, full rounds
    chamfers_shells.py chamfers and shells
    mirrors.py       body and feature mirrors
    patterns_planes.py linear/circular patterns and reference planes
    parameters.py    dimensions, equations and dimension listings
    feature_history.py feature tree, suppression, reordering
    person_sketch.py reading and building on person-authored sketches
    materials.py     appearance and material assignment
    inspection.py    mass properties, faces, edges, bodies
    printability.py  overhang, island and thin-wall analysis
    mesh_io.py       mesh sectioning/comparison
    export_io.py     export, screenshots, drawings
    assembly_core.py assembly documents, components, transforms
    assembly_mates.py mates and mate measurement
    assembly_analysis.py interference, distance, motion, swept regions
```

Rules for the `session/` package:

- Methods call each other through `self`; a mixin module must not import another
  mixin module (that would create cycles and freeze the MRO).
- Shared state lives in `CoreMixin.__init__`; shared constants live in
  `SessionConstants`.
- `SolidWorksSession` is the only public class. Add a new mixin to
  `session/__init__.py` and keep the method names unique across mixins.

Rules for `tools/`:

- Each module declares only `@mcp.tool()` wrappers for one domain. No COM logic.
- A wrapper validates arguments, delegates to `_session.<method>` through
  `_call`, and returns the session dict. File-only tools use
  `_call_without_solidworks`.
- `server.py` re-exports the tools for scripts and tests, and owns the CLI entry
  point. Do not put new tool bodies there.

Rules for the rest:

- Pure helpers stay outside `session/` so they can be tested without Windows or
  SolidWorks.

## 5. Testing standard

Two layers:

1. **Unit layer** (default): pure helpers, selector parsing, geometry maths,
   packaging metadata and tool-forwarding checks. It must run on a machine with
   no SolidWorks and finish in seconds.
2. **Integration layer** (`-m solidworks`): drives a running SolidWorks, builds
   real features and compares each measured result with a hand calculation.
   Every part test uses the `part` fixture, which also asserts that no sketch was
   left under-defined.

The coverage floor is deliberately modest (35%) because the COM integration
suite cannot run in CI. The number to improve is the pure-logic coverage; do not
lower the floor to make a change pass.

## 6. Versioning and release

- SemVer: patch for fixes, minor for tools/features, major for breaking changes.
- The version lives in `pyproject.toml`, `server.json` and
  `solidworks_mcp.__version__`; `tests/test_packaging.py` enforces agreement.
- Update `CHANGELOG.md` before tagging.
- CI must be green before a release.
- **This fork does not publish to PyPI or the public MCP Registry.** The upstream
  publish workflow is kept for reference but guarded so it can only run in the
  upstream repository. A fork release is a GitHub release only.

## 7. Documentation map

| Document | Owns |
|---|---|
| `README.md` | user-facing install, tool overview, quickstart |
| `Docs/README.md` | documentation index |
| `Docs/ENGINEERING.md` | standards and definition of done |
| `Docs/MODELING-STANDARDS.md` | GB modelling and drawing standard, mapping and non-claims |
| `Docs/ARCHITECTURE.md` | layers, request flow, module map |
| `Docs/TESTING.md` | test layers, commands, CI coverage |
| `Docs/RELEASING.md` | versioning and release process |
| `Docs/COMPATIBILITY.md` | supported platforms and selftest |
| `Docs/MAINTENANCE.md` | upstream sync, dependencies, security, ownership |
| `CONTRIBUTING.md` | development setup and PR rules |
| `SECURITY.md` | private vulnerability reporting |
| `UPSTREAM.md` | fork relationship and sync procedure |

## 8. Known debt

- Mypy currently covers the core modules only. The mixins are dynamically typed
  around COM and will need a Protocol/stub layer before whole-package checking.
- The `tools/` modules are deliberately repetitive MCP wrappers (88 tools). They
  are thin by design; logic lives in the session mixins.
- Integration tests need a licensed, running SOLIDWORKS on Windows. They are not
  part of CI.
- The `main` branch is protected by the `main-protection` ruleset: a pull
  request is required, the four CI jobs must pass on an up-to-date branch, and
  deletion/force-push are blocked. The repository is public, so these protections
  are enforced server-side.
- Upstream merges require mapping changes from the old single `session.py` into
  the relevant mixin. See `UPSTREAM.md`.
