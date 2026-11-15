# Architecture

**English** | [简体中文](zh-CN/ARCHITECTURE.md)

## Request flow

```mermaid
flowchart LR
    Client[MCP client] -->|stdio JSON-RPC| Server[server.py + tools/*.py<br/>FastMCP tools]
    Server -->|await ComWorker.call| Worker[com_worker.py<br/>dedicated STA thread]
    Worker --> Session[SolidWorksSession<br/>domain mixins]
    Session --> Binding[binding.py<br/>early-bound typelib wrappers]
    Binding --> COM[SolidWorks COM API]
    Session --> Pure[mesh_tools / region_tools<br/>sketch_constraints / free_sketch]
    Server -->|{ok:false,error}| Client
```

The server is a local stdio MCP process. It does not launch SolidWorks: it
attaches to a running instance with `GetActiveObject`.

## Layers

| Layer | Responsibility | Must not |
|---|---|---|
| `server.py` | CLI entry point, public re-exports, `main()` | Contain tool bodies or COM logic |
| `tools/` | Declare the 88 MCP tools by domain, validate shapes, delegate, normalise errors | Contain COM logic or modelling state |
| `app.py` | Own the FastMCP instance, connect-time instructions, guide resource, `_call`/`_failure`, session/worker wiring | Declare domain tools |
| `com_worker.py` | Own one STA thread and serialise every COM call | Call back into asyncio or run jobs concurrently |
| `binding.py` | Wrap raw dispatches in generated typelib interface classes; call by dispid | Assume late binding works |
| `session/` mixins | Implement modelling operations against the current document | Import another mixin module or keep module-level mutable state |
| pure helpers | Mesh slicing, region outlines, sketch degree-of-freedom planning | Depend on a live SolidWorks instance |

## Session composition

`solidworks_mcp.session.SolidWorksSession` is composed from domain mixins in
`session/__init__.py`:

```python
class SolidWorksSession(
    CoreMixin, GeometryMixin, SketchingMixin, SolidsMixin, SweepsMixin,
    HolesMixin, FaceFeaturesMixin, CutsMixin, FilletsMixin, ChamfersShellsMixin,
    MirrorsMixin, PatternsPlanesMixin, ParametersMixin, FeatureHistoryMixin,
    PersonSketchMixin, MaterialsMixin, InspectionMixin, PrintabilityMixin,
    MeshIOMixin, ExportIOMixin, AssemblyCoreMixin, AssemblyMatesMixin,
    AssemblyAnalysisMixin, SessionConstants,
):
    ...
```

The split is behavioural: the 346 method bodies were moved verbatim from the old
single `session.py`; only the `_IMPORT_LIMIT_MB` class reference became
`SessionConstants._IMPORT_LIMIT_MB` inside a static helper. All methods still
share the same `self`, so cross-domain helpers work exactly as before.

## State ownership

`CoreMixin.__init__` owns the mutable session state:

| Attribute | Meaning |
|---|---|
| `_sw` | early-bound `ISldWorks` |
| `_mod` | generated typelib wrapper module |
| `_model` | current `IModelDoc2` (part or assembly) |
| `_quiet_depth` | nesting depth of the "keep the UI still" guard |
| `_reading` | nesting depth of read-only tools |
| `_to_wake` | documents and properties to restore after a call |

`SessionConstants` owns class-level constants (tolerances, enum maps, limits).
Do not add mutable state at module level.

## Call lifecycle

1. The MCP client sends a tool call; the matching `tools/<domain>.py` wrapper
   receives it.
2. `_call(fn, ...)` submits `_session.run_guarded(fn, ...)` to `ComWorker`.
3. `run_guarded` takes a feature-tree snapshot, sets `CommandInProgress`, and
   calls the mixin method on the COM thread.
4. The method mutates SolidWorks and returns a JSON-serialisable dict.
5. On failure, `run_guarded` removes features added since the snapshot, restores
   the quiet state, and `_call` returns `{"ok": false, "error": "..."}`.
6. Pure file-only tools (`slice_mesh`, `compare_with_mesh`) bypass the COM worker
   through `_call_without_solidworks`.

## Adding a tool

1. Put the implementation in the mixin that owns the domain (for example a new
   hole variant goes in `session/holes.py`).
2. Add a thin `@mcp.tool()` wrapper in the matching module under
   `src/solidworks_mcp/tools/` (for example `tools/features.py`), with a
   docstring that states units, selectors and the result shape. Re-export the
   name from `server.py` if scripts/tests should keep importing it there.
3. Add a pure unit test for validation/geometry helpers and, when it touches
   SolidWorks, an integration test marked `solidworks` with a hand calculation.
4. Update `README.md`, `src/solidworks_mcp/guide.md` and `CHANGELOG.md`.
5. Run the checks from `CONTRIBUTING.md`.

## Why early binding and a dedicated thread

On the tested build, `GetActiveObject` returns a dispatch whose `GetTypeInfo()`
fails, so pure late binding breaks on calls such as
`IModelDoc2.FirstFeature`. `binding.py` generates makepy wrappers from the
installed typelib and wraps each raw dispatch in the right interface class.
COM is STA and thread-affine; `com_worker.py` pins all calls to one thread even
though the MCP server itself runs on an asyncio event loop.

## Failure model

- A failed call is a normal result, not an exception escaping to the MCP client.
- `SolidWorksError` carries a readable, actionable message.
- Raw COM errors are reduced to a readable description.
- A failed call rolls back features added during that call, so the part is left
  as it was.
- `CommandInProgress` and the quiet-view guard are always restored, including on
  failure.

## Further reading

- [`ENGINEERING.md`](ENGINEERING.md): required checks and definition of done.
- [`TESTING.md`](TESTING.md): test layers, commands and CI matrix.
- [`RELEASING.md`](RELEASING.md): versioning and release process.
- [`MAINTENANCE.md`](MAINTENANCE.md): dependency and upstream maintenance.
