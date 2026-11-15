"""Holes, threads, face features, cuts, fillets, chamfers, patterns, mirrors and shells.

Thin MCP wrappers: validate arguments, delegate to the session and
normalise failures through :func:`solidworks_mcp.app._call`.
"""

from ..app import _call, _session, mcp


@mcp.tool()
async def add_thread(
    size: str, x_mm: float, y_mm: float, z_mm: float, length_mm: float, internal: bool = False, name: str = "Thread"
) -> dict:
    """Cut a real, printable GB/T 196/197 metric thread (SolidWorks' own Thread feature).

    size: e.g. 'M10x1.5', 'M3x0.5', 'M10x1.0' -- checked against SolidWorks'
    thread profiles. (x_mm, y_mm, z_mm) = centre of the circular edge where the
    thread starts: the end face of a rod, or the mouth of a hole (internal=True).
    It runs length_mm into the material, right-handed. External: the rod must
    have the nominal diameter (M10 -> Ø10). Internal: drill the GB/T 196 basic minor
    diameter first, D - 1.0825*P (M10x1.5 -> Ø8.376). Returns mass properties
    and the thread's size, pitch and diameters.
    """
    return await _call(_session.add_thread, size, x_mm, y_mm, z_mm, length_mm, internal, name)


@mcp.tool()
async def add_hole(diameter_mm: float, x_mm: float, y_mm: float, name: str = "Hole") -> dict:
    """Cut a circular through-hole at (x_mm, y_mm), through the part's depth axis.

    The hole runs straight through the thickness (the add_box extrude direction),
    perpendicular to the width x height profile face. Coordinates share add_box's
    system (the centre of a 40x20 profile is x=20, y=10). Returns mass properties.
    """
    return await _call(_session.add_hole, diameter_mm, x_mm, y_mm, name)


@mcp.tool()
async def add_counterbore_hole(
    clearance_diameter_mm: float,
    cbore_diameter_mm: float,
    cbore_depth_mm: float,
    x_mm: float,
    y_mm: float,
    name: str = "Counterbore",
) -> dict:
    """Cut a counterbored screw hole on the +Z face at (x_mm, y_mm).

    A clearance shank through the thickness plus a larger coaxial flat-bottom
    pocket of cbore_depth_mm from the top 鈥?so a cap-head screw or heat-set insert
    sits flush/recessed (common for 3D-printed parts). cbore_diameter must exceed
    clearance_diameter. Coordinates share add_box's system. Returns mass properties.
    """
    return await _call(
        _session.add_counterbore_hole, clearance_diameter_mm, cbore_diameter_mm, cbore_depth_mm, x_mm, y_mm, name
    )


@mcp.tool()
async def add_hole_on_face(
    diameter_mm: float,
    face: str,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    depth_mm: float | None = None,
    name: str = "Hole",
    from_edges: bool = False,
) -> dict:
    """Drill a round hole on ANY planar face, centred at 3D point (x, y, z) mm.

    face is "+x"/"-x"/"+y"/"-y"/"+z"/"-z": the face facing that way through the
    point is drilled, so a pocket floor or a step works too. Through all, or
    depth_mm deep (blind: heat-set inserts, screw pilots). Returns mass
    properties and `dimensions` (diameter, x, y, depth). from_edges=True
    measures x and y from the face's nearest straight edges instead of the
    origin, so the hole keeps its distance to them when the part changes
    (`measured_from` names the edges): use it where the design means it.
    """
    return await _call(_session.add_hole_on_face, diameter_mm, face, x_mm, y_mm, z_mm, depth_mm, name, from_edges)


