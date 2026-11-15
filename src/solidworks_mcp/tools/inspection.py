"""Dimensions, equations, feature history, materials, bodies, mass properties, faces/edges and printability.

Thin MCP wrappers: validate arguments, delegate to the session and
normalise failures through :func:`solidworks_mcp.app._call`.
"""

from ..app import _call, _call_without_solidworks, _session, mcp


@mcp.tool()
async def set_dimension(dimension_name: str, value_mm: float) -> dict:
    """Set a named driving dimension (e.g. 'D1@BlockExtrude') in mm, rebuild, and remeasure.

    This is the parametric edit at the heart of the correction loop. The result's
    broken_features names the features that fail since the change (a later cut
    now off the part, a split whose bodies moved): fix or undo them first. Every
    modelling tool returns its dimensions by role in `dimensions`. An angle (a
    revolve, an angle mate) takes degrees; list_dimensions shows the unit. A
    point's coordinate from the origin (a sketch's 'x3', 'y2') takes a sign,
    -5 being across the origin; any other length is a size, refused below 0.
    A value SolidWorks does not take (a dimension an equation drives, a size
    of 0) is refused with the reason, and the part is left as it was.
    """
    return await _call(_session.set_dimension, dimension_name, value_mm)


@mcp.tool()
async def list_dimensions(contains: str | None = None) -> dict:
    """List every dimension in the current part: name (for set_dimension), feature, value, unit.

    For a part opened from disk, or when the names the tools returned are gone.
    contains (e.g. 'Sketch3' or 'Pad') keeps those whose name or feature holds
    that text; use it on a large part, whose full list is too long to read.
    """
    return await _call(_session.list_dimensions, contains)


@mcp.tool()
async def list_features() -> dict:
    """List the current part's modelling history in tree order: name, type, suppressed.

    For a part opened from disk, or to find the step to undo. Flags features
    that fail to rebuild and names sketches that are not fully defined.
    """
    return await _call(_session.list_features)


@mcp.tool()
async def delete_feature(
    name: str, with_children: bool = False, with_equations: bool = False, dry_run: bool = False
) -> dict:
    """Delete a feature (a list_features name) with its sketch, then rebuild and remeasure.

    The way to undo a step. Refuses when other features are built on it and
    names them, and what is built on those; with_children=True deletes them
    all. dry_run=True only lists what would go (would_delete). Equations that
    named its dimensions break and come back as broken_equations;
    with_equations=True deletes them (global variables stay).
    """
    return await _call(_session.delete_feature, name, with_children, with_equations, dry_run)


@mcp.tool()
async def suppress_feature(name: str, suppress: bool = True) -> dict:
    """Suppress a feature, or bring it back with suppress=False; rebuild and remeasure.

    Keeps the feature and its dimensions, unlike delete_feature, so it suits
    trying a variant. Features that depend on it follow both ways.
    """
    return await _call(_session.suppress_feature, name, suppress)


@mcp.tool()
async def reorder_feature(name: str, before: str) -> dict:
    """Move a feature (a list_features name), with its sketch, to just before another one; rebuild and remeasure.

    For a boss added last that filled holes cut earlier: build it at the end
    as usual, then move it before the first of those cuts, and they cut
    through it again. Reference planes and axes it is built on move along
    (moved_along); refused, the part as it was, when it is built on another
    feature at or after that place. Returns the new order (features) and the
    features that fail to rebuild (failing_features).
    """
    return await _call(_session.reorder_feature, name, before)


@mcp.tool()
async def set_appearance(
    rgb: list | None = None, transparency: float | None = None, component: str | None = None
) -> dict:
    """Colour and/or see-through of the current part, or of one component in an assembly.

    rgb: [r, g, b], 0..255 each; transparency: 0 solid .. 1 clear (0 makes a
    see-through component solid again). In an assembly, component names it
    ('Bracket-1', 'Leg-1/Thigh-1'); the colour then belongs to the assembly and
    the part keeps its own. What is left out stays as it was.
    """
    return await _call(_session.set_appearance, rgb, transparency, component)


