"""Solid builders: extrusion, revolve, sweep, loft, planes and ribs.

Thin MCP wrappers: validate arguments, delegate to the session and
normalise failures through :func:`solidworks_mcp.app._call`.
"""

from ..app import _call, _session, mcp


@mcp.tool()
async def add_box(width_mm: float, height_mm: float, depth_mm: float, name: str = "BlockExtrude") -> dict:
    """Add a rectangular block: sketch width x height on the first plane, extrude by depth.

    Dimensions are in millimetres. Returns the created feature name, the
    addressable depth dimension ('D1@<name>'), `dimensions` (width, height,
    depth; for set_dimension) and the resulting mass properties.
    """
    return await _call(_session.add_box, width_mm, height_mm, depth_mm, name)


@mcp.tool()
async def add_extruded_profile(
    points_mm: list,
    depth_mm: float,
    name: str = "Extrude",
    corner_radii_mm: float | list | None = None,
    rotate_deg: float = 0.0,
    about_mm: list | None = None,
    draft_deg: float = 0.0,
    merge: bool = True,
) -> dict:
    """Extrude a closed polygon into a solid: points_mm = [[x,y], ...] in mm.

    The polygon (first-plane coordinates, same as add_box) is auto-closed and
    extruded by depth_mm. Unlocks arbitrary prismatic shapes (brackets, profiles,
    polygons). corner_radii_mm rounds the corners with real sketch fillets: one
    radius for all, or one per vertex (0 = sharp); equal radii share one
    dimension ('radius', else 'r<i>'). rotate_deg turns the profile
    counterclockwise about about_mm ([x, y], the origin by default) first: draw
    a crank or a lug straight, then set it at its angle. draft_deg tapers the
    walls inwards as they rise (negative: outwards), a dimension 'draft' (a
    moulded boss, a printable taper). merge=False keeps the result a separate
    body: list_bodies, combine_bodies. Returns mass properties (volume = polygon
    area * depth; a right-angled corner of radius r loses r^2 (1 - pi/4), a
    concave one gains it).
    """
    return await _call(
        _session.add_extruded_profile,
        points_mm,
        depth_mm,
        name,
        corner_radii_mm,
        rotate_deg,
        about_mm,
        draft_deg,
        merge,
    )


@mcp.tool()
async def add_extruded_spline(points_mm: list, depth_mm: float, name: str = "Spline") -> dict:
    """Extrude a smooth CLOSED spline through points: points_mm = [[x,y], ...] in mm.

    Like add_extruded_profile but the outline is a smooth curve through the points
    (free-form/organic shapes: cams, rounded outlines, aesthetic bosses), auto-closed
    and extruded by depth_mm. A spline's area is not analytic, so the returned volume
    is the measured value. Returns mass properties. Use new_part first.
    """
    return await _call(_session.add_extruded_spline, points_mm, depth_mm, name)


@mcp.tool()
async def add_disc(
    diameter_mm: float, thickness_mm: float, name: str = "Disc", x_mm: float = 0.0, y_mm: float = 0.0
) -> dict:
    """Create a disc/puck/flange: a circle extruded along +Z, centred at (x_mm, y_mm).

    Flat faces are +Z/-Z, so add_hole and add_circular_pattern compose with it
    (round-flange bolt circles). The centre defaults to the origin; off it, its
    x and y are dimensions. Returns mass properties. Use new_part first.
    """
    return await _call(_session.add_disc, diameter_mm, thickness_mm, name, x_mm, y_mm)


@mcp.tool()
async def add_cylinder(diameter_mm: float, height_mm: float, name: str = "Revolve") -> dict:
    """Create a cylinder by revolving a profile 360掳 about an axis.

    The first revolve-based primitive. Returns the resulting mass properties
    (volume = 蟺 路 r虏 路 h). Use new_part first.
    """
    return await _call(_session.add_cylinder, diameter_mm, height_mm, name)


@mcp.tool()
async def add_cone(bottom_diameter_mm: float, top_diameter_mm: float, height_mm: float, name: str = "Revolve") -> dict:
    """Create a cone/frustum by revolving a trapezoidal profile 360掳.

    top_diameter_mm = 0 gives a full cone. Returns mass properties
    (volume = 蟺路h/3 路 (rb虏 + rb路rt + rt虏)). Use new_part first.
    """
    return await _call(_session.add_cone, bottom_diameter_mm, top_diameter_mm, height_mm, name)