@mcp.tool()
async def add_hole_wizard(
    kind: str,
    size: str,
    face: str,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    depth_mm: float | None = None,
    fit: str = "normal",
    thread: str = "cosmetic",
    name: str | None = None,
    standard: str = "GB",
) -> dict:
    """A GB (default) or ISO hole from SolidWorks' Hole Wizard.

    standard='GB' (default) uses GB/T 5277 clearance, GB/T 70.1 socket head
    cap, GB/T 70.3 countersunk socket head and GB tapped-hole tables;
    standard='ISO' uses the ISO 273/4762/10642 tables. kind: 'clearance',
    'counterbore', 'countersink' or 'tapped'; size e.g. 'M3'. Centred at
    (x, y, z) mm on the face through that point; through all, or depth_mm deep.
    fit: 'close' / 'normal' / 'loose'. For tapped holes thread='modeled' cuts a
    real, printable metric thread instead of SolidWorks' cosmetic one. Returns
    the standard's sizes in `hole` and mass properties.
    """
    return await _call(
        _session.add_hole_wizard, kind, size, face, x_mm, y_mm, z_mm, depth_mm, fit, thread, name, standard
    )


@mcp.tool()
async def add_boss_on_face(
    diameter_mm: float,
    face: str,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    height_mm: float,
    name: str = "Boss",
    from_edges: bool = False,
) -> dict:
    """Grow a round boss (standoff, peg) height_mm out of ANY planar face, centred at (x, y, z) mm.

    The face is found as for add_hole_on_face. For a PCB standoff, add a blind
    hole in its top. from_edges works as for add_hole_on_face. Returns mass
    properties and `dimensions`.
    """
    return await _call(_session.add_boss_on_face, diameter_mm, face, x_mm, y_mm, z_mm, height_mm, name, from_edges)


@mcp.tool()
async def add_extruded_profile_on_face(
    points_mm: list, face: str, depth_mm: float, name: str = "Boss", corner_radii_mm: float | list | None = None
) -> dict:
    """Grow a polygon boss depth_mm out of ANY planar face: points_mm = [[x,y,z], ...] in mm.

    The 3D points lie on the face (found as for add_hole_on_face). For pads,
    ledges and mounting blocks on an existing part. corner_radii_mm rounds the
    corners as for add_extruded_profile. Returns mass properties.
    """
    return await _call(_session.add_extruded_profile_on_face, points_mm, face, depth_mm, name, corner_radii_mm)


@mcp.tool()
async def add_text_on_face(
    text: str,
    face: str,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    height_mm: float,
    depth_mm: float,
    emboss: bool = False,
    font: str | None = None,
    name: str = "Text",
) -> dict:
    """Engrave text into ANY planar face, or emboss it with emboss=True (labels, version numbers).

    (x, y, z) is the text's lower-left corner on the face; the text runs along
    the face sketch's horizontal axis: upright along +x on the top (+z) and
    front (-y) faces, turned on the others (vertical on +/-x, upside down on
    +y), so put labels on the top or front. height_mm is the
    character height, depth_mm the engraving depth or embossing height. The
    position is two dimensions ('x', 'y'); font must be installed (default:
    SolidWorks' own). Returns text_area_mm2, since letters have no hand calculation.
    """
    return await _call(_session.add_text_on_face, text, face, x_mm, y_mm, z_mm, height_mm, depth_mm, emboss, font, name)


@mcp.tool()
async def cut_profile(
    points_mm: list,
    depth_mm: float | None = None,
    name: str = "Cut",
    corner_radii_mm: float | list | None = None,
    rotate_deg: float = 0.0,
    about_mm: list | None = None,
) -> dict:
    """Cut a polygonal pocket/slot from the +Z face: points_mm = [[x,y], ...] in mm.

    Auto-closed polygon, cut blind by depth_mm or all the way through when depth_mm
    is omitted. For pockets, slots, cutouts. corner_radii_mm rounds the corners
    and rotate_deg turns the profile about about_mm, as for add_extruded_profile
    (notches at +/-60 degrees around a pivot). Returns mass properties.
    """
    return await _call(_session.cut_profile, points_mm, depth_mm, name, corner_radii_mm, rotate_deg, about_mm)