@mcp.tool()
async def set_material(name: str, database: str = "", density_kg_m3: float | None = None) -> dict:
    """Assign a material by name (e.g. "6061 Alloy", "AISI 1020", "ABS").

    Makes mass and density reflect a real material instead of the 1000 kg/m鲁
    default. One SolidWorks does not have (say "TPU") comes with its density:
    density_kg_m3=1210 makes it, by that name, carrying only the density.
    The English names work on a SolidWorks in another language too.
    Returns mass properties including density.
    """
    return await _call(_session.set_material, name, database, density_kg_m3)


@mcp.tool()
async def set_equation(equation: str) -> dict:
    """Add an equation, or replace the one that sets the same name; rebuild and remeasure.

    A SolidWorks equation string, e.g. '"D1@BlockExtrude" = 25' or
    '"D1@BlockExtrude" = 2 * "D1@Sketch1"'. A global variable is '"W" = 40';
    link a dimension to it with '"width@Sketch1" = "W"', and set '"W" = 45'
    again to change it. Persists a relation (unlike set_dimension). Returns
    the index, whether it replaced one, the features that fail to rebuild
    (failing_features) and mass properties.
    """
    return await _call(_session.set_equation, equation)


@mcp.tool()
async def set_equations(equations: list) -> dict:
    """Add or replace a list of equations at once, with one rebuild at the end.

    As set_equation for each, in order (later ones may use earlier ones). A
    refused equation undoes the whole list. Returns per equation its index and
    whether it replaced one, failing_features and mass properties.
    """
    return await _call(_session.set_equations, equations)


@mcp.tool()
async def list_equations() -> dict:
    """List the equations and global variables: index, equation, name it sets, value, global.

    `broken` marks an equation that names a dimension or variable that is gone,
    as one left behind by delete_feature; delete_equation removes it.
    automatic_solve_order False means SolidWorks solves them as listed: one
    above the line that sets its variable then warns and lags a rebuild. Any
    set_equation turns it on.
    """
    return await _call(_session.list_equations)


@mcp.tool()
async def delete_equation(equation: str) -> dict:
    """Delete an equation by the name it sets ("L_thigh", "D1@Boss") or its list_equations index.

    Rebuilds and returns what was deleted, failing_features and mass properties.
    """
    return await _call(_session.delete_equation, equation)


@mcp.tool()
async def rebuild(top_only: bool = False) -> dict:
    """Force a rebuild of the current part or assembly and report whether it rebuilt without errors.

    In an assembly, mate_errors names each mate SolidWorks flags, and each
    mate that lost a face or edge it used (it rebuilds fine, but holds nothing).
    """
    return await _call(_session.rebuild, top_only)


@mcp.tool()
async def get_mass_properties() -> dict:
    """Get volume (mm^3), mass (kg), surface area (mm^2), centre of mass, and bounding box."""
    return await _call(_session.get_mass_properties)


@mcp.tool()
async def get_bounding_box() -> dict:
    """Get the tight bounding box of the current part (min/max/size in mm)."""
    return await _call(_session.get_bounding_box)


@mcp.tool()
async def list_faces(component: str | None = None) -> dict:
    """List the part's faces (index, planar?, normal, area, centre) for inspection.

    A cylindrical face also gives its axis, radius and a point on the axis (for
    a hole: its centre), so hole patterns can be read off. component: a
    component of the current assembly, listed in its own frame (e.g. an
    imported servo); for a sub-assembly, every part's faces in the
    sub-assembly's frame, each naming its part. A part's indices shift as
    features are added; a component's are ordered by part, type, centre and
    area, so they stay while its shape does. add_mate takes them as '#5'.
    """
    return await _call(_session.list_faces, component)


