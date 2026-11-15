"""Assembly documents, components, mates, interference, motion and swept regions.

Thin MCP wrappers: validate arguments, delegate to the session and
normalise failures through :func:`solidworks_mcp.app._call`.
"""

from ..app import _call, _session, mcp


@mcp.tool()
async def new_assembly() -> dict:
    """Create a new empty assembly document; it becomes the current document.

    Assemblies compose saved parts: insert_component places each part, add_mate
    constrains them, check_interference proves nothing overlaps.
    """
    return await _call(_session.new_assembly)


@mcp.tool()
async def open_assembly(path: str, allow_large: bool = False) -> dict:
    """Open a .sldasm, or import a STEP/IGES/Parasolid assembly; it becomes the current document.

    An imported assembly's parts arrive as components at their places, ready
    for list_components and add_mate; the result gives the component count.
    A file holding a single part is refused (use open_part), and an import over
    30 MB unless allow_large=True (it can outlast the 2-minute call limit).
    """
    return await _call(_session.open_assembly, path, allow_large)


@mcp.tool()
async def save_assembly(path: str) -> dict:
    """Save the current assembly to a native .sldasm file (so it can be reopened)."""
    return await _call(_session.save_assembly, path)


@mcp.tool()
async def insert_component(
    path: str, x_mm: float = 0.0, y_mm: float = 0.0, z_mm: float = 0.0, fixed: bool | None = None
) -> dict:
    """Insert a .sldprt, or a .sldasm as a sub-assembly, with its ORIGIN at (x, y, z) mm.

    The part's own origin lands exactly on that point, and the placement is read
    back and verified. fixed=True pins the component; fixed=False leaves it free
    for mates. The default fixes only the FIRST component, giving the assembly a
    ground to build against. Returns the component's name, placement and box.
    """
    return await _call(_session.insert_component, path, x_mm, y_mm, z_mm, fixed)


@mcp.tool()
async def list_components() -> dict:
    """List the assembly's components (name, path, fixed, position, rotation, bounding box) and mates.

    Positions are in mm and rotations in degrees, both in assembly coordinates;
    the bounding box of each component is in assembly coordinates too. Each
    mate gives its name, SolidWorks type, the dimension of a distance or angle
    mate, and an error when SolidWorks flags it. A component that shows no
    geometry carries a `problem` (see replace_component).
    """
    return await _call(_session.list_components)


@mcp.tool()
async def replace_component(name: str, path: str, reattach_mates: bool = True) -> dict:
    """Put another part or assembly file in the place of a component of the current assembly.

    Keeps its position and, with reattach_mates, its mates where they still
    find their faces; `mate_errors` lists the ones that do not. Also the cure
    for a component that vanished after its part was made anew under the same
    path. Returns the new component (name, path, placement, bounding box).
    """
    return await _call(_session.replace_component, name, path, reattach_mates)


@mcp.tool()
async def set_component_transform(
    name: str, x_mm: float, y_mm: float, z_mm: float, rx_deg: float = 0.0, ry_deg: float = 0.0, rz_deg: float = 0.0
) -> dict:
    """Move/rotate a component: its origin to (x, y, z) mm, rotated rx/ry/rz degrees.

    name is the component name ('Bed' or 'Bed-1'); rotations apply X, then Y,
    then Z about the assembly axes, and work on a fixed component too. The
    transform is read back and compared, so a move SolidWorks ignored (e.g. one
    already pinned by mates) fails loudly instead of silently leaving the part
    where it was.
    """
    return await _call(_session.set_component_transform, name, x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg)


@mcp.tool()
async def add_mate(
    comp_a: str,
    face_a: str,
    comp_b: str,
    face_b: str,
    mate_type: str = "coincident",
    distance_mm: float = 0.0,
    angle_deg: float = 0.0,
    flip: bool = False,
) -> dict:
    """Mate a face of one component to a face of another.

    comp_a/comp_b are component names ('Bed' or 'Bed-1'; 'Leg-1/Thigh-1' inside
    a sub-assembly). face_a/face_b select a face in that component's OWN frame:
    by direction "+x"/"-x"/"+y"/... (optionally "+y:inner" for the cavity side
    of a hollow part), by its list_faces(component=...) index, "#5", or by a
    point on it, "@x,y,z" (a hole's wall: its centre plus the radius along x).
    mate_type between planar faces:
    "coincident", "distance" (distance_mm), "parallel", "perpendicular" or
    "angle" (angle_deg between the faces' normals, 0..180); "concentric" between
    two cylindrical faces (a pin in a hole, a hinge axis), leaving the turn
    about the axis free. flip takes the other solution: the mirror side of a
    distance, the other turning direction of an angle. A distance or angle
    mate returns its `dimension`: drive it with
    set_dimension, or step it with check_motion. An angle mate's dimension
    then turns the joint the whole way round, past 180 and below 0 (-30 is 30
    the other way, the same turn as 330). The result is measured back
    after the rebuild; a mate that does not hold is removed and the components
    are put back.
    """
    return await _call(_session.add_mate, comp_a, face_a, comp_b, face_b, mate_type, distance_mm, angle_deg, flip)