@mcp.tool()
async def cut_profile_on_face(
    points_mm: list,
    face: str,
    depth_mm: float | None = None,
    name: str = "Cut",
    corner_radii_mm: float | list | None = None,
) -> dict:
    """Cut a polygon pocket/slot on ANY planar face: points_mm = [[x,y,z], ...] in mm.

    The 3D points must lie on one face facing `face` ("+x"/"-x"/...), which is
    found through them; cut blind by depth_mm or through when omitted. For side
    pockets/cutouts. corner_radii_mm rounds the corners as for
    add_extruded_profile. Returns mass properties.
    """
    return await _call(_session.cut_profile_on_face, points_mm, face, depth_mm, name, corner_radii_mm)


@mcp.tool()
async def cut_offset_pocket(
    face: str, x_mm: float, y_mm: float, z_mm: float, rim_mm: float, depth_mm: float | None = None, name: str = "Pocket"
) -> dict:
    """Pocket a planar face, leaving a rim rim_mm wide along its outline.

    The recessed web of an I-beam that follows a curved link, a tray, or a frame
    (depth_mm omitted: through all). The face is the one facing `face`
    ('+z', ...) through the point (x, y, z). The rim follows the outline, arcs
    and splines included; holes in the face stay holes. rim and depth come back
    as dimensions, and the pocket follows the outline when it changes. Returns
    mass properties.
    """
    return await _call(_session.cut_offset_pocket, face, x_mm, y_mm, z_mm, rim_mm, depth_mm, name)


@mcp.tool()
async def cut_slot(
    length_mm: float,
    width_mm: float,
    x_mm: float,
    y_mm: float,
    angle_deg: float = 0.0,
    depth_mm: float | None = None,
    name: str = "Slot",
) -> dict:
    """Cut a straight slotted hole (obround) on the +Z face.

    Centred at (x_mm, y_mm); length_mm is centre-to-centre of the rounded ends,
    width_mm the slot width, angle_deg its orientation in the +Z plane (0 = +X).
    Cut blind by depth_mm or through when omitted. Returns mass properties.
    """
    return await _call(_session.cut_slot, length_mm, width_mm, x_mm, y_mm, angle_deg, depth_mm, name)


@mcp.tool()
async def add_extruded_slot(start_mm: list, end_mm: list, width_mm: float, depth_mm: float, name: str = "Slot") -> dict:
    """Extrude a stadium (rounded tab, lug or link) from point start_mm to end_mm ([x, y] mm).

    The half-round ends are centred on the two points themselves; width_mm is
    the tab's width, depth_mm the extrusion along +Z. Volume = (width * length
    + pi * (width/2)^2) * depth. Returns mass properties.
    """
    return await _call(_session.add_extruded_slot, start_mm, end_mm, width_mm, depth_mm, name)


@mcp.tool()
async def add_fillet(
    radius_mm: float,
    edges: str = "all",
    name: str = "Fillet",
    radii_at_mm: list | None = None,
    skip_shorter_mm: float | None = None,
    tangent_propagation: bool = False,
) -> dict:
    """Round edges of the current part with one constant radius (mm).

    edges: "all" (default), "x"/"y"/"z" for edges parallel to that world axis,
    a face outline like "+z:outline" (the outer edges of the top face, not those
    of holes in it), every edge of one feature like "feature:Boss" (its top and
    where it meets the part: a moulded look), or explicit indices like "2,5" from
    list_edges. radii_at_mm = [[x, y, z, r], ...] makes the radius vary: r at
    the edge end at each point (list_edges gives the ends), radius_mm at the
    other ends, straight in between; 'vertex_radii' gives each end's dimension.
    skip_shorter_mm leaves out edges shorter than that. tangent_propagation=True
    carries the round on along edges that run on smoothly from the given ones,
    as SolidWorks does by default: an edge ending where it runs into another
    tangentially, such as round a fillet, only rounds so. A refusal names the
    edges the radius does not fit (each tried alone, and with propagation).
    Returns the number of edges filleted and the mass properties.
    """
    return await _call(_session.add_fillet, radius_mm, edges, name, radii_at_mm, skip_shorter_mm, tangent_propagation)