@mcp.tool()
async def list_edges(
    face: str | None = None,
    feature: str | None = None,
    within_mm: list | None = None,
    min_length_mm: float | None = None,
) -> dict:
    """List the part's edges: index, type, length, ends; lines also axis and midpoint.

    Narrow it on a big part: face (a list_faces index, "#5"), feature (the edges
    of the faces it made), within_mm ([[x1, y1, z1], [x2, y2, z2]]: both ends
    inside), min_length_mm. Indices are always those of the whole part: use them
    with add_fillet/add_chamfer edges="2,5".
    """
    return await _call(_session.list_edges, face, feature, within_mm, min_length_mm)


@mcp.tool()
async def list_bodies() -> dict:
    """List the part's solid bodies: name, volume and bounding box.

    A part holds several after merge=False or split_body; combine_bodies joins
    them again.
    """
    return await _call(_session.list_bodies)


@mcp.tool()
async def combine_bodies(operation: str, main: str, tools: list | None = None, name: str = "Combine") -> dict:
    """Combine solid bodies of the part into `main` (a list_bodies name).

    operation 'add' joins the tools to main, 'subtract' cuts them out of it,
    'common' keeps only what main shares with them. tools: body names, every
    other body by default. Returns mass properties and the bodies left.
    """
    return await _call(_session.combine_bodies, operation, main, tools, name)


@mcp.tool()
async def split_body(plane: str, name: str = "Split") -> dict:
    """Split the part's body in two along a plane (front/top/right or a plane by name).

    The two bodies come back by name: combine them differently, or check each
    with list_bodies. Use add_plane first for a cut anywhere else.
    """
    return await _call(_session.split_body, plane, name)


@mcp.tool()
async def check_printability(up: str = "+z", overhang_deg: float = 45.0, min_wall_mm: float | None = None) -> dict:
    """Check the current part for 3D printing, built along `up` ('+z', '-y', ...).

    Overhangs: downward faces leaning more than overhang_deg from vertical (90 =
    a flat ceiling) need support; the faces on the bed do not count. Gives the
    overhanging area per face (list_faces index) with its worst lean and centre,
    the bed contact area and the print height. Islands: each place where the
    print starts in the air, its height above the bed, centre and faces; a
    downward edge between faces too steep to overhang still needs support
    there. Unsupported edges: stretches of such an edge with air below, also
    where the rest of it rests on material (the ends of a chamfered pad's edge
    beside a tube), with length, height, centre and faces. With min_wall_mm (e.g. two
    nozzle widths) also the walls thinner than that, measured straight through
    the material from points spread over every face, with where each is thinnest;
    that stops after a minute on a detailed part, and `rays` then says how much
    it measured.
    A spot right beside an edge where faces meet at a sharp angle reads as thin
    as the wedge of material there is: that is the edge, not a wall.
    """
    return await _call(_session.check_printability, up, overhang_deg, min_wall_mm)


@mcp.tool()
async def slice_mesh(path: str, axis: str, heights_mm: list, frame: str = "object") -> dict:
    """Cross-sections of an STL/3MF mesh at the given heights along axis 'x'/'y'/'z'.

    For modelling a part that must fit something that only exists as a mesh.
    Returns each section's closed loops, largest first, as polygon points (mm)
    ready to use as profiles. frame (3MF): 'object' (the mesh's own frame) or
    'build' (as placed on the slicer's plate). Needs no SolidWorks.
    """
    return await _call_without_solidworks(_session.slice_mesh, path, axis, heights_mm, frame)


@mcp.tool()
async def compare_with_mesh(
    path: str, axis: str, heights_mm: list, frame: str = "object", offset_mm: list | None = None
) -> dict:
    """Compare the current part's cross-sections with a reference mesh's at the same heights.

    offset_mm [dx, dy, dz] moves the mesh into the part's frame. A different
    area means a misread feature; equal areas with different extents a
    shifted frame. Returns per-section pairs and the worst differences.
    """
    return await _call(_session.compare_with_mesh, path, axis, heights_mm, frame, offset_mm)