@mcp.tool()
async def check_interference() -> dict:
    """Report component pairs whose solids overlap, with the volume in mm^3.

    Touching faces do not count (a bed standing on the floor is fine); only real
    overlapping material does. count == 0 means the assembly is clash-free.
    """
    return await _call(_session.check_interference)


@mcp.tool()
async def measure_distance(
    component_a: str, component_b: str | None = None, point_mm: list | None = None, axis_mm: list | None = None
) -> dict:
    """The smallest distance (mm) from a component to another one, a point or an axis.

    Give component_b; or point_mm = [x, y, z] in assembly mm, and the nearest
    point on the component comes back too, with inside: true when the point lies
    in its material; or axis_mm = [[x, y, z], [dx, dy, dz]], the endless line
    through that point along that direction, such as a bolt's axis. 0 means they
    touch or overlap; check_interference tells which. Sub-assemblies count with
    all their parts; one part inside is 'Leg-1/Thigh-1'.
    """
    return await _call(_session.measure_distance, component_a, component_b, point_mm, axis_mm)


@mcp.tool()
async def check_motion(dimension_name: str, values: list, distances: list | None = None) -> dict:
    """Step a joint through its range and check the assembly at every step.

    dimension_name: an angle or distance mate's dimension (add_mate returns it);
    values in degrees for an angle, mm for a distance, e.g. [30, 60, 90, 120,
    150]. Each step gives the overlapping pairs with their volume and the
    distance between each pair in distances ([["Rod", "Bolt"], ...]); the
    summary gives clash_free and each pair's smallest distance with the value
    where it occurs. The dimension goes back to its value afterwards. A joint
    inside a sub-assembly is 'D1@Angle1@Leg-1'. Refused while a mate is broken:
    the parts it should hold would drift and the result mean nothing.
    """
    return await _call(_session.check_motion, dimension_name, values, distances)


@mcp.tool()
async def swept_region(
    component: str,
    dimension: str,
    values: list,
    heights_mm: list,
    axis: str = "z",
    margin_mm: float = 0.0,
    tolerance_mm: float = 0.2,
    frame: str | None = None,
) -> dict:
    """Outline what a component covers in a plane while a joint moves, to keep
    clear of it or cut it away.

    Steps the joint's dimension through values (as check_motion, e.g. every
    5 degrees over 30..150), cuts the component at axis = each of heights_mm
    (a few heights inside a layer, not on its faces) and joins all of it, made
    margin_mm wider, within about tolerance_mm. frame: the component to give the
    coordinates in, such as the part to cut from; else the assembly's. Each
    region's outline runs counter-clockwise in the plane's other two axes,
    (x, y) across z: give it to add_sketch as a spline. count says how many
    separate regions there are.
    """
    return await _call(
        _session.swept_region, component, dimension, values, heights_mm, axis, margin_mm, tolerance_mm, frame
    )


@mcp.tool()
async def get_assembly_bounding_box() -> dict:
    """Get the bounding box of the whole assembly (min/max/size in mm)."""
    return await _call(_session.get_assembly_bounding_box)


@mcp.tool()
async def delete_mate(name: str) -> dict:
    """Delete a mate of the current assembly by name (list_components, or add_mate's 'mate').

    Its components are free to move again. Returns the mates left.
    """
    return await _call(_session.delete_mate, name)


@mcp.tool()
async def suppress_mate(name: str, suppress: bool = True) -> dict:
    """Suppress a mate so it stops holding its components (it stays in the tree), or bring it back.

    suppress=False brings it back. Returns whether it is suppressed now.
    """
    return await _call(_session.suppress_mate, name, suppress)


@mcp.tool()
async def delete_component(component: str) -> dict:
    """Remove a component from the current assembly, with the mates that hold it.

    component: its name in list_components ("Bracket-1", or "Bracket" while
    there is one). Returns the mates deleted, the components left and the
    assembly's mass properties.
    """
    return await _call(_session.delete_component, component)
