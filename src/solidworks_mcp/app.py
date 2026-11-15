"""Shared FastMCP application and COM dispatch helpers.

The tool declarations live in :mod:`solidworks_mcp.tools`; this module owns the
FastMCP instance, the connect-time instructions, the guide resource and the
session/worker wiring so tool modules can register without importing server.py.
"""

import asyncio
import sys
from importlib import resources

from mcp.server.fastmcp import FastMCP

from .errors import SolidWorksError

# Shown to the model by every MCP client at connect time, so keep it short; the
# long version is the solidworks://guide resource.
INSTRUCTIONS = """\
Builds, measures and verifies parametric parts and assemblies in the user's running SolidWorks.

Conventions
- Millimetres and degrees. New geometry starts on the Front plane (XY) and extrudes along +Z from z = 0. add_box spans x 0..w, y 0..h; add_disc is centred on the origin; revolves turn about Y.
- Faces are picked by direction: '+z', '-x', ... *_on_face tools take 3D points on the face and use the face facing that way through them (the top, a pocket floor, a step); '+z:outer' / '+z:inner' force the outermost / innermost one. Other tools use the outermost face.
- Every sketch is fully defined. Tools return `dimensions` ({role: 'width@Sketch1', ...}): change one with set_dimension, or drive several from a global variable via set_equation.
- Other orientations: add_plane (an offset, or turned about x/y/z) and build on it with add_extruded_profile_on_plane or cut_profile_through_plane.
- In a part a person drew, their sketches and planes work by name: read_sketch, extrude_sketch, cut_sketch; plane='Plane1' in add_mirror and cut_profile_through_plane.
- Flowing outlines (an S-bend, a hub running into a beam): add_sketch with lines, tangent arcs and splines, then extrude_sketch / cut_sketch.
- A joint: concentric mate (cylinders by list_faces index, '#5') + coincident + angle mate; the angle mate's dimension turns it (set_dimension, check_motion).

Design intent
- Plan the feature tree before the first call and show it to the user: base sketch, main shape (extrude, revolve or loft), shell, openings, bosses and details, fillets last (fillets that shape the body before the shell).
- To change a shape, change what makes it: set_dimension, set_equation, or the sketch (read_sketch). Do not stack bodies and cuts at the end of the tree to imitate a new shape: every call succeeds, and the part ends up with slivers, slots and fins. Rebuild the part when its source cannot change safely.
- Details that must meet a surface (bosses, ribs, walls) extrude up to it (extrude_sketch up_to='next'), not a fixed depth, so they follow later changes.
- When an operation is missing or refused (a reorder that will not move), stop and tell the user; do not approximate it with other tools.

Work in small verified steps
- Every modelling call returns volume, mass and bounding box: check them against your own hand calculation after each step, and fix the first mismatch before adding more. Where a hand calculation cannot judge the shape, measure it: slice_mesh on an export, check_printability, check_interference, a screenshot.
- Look before selecting by index: list_faces / list_edges; screenshot to see the shape.
- Undo a wrong step with delete_feature; list_features shows the history, also of a part opened from disk.
- {ok: false, error} means the tool refused or SolidWorks failed; the error names the cause, and the part is left as it was.

Pitfalls
- Walls shared by successive polygon cuts must use identical points: sections a few micrometres apart leave sliver faces and the next cut fails.
- Round polygon corners with corner_radii_mm (real sketch fillets; equal radii share one dimension). Other curves: revolves, splines, slots and holes.
- add_mirror needs its plane where the copies land in material: add_box spans x 0..w, so mirror about offset_mm = w / 2, not x = 0.
- SolidWorks' memory grows in long sessions: on a low-memory warning, save and restart SolidWorks (never during a run).

Read the resource solidworks://guide for the full guide: recipes (holes, ribs, threads, patterns, assemblies), 3D printing, and reverse-engineering a part from a mesh.
中文用户可读 solidworks://guide-zh（中文建模指南，GB 标准与常用配方）。
"""

mcp = FastMCP("solidworks-mcp", instructions=INSTRUCTIONS)


@mcp.resource(
    "solidworks://guide",
    name="guide",
    mime_type="text/markdown",
    description="Modelling guide: conventions, verification, recipes, 3D printing, "
    "reverse-engineering from a mesh, limits.",
)
def guide() -> str:
    return resources.files("solidworks_mcp").joinpath("guide.md").read_text(encoding="utf-8")


@mcp.resource(
    "solidworks://guide-zh",
    name="guide-zh",
    mime_type="text/markdown",
    description="中文建模指南：GB 标准、约定、验证、常用配方、3D 打印和限制。",
)
def guide_zh() -> str:
    return resources.files("solidworks_mcp").joinpath("guide.zh-CN.md").read_text(encoding="utf-8")


class _NoSolidWorks:
    """Stand-in session off Windows: every method fails with a readable error.

    The server still starts and lists its tools there, because MCP directories
    introspect servers in a Linux container before listing them.
    """

    def __getattr__(self, name):
        def unavailable(*args, **kwargs):
            raise SolidWorksError(
                f"SolidWorks MCP only works on Windows with SolidWorks installed (this is {sys.platform})."
            )

        return unavailable


if sys.platform == "win32":
    import pythoncom

    from .com_worker import ComWorker
    from .session import SolidWorksSession

    _worker = ComWorker()
    _session = SolidWorksSession()
    _COM_ERROR = pythoncom.com_error
else:
    _worker = None
    _session = _NoSolidWorks()
    _COM_ERROR = ()  # an empty tuple matches no exception


async def _call(fn, *args, **kwargs) -> dict:
    """Run a session method on the COM thread and normalise errors to a result dict.

    It runs guarded: a call that fails leaves the current part as it was.
    """
    try:
        if _worker is None:
            return fn(*args, **kwargs)
        return await _worker.call(lambda: _session.run_guarded(fn, *args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the agent
        return _failure(exc)


async def _call_without_solidworks(fn, *args) -> dict:
    """Run a session method that only reads files, off the COM thread and
    without attaching to SolidWorks: it works while SolidWorks is gone."""
    try:
        return await asyncio.to_thread(fn, *args)
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the agent
        return _failure(exc)


def _failure(exc) -> dict:
    """A failed call as the result dict the agent reads."""
    if isinstance(exc, SolidWorksError):
        return {"ok": False, "error": str(exc)}
    if isinstance(exc, _COM_ERROR):
        # Extract the human-readable description if SolidWorks supplied one;
        # raw HRESULT tuples are useless as a correction-loop signal.
        info = getattr(exc, "excepinfo", None)
        desc = info[2] if info and len(info) > 2 and info[2] else getattr(exc, "strerror", None)
        return {"ok": False, "error": f"SolidWorks COM error: {desc or exc}"}
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