@mcp.tool()
async def add_full_round(face: str, x_mm: float, y_mm: float, z_mm: float, name: str = "FullRound") -> dict:
    """Round a rib's top off completely: a full round fillet, as on a moulded part.

    The face facing `face` ("+z", ...) through the point (x, y, z) is the top;
    the two opposite flat side faces along it that lie closest together are the
    sides, so the round runs across the rib, not along it. The radius is half
    their distance (width_mm in the result) and follows the rib. Hand
    calculation: a rib w wide and L long loses L w^2 (1/2 - pi/8).
    """
    return await _call(_session.add_full_round, face, x_mm, y_mm, z_mm, name)


@mcp.tool()
async def add_chamfer(
    distance_mm: float, edges: str = "all", name: str = "Chamfer", angle_deg: float = 45.0, from_face: str | None = None
) -> dict:
    """Chamfer edges of the current part: distance_mm back along a face, at angle_deg (default 45掳) to it.

    edges: "all" (default), "x"/"y"/"z", a face outline like "+z:outline", a
    feature's edges like "feature:Boss", or explicit indices like "2,5" from
    list_edges. Another angle than 45掳 needs from_face, which way the face that
    the distance runs along faces: "-z", angle_deg=60 makes an underside edge
    printable without support (round an arc the chamfer is a cone). Returns the
    number of edges chamfered and the mass properties.
    """
    return await _call(_session.add_chamfer, distance_mm, edges, name, angle_deg, from_face)


@mcp.tool()
async def add_linear_pattern(
    count: int, spacing_mm: float, direction: str = "+x", feature_name: str | None = None
) -> dict:
    """Repeat a feature `count` times, `spacing_mm` apart, along a direction.

    direction: "+x"/"-x"/"+y"/... feature_name: the feature to repeat (e.g.
    "Hole"); defaults to the most recently added feature. Returns mass properties.
    """
    return await _call(_session.add_linear_pattern, count, spacing_mm, direction, feature_name)


@mcp.tool()
async def add_circular_pattern(
    count: int, center_x_mm: float, center_y_mm: float, feature_name: str | None = None
) -> dict:
    """Repeat a feature `count` times evenly around 360掳 about an axis.

    The axis is the cylindrical face nearest (center_x_mm, center_y_mm) 鈥?e.g. a
    centre hole drilled there. feature_name defaults to the last feature. Bolt
    circle: drill a centre hole + one bolt hole, then pattern the bolt hole.
    """
    return await _call(_session.add_circular_pattern, count, center_x_mm, center_y_mm, feature_name)


@mcp.tool()
async def add_mirror(plane: str, offset_mm: float = 0.0, features: list | None = None, name: str = "Mirror") -> dict:
    """Mirror features, or the whole body, about the 'front'/'top'/'right' plane moved offset_mm.

    Mirrors about z / y / x = offset_mm; plane may also name another plane in
    the part ('Plane1'), moved offset_mm along its normal. features: list_features names; the
    copies follow their seeds. Without features the body is mirrored and
    merged: model half of a symmetric part, mirror it about the face where the
    halves meet. The plane position comes back as dimension 'plane_offset'.
    Fails, leaving the part as it was, when a copy would land outside the part.
    """
    return await _call(_session.add_mirror, plane, offset_mm, features, name)


@mcp.tool()
async def add_shell(thickness_mm: float, open_face: str | list = "+z") -> dict:
    """Hollow the current part to a wall of thickness_mm, opening one face or more.

    open_face: a direction "+z"/"-z"/"+x"/... removes that planar face (open
    shell), "#5" the face of that list_faces index, and a list ["+z", "#5"]
    opens several; "none" makes a closed hollow. Shell before cutting openings:
    a shell after them puts a wall along every cut edge. Returns the resulting
    mass properties.
    """
    return await _call(_session.add_shell, thickness_mm, open_face)
