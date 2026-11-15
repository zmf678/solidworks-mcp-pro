"""Sketch reading and building on person-authored sketches.

Thin MCP wrappers: validate arguments, delegate to the session and
normalise failures through :func:`solidworks_mcp.app._call`.
"""

from ..app import _call, _session, mcp


@mcp.tool()
async def extrude_sketch(
    sketch: str, depth_mm: float | None = None, reverse: bool = False, name: str = "Extrude", up_to: str | None = None
) -> dict:
    """Extrude an existing sketch of the current part by name, e.g. one a person drew.

    depth_mm along the sketch's normal (reverse=True: the other way), merged
    with the body. Or up_to='next': up to the next face of the part, ending on
    its shape (a post into a curved wall) and following it when it changes;
    or up_to='@x,y,z': up to the face through that point, also where 'next'
    fails (a side of the profile on a face: the refusal names a point ahead).
    The sketch keeps its own dimensions and relations, so the person's design
    stays in charge; read_sketch shows it first. Returns mass properties.
    """
    return await _call(_session.extrude_sketch, sketch, depth_mm, reverse, name, up_to)


@mcp.tool()
async def add_sketch(plane: str, start_mm: list, segments: list, name: str | None = None) -> dict:
    """Draw a sketch of lines, arcs and splines on a plane, fully defined, to extrude or cut.

    plane: "front", "top", "right" or a plane by name (add_plane). Points are
    [u, v] in the plane's own axes, which the result gives (origin_mm + u
    x_axis + v y_axis): front is (x, y), top (x, -z), right (-z, y).
    The outline starts at start_mm; each segment runs on from where the last
    ended: {"line": [u, v]}; {"arc": [u, v], "through": [u, v]} (an arc through
    a middle point); {"arc": [u, v], "tangent": true} (an arc flowing on from
    the segment before); {"spline": [[u, v], ..., [u, v]]} (through the points,
    ending at the last). "tangent": true on a line checks that it flows on.
    End on start_mm to close the outline. Segments that meet smoothly get a
    tangent relation, the rest is dimensioned from the origin: x<i>/y<i> for
    the i-th point given (points_mm lists them; start_mm is 0), r<k> for the
    radius of segment k. Then extrude_sketch / cut_sketch the returned sketch.
    """
    return await _call(_session.add_sketch, plane, start_mm, segments, name)


@mcp.tool()
async def cut_sketch(sketch: str, depth_mm: float | None = None, reverse: bool = False, name: str = "Cut") -> dict:
    """Cut an existing sketch of the current part by name into the body.

    depth_mm deep, or through all when depth_mm is omitted, against the
    sketch's normal: into the part from a face. From a plane with the part in
    front of it (a box on the Front plane) give reverse=True. Returns mass
    properties.
    """
    return await _call(_session.cut_sketch, sketch, depth_mm, reverse, name)


@mcp.tool()
async def read_sketch(name: str) -> dict:
    """Read a sketch of the current part back, e.g. one a person drew (a list_features name).

    Gives its lines, arcs, circles and splines in MODEL coordinates (mm),
    construction geometry marked, its dimensions (for set_dimension) and
    whether it is fully defined: check a design against fixed points before
    building on it with extrude_sketch / cut_sketch.
    """
    return await _call(_session.read_sketch, name)
