"""Documents, export, screenshots and drawings.

Thin MCP wrappers: validate arguments, delegate to the session and
normalise failures through :func:`solidworks_mcp.app._call`.
"""

from ..app import _call, _session, mcp


@mcp.tool()
async def export(
    path: str,
    file_format: str | None = None,
    quality: str = "fine",
    deviation_mm: float | None = None,
    angle_deg: float | None = None,
    per_component: bool = False,
) -> dict:
    """Export the current part or assembly to STEP/STL/IGES/Parasolid/3MF (format from extension).

    Silent (no prompts). Verifies the file appears on disk and reports its size.
    For STL/3MF, tessellation resolution is set first: quality 'coarse'|'fine'
    (default 'fine' for print quality), or pass deviation_mm (+ optional angle_deg)
    for a reproducible custom resolution (overrides quality). Ignored for other formats.
    An assembly goes to STL as one file, or one file per component with
    per_component=True (SolidWorks names them); `files` lists what was written.
    STL/3MF keep the part's or assembly's own coordinates (`frame`), also per
    component, so a mesh measures back where the model is; slicers place it anyway.
    """
    return await _call(_session.export, path, file_format, quality, deviation_mm, angle_deg, per_component)


@mcp.tool()
async def screenshot(
    path: str, view: str = "iso", zoom_mm: list | None = None, show_planes: bool = False, from_dir: list | None = None
) -> dict:
    """Save a screenshot of the current part or assembly (PNG/JPG/TIF).

    view: 'iso' (default), 'front', 'back', 'left', 'right', 'top' or 'bottom';
    or from_dir = [x, y, z], the direction to look from, e.g. [-1, 1, -1] to
    see from behind and below what iso hides (the model's +y stays up).
    Zoomed to fit, or onto a detail: zoom_mm = [[x1, y1, z1], [x2, y2, z2]], the
    corners of the region to fill the image (model mm, in any view). Reference
    planes and axes are left out, so they do not cut through the shape;
    show_planes=True keeps them.
    """
    return await _call(_session.screenshot, path, view, zoom_mm, show_planes, from_dir)


@mcp.tool()
async def make_drawing(path: str, template: str | None = None) -> dict:
    """Make a 2D drawing of the current part: a PDF, or an editable .slddrw.

    Front, top and right views in GB/T 14692 first-angle projection plus an
    isometric view, on an A4 sheet (GB/T 14689) at the scale SolidWorks picks,
    with the model's own dimensions, each shown once: a dimensioned sketch to
    print or send. template: optional .drwdot; pass SolidWorks' GB drawing
    template for a GB title block, or leave it None to use the default drawing
    template. Save the part first (save_part): the drawing refers to its file.
    """
    return await _call(_session.make_drawing, path, template)


@mcp.tool()
async def list_documents() -> dict:
    """List the documents open in SolidWorks: title, path (empty until saved), type, unsaved changes.

    `current` marks the one the tools work on, `active` SolidWorks' own. Parts
    an open assembly loaded come along, with visible false.
    """
    return await _call(_session.list_documents)


@mcp.tool()
async def activate_document(title: str) -> dict:
    """Make an open document current again by its title, also a new one that was never saved.

    For after open_part / close_part on another document; list_documents gives
    the titles.
    """
    return await _call(_session.activate_document, title)


@mcp.tool()
async def close_part(save: bool = False) -> dict:
    """Close the current part or assembly without saving (export/save first if needed).

    With no current document it closes SolidWorks' active one, but only when
    that has no unsaved changes.
    """
    return await _call(_session.close_part, save)


@mcp.tool()
async def save_part(path: str) -> dict:
    """Save the current part to a native .sldprt file (so it can be reopened/edited)."""
    return await _call(_session.save_part, path)


@mcp.tool()
async def open_part(path: str, allow_large: bool = False) -> dict:
    """Open a .sldprt, or import a STEP/IGES/Parasolid file as a new part; it becomes the current part.

    list_features shows its history, list_dimensions its dimensions. An
    imported body has no history, but the tools work on it (holes and pockets
    on its faces, bosses, fillets); an import returns its solid body count and
    mass properties. A file holding an assembly is refused, and an import over
    30 MB unless allow_large=True (it can outlast the 2-minute call limit).
    """
    return await _call(_session.open_part, path, allow_large)