@mcp.tool()
async def add_revolved_profile(
    profile_mm: list,
    angle_deg: float = 360.0,
    name: str = "Revolve",
    corner_radii_mm: float | list | None = None,
    axis_mm: list | None = None,
) -> dict:
    """Revolve a closed profile on the Front plane about an axis in it.

    Without axis_mm: profile_mm = [[r, z], 鈥 in mm, r = distance from the Y axis,
    z = position along it. With axis_mm = [[x1, y1], [x2, y2]]: profile_mm gives
    [x, y] points and the axis is the line through those two points, anywhere and
    at any angle (a hub turned about its own centre). Auto-closed and spun
    angle_deg (default 360掳). Points on the axis give a solid (shafts, vases); a
    profile away from it gives a ring. The profile may not cross the axis.
    corner_radii_mm rounds corners as for add_extruded_profile (not those on the
    axis). Returns mass properties. Use new_part first.
    """
    return await _call(_session.add_revolved_profile, profile_mm, angle_deg, name, corner_radii_mm, axis_mm)


@mcp.tool()
async def add_swept_pipe(
    path_mm: list, diameter_mm: float, bend_radius_mm: float = 0.0, name: str = "Pipe", smooth: bool = False
) -> dict:
    """Sweep a circular profile (pipe/tube/rod) along a 2D path on the Front plane.

    path_mm = [[x, y], 鈥 in mm is the centreline. Interior corners are rounded
    with bend_radius_mm (required when the path turns; a 2-point straight path
    needs none); smooth=True runs a spline through the points instead, a
    flowing curve. diameter_mm = outer 脴; the round profile is auto-generated
    perpendicular to the path. Returns mass properties (pi r^2 x
    path_length_mm). Use new_part first.
    """
    return await _call(_session.add_swept_pipe, path_mm, diameter_mm, bend_radius_mm, name, smooth)


@mcp.tool()
async def add_swept_profile(
    profile_mm: list,
    path_mm: list,
    bend_radius_mm: float = 0.0,
    name: str = "Sweep",
    corner_radii_mm: float | list | None = None,
) -> dict:
    """Sweep an arbitrary closed PROFILE (cross-section) along a 2D PATH.

    profile_mm = [[u,v],鈥 in mm: the closed cross-section on the Right plane (u 鈫?    world -Z, v 鈫?world +Y), centred near the origin. path_mm = [[x,y],鈥 in mm on
    the Front plane 鈥?MUST start at the origin heading +X (the profile is
    perpendicular to the path there). Path corners are rounded with bend_radius_mm;
    corner_radii_mm rounds the profile's corners as for add_extruded_profile.
    Volume = profile_area 路 path_length. For non-round extrusions along a path
    (rails, gaskets, trim, channels). Returns mass properties. Use new_part first.
    """
    return await _call(_session.add_swept_profile, profile_mm, path_mm, bend_radius_mm, name, corner_radii_mm)


@mcp.tool()
async def add_lofted_solid(profiles_mm: list, heights_mm: list, name: str = "Loft") -> dict:
    """Loft (blend) 2+ closed profiles on parallel planes stacked along +Z.

    profiles_mm: per profile a polygon [[x,y],鈥 (mm) in Front-plane coords, or a
    round section {"center_mm": [x, y], "diameter_mm": d} (thick at the knee,
    thin at the foot, centres free to wander). heights_mm = the +Z offset (mm)
    of each profile, same length, strictly increasing, starting at 0. A
    2-profile loft is a ruled transition; 3+ blend smoothly. Each profile
    starts at its first vertex (a round one on +x): give polygons in a
    consistent vertex order to avoid twist. Returns mass properties. Use
    new_part first.
    """
    return await _call(_session.add_lofted_solid, profiles_mm, heights_mm, name)


@mcp.tool()
async def loft_sketches(sketches: list, name: str = "Loft") -> dict:
    """Loft through 2+ closed sketches of the current part, by name, in order.

    The sketches may lie on any planes (add_plane, then add_sketch on it, or a
    person's sketches), so the loft runs in any direction, unlike
    add_lofted_solid's stack along +Z. Start each sketch at the matching
    corner (its first segment's start) to keep the loft from twisting. Returns
    mass properties.
    """
    return await _call(_session.loft_sketches, sketches, name)


@mcp.tool()
async def add_plane(
    base: str = "front",
    offset_mm: float = 0.0,
    angle_deg: float = 0.0,
    about: str | None = None,
    name: str | None = None,
) -> dict:
    """Make a reference plane to sketch on: an offset or a turned plane, its position a dimension.

    base moved offset_mm along its normal (base: front/top/right or a plane by
    name), or a default plane turned angle_deg about a model axis it holds,
    about='x'/'y'/'z' (front holds x and y, top x and z, right y and z), by the
    right-hand rule. For both, turn first, then offset that plane. Returns its
    name for plane= arguments, and origin_mm, normal, x_axis and y_axis: a point
    (u, v) on it is origin + u x_axis + v y_axis.
    """
    return await _call(_session.add_plane, base, offset_mm, angle_deg, about, name)


@mcp.tool()
async def add_extruded_profile_on_plane(
    points_mm: list,
    plane: str,
    depth_mm: float,
    reverse: bool = False,
    name: str = "Extrude",
    corner_radii_mm: float | list | None = None,
    draft_deg: float = 0.0,
    merge: bool = True,
) -> dict:
    """Extrude a polygon drawn on a reference plane, such as one add_plane made at an angle.

    points_mm = 3D [x, y, z] points ON the plane (origin + u x_axis + v y_axis
    from add_plane), or all [u, v] in that frame. depth_mm along the plane's normal, or the other way with
    reverse=True; merged with the part. corner_radii_mm, draft_deg and merge
    work as for add_extruded_profile. Returns mass properties.
    """
    return await _call(
        _session.add_extruded_profile_on_plane,
        points_mm,
        plane,
        depth_mm,
        reverse,
        name,
        corner_radii_mm,
        draft_deg,
        merge,
    )


@mcp.tool()
async def cut_profile_through_plane(
    points_mm: list,
    plane: str,
    depth_mm: float | None = None,
    name: str = "Cut",
    corner_radii_mm: float | list | None = None,
    keep_inside: bool = False,
) -> dict:
    """Cut a polygon sketched on a reference plane, symmetric about that plane.

    plane: 'front' (z = 0), 'top' (y = 0), 'right' (x = 0) or the name of another
    plane in the part ('Plane1'); points_mm = 3D [x, y, z] points ON that plane
    (e.g. x = 0 for 'right'), or all [u, v] in the plane's own frame (as
    add_plane and add_sketch give it). Cuts through all in
    both directions (depth_mm omitted) or depth_mm in total, centred on the
    plane. For shapes seen from the side: wedges, windows, symmetric recesses.
    corner_radii_mm rounds the corners as for add_extruded_profile.
    keep_inside=True cuts away everything OUTSIDE the profile (through all):
    extrude the front view, cut the side view with keep_inside, and the part is
    the 3D shape both views agree on. Returns mass properties.
    """
    return await _call(
        _session.cut_profile_through_plane, points_mm, plane, depth_mm, name, corner_radii_mm, keep_inside
    )


@mcp.tool()
async def add_rib(
    start_mm: list, end_mm: list, toward_mm: list, thickness_mm: float, z_mm: float, name: str = "Rib"
) -> dict:
    """Add a straight stiffening rib / gusset in a plane parallel to the Front plane.

    start_mm/end_mm = [x, y] ends of the rib's free edge (add_extruded_profile
    coordinates); the plane sits at height z_mm. The rib grows toward toward_mm
    (any [x, y] point on the side to fill, e.g. the inner corner of an L-bracket)
    until it meets the part, thickness_mm thick, centred on the plane. Returns mass
    properties: a triangular gusset with legs a and b adds a*b/2 * thickness.
    """
    return await _call(_session.add_rib, start_mm, end_mm, toward_mm, thickness_mm, z_mm, name)
