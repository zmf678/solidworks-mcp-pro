"""Primary solid builders: box, extruded profile, spline, disc, cylinder, cone and revolve.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    SW_END_COND_BLIND,
)
from ..errors import SolidWorksError
from ..units import deg_to_rad, mm_to_m


class SolidsMixin:
    """Primary solid builders: box, extruded profile, spline, disc, cylinder, cone and revolve."""

    def add_box(self, width_mm: float, height_mm: float, depth_mm: float, name: str = "BlockExtrude") -> dict:
        """Sketch a rectangle on the first plane and extrude it; returns mass props.

        The extrude feature gets the stable name `name` so its depth dimension is
        addressable as 'D1@<name>' (used by set_dimension) regardless of language.
        The sketch is fully defined: `dimensions` names the width, height and
        depth, each changeable with set_dimension.
        """
        model = self._require_model()
        for value, label in ((width_mm, "width"), (height_mm, "height"), (depth_mm, "depth")):
            if value <= 0:
                raise SolidWorksError(f"{label} must be > 0 (got {value}).")

        plane = self._first_ref_plane()
        if plane is None:
            raise SolidWorksError("No reference plane found in the feature tree.")
        if not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the reference plane.")

        w, h = mm_to_m(width_mm), mm_to_m(height_mm)
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            lines = self._draw_polyline(sk, [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)])
            sketch = self._define_sketch(sk, lines, names={("x", 1): "width", ("y", 2): "height"})
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the sketch (it stays selected for the extrude)

        result = self._extrude_sketch(depth_mm, name, sketch, "Is the sketch valid?")
        result["depth_dimension"] = result["dimensions"]["depth"]
        return result

    def add_extruded_profile(
        self,
        points_mm: list,
        depth_mm: float,
        name: str = "Extrude",
        corner_radii_mm=None,
        rotate_deg: float = 0.0,
        about_mm: list | None = None,
        draft_deg: float = 0.0,
        merge: bool = True,
    ) -> dict:
        """Extrude a closed polygon profile into a solid on the first plane.

        points_mm is a list of [x, y] vertices (mm) in the first-plane coordinate
        system (same as add_box); the polygon is auto-closed and extruded by
        depth_mm along the plane normal. Unlocks arbitrary prismatic shapes
        (L-brackets, T-sections, polygons, ...). corner_radii_mm rounds the
        corners with real sketch fillets: one radius for all, or one per vertex
        (0 = sharp). rotate_deg turns the profile counterclockwise about about_mm
        ([x, y], the origin by default) before it is drawn, for parts at an angle
        such as a crank at 150 degrees. draft_deg tapers the walls inwards as
        they rise (negative: outwards), a dimension 'draft'; merge=False keeps the
        result a separate body (see list_bodies, combine_bodies). Returns mass
        properties (volume = polygon area * depth; a right-angled corner of
        radius r loses r^2 (1 - pi/4), a concave one gains it).
        """
        model = self._require_model()
        if depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        if not points_mm:
            raise SolidWorksError("No profile points given.")
        self._check_draft(draft_deg)
        points_mm = self._turned_points(points_mm, rotate_deg, about_mm)

        plane = self._first_ref_plane()
        if plane is None:
            raise SolidWorksError("No reference plane found in the feature tree.")
        if not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the reference plane.")

        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sketch = self._sketch_closed_polygon(sk, points_mm, corner_radii_mm)
        return self._extrude_sketch(
            depth_mm, name, sketch, "Is the profile closed and not self-intersecting?", draft_deg=draft_deg, merge=merge
        )

    def add_extruded_spline(self, points_mm: list, depth_mm: float, name: str = "Spline") -> dict:
        """Extrude a smooth CLOSED spline through the given points (organic shapes).

        points_mm = [[x, y], ...] in mm: interpolation points the spline passes
        through, on the first plane. The curve is closed (last -> first) and
        extruded depth_mm along the plane normal -- like add_extruded_profile but
        smooth/curved (cams, fillided outlines, free-form bosses). NOTE: a spline's
        enclosed area is not analytic, so the returned volume is the measured truth,
        not a hand-calc. Returns mass properties. Use new_part first.
        """
        model = self._require_model()
        if depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        pts = self._clean_polygon(points_mm)  # >= 3 distinct points

        plane = self._first_ref_plane()
        if plane is None:
            raise SolidWorksError("No reference plane found in the feature tree.")
        if not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the reference plane.")

        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            coords = []
            for x, y in pts + [pts[0]]:  # repeat the first point to close the spline
                coords += [mm_to_m(x), mm_to_m(y), 0.0]
            point_data = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, coords)
            spline = sk.CreateSpline2(point_data, False)  # SimulateNaturalEnds=False
            if not spline:
                raise SolidWorksError("Spline sketch failed: CreateSpline2 returned nothing.")
            sketch = self._fix_sketch(sk, [spline])  # its points are the design; nothing to dimension
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the sketch
        return self._extrude_sketch(depth_mm, name, sketch, "Is the spline closed and not self-intersecting?")

    def add_disc(
        self, diameter_mm: float, thickness_mm: float, name: str = "Disc", x_mm: float = 0.0, y_mm: float = 0.0
    ) -> dict:
        """Create a disc / puck / flange: a circle extruded along +Z, centred at (x, y).

        Unlike add_cylinder (revolve, axis Y), the disc's flat faces are +Z/-Z, so
        add_hole and add_circular_pattern compose with it directly -- this is how
        round-flange bolt circles are built. The centre defaults to the origin;
        off it, its x and y are dimensions. Returns mass properties (volume =
        pi * r^2 * thickness).
        """
        model = self._require_model()
        if diameter_mm <= 0 or thickness_mm <= 0:
            raise SolidWorksError("diameter and thickness must be > 0.")

        plane = self._first_ref_plane()
        if plane is None:
            raise SolidWorksError("No reference plane found in the feature tree.")
        if not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the reference plane.")

        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            circle = self._draw_circle(sk, mm_to_m(x_mm), mm_to_m(y_mm), mm_to_m(diameter_mm / 2.0))
            sketch = self._define_sketch(sk, circles=[circle], names={("x", 0): "x", ("y", 0): "y"})
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)
        return self._extrude_sketch(thickness_mm, name, sketch, role="thickness")

    def add_cylinder(self, diameter_mm: float, height_mm: float, name: str = "Revolve") -> dict:
        """Create a cylinder by revolving a rectangular profile 360 deg about an axis.

        Sketches a radius x height rectangle on the first plane with one edge on
        the revolve axis (a centerline at x=0) and revolves it fully. A single
        centerline is auto-detected as the axis. This proves the revolve path; the
        same plumbing extends to cones / general profiles next. Returns mass
        properties (volume should equal pi * r^2 * h).
        """
        model = self._require_model()
        for value, label in ((diameter_mm, "diameter"), (height_mm, "height")):
            if value <= 0:
                raise SolidWorksError(f"{label} must be > 0 (got {value}).")

        plane = self._first_ref_plane()
        if plane is None:
            raise SolidWorksError("No reference plane found in the feature tree.")
        if not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the reference plane.")

        radius = mm_to_m(diameter_mm / 2.0)
        height = mm_to_m(height_mm)
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            lines = self._draw_polyline(sk, [(0.0, 0.0), (radius, 0.0), (radius, height), (0.0, height)])
            axis = self._draw_centerline(sk, 0.0, 0.0, 0.0, height)  # axis at x=0
            sketch = self._define_sketch(sk, lines + [axis], names={("x", 1): "radius", ("y", 2): "height"})
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # exit sketch

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        revolve = feat_mgr.FeatureRevolve2(
            True,
            True,
            False,
            False,  # SingleDir, IsSolid, IsThin, IsCut
            False,
            False,  # ReverseDir, BothDirectionUpToSameEntity
            SW_END_COND_BLIND,
            0,  # Dir1Type, Dir2Type
            deg_to_rad(360.0),
            0.0,  # Dir1Angle (full revolve), Dir2Angle
            False,
            False,
            0.0,
            0.0,  # OffsetReverse1/2, OffsetDistance1/2
            0,
            0.0,
            0.0,  # ThinType, ThinThickness1/2
            True,
            True,
            True,  # Merge, UseFeatScope, UseAutoSelect
        )
        if revolve is None:
            raise SolidWorksError("FeatureRevolve2 failed (None). Is the profile valid?")
        return self._finish_feature(revolve, name, **sketch)

    def add_cone(
        self, bottom_diameter_mm: float, top_diameter_mm: float, height_mm: float, name: str = "Revolve"
    ) -> dict:
        """Create a cone/frustum by revolving a trapezoidal profile 360 deg.

        top_diameter_mm = 0 gives a full cone. Reuses the add_cylinder revolve
        plumbing (a closed profile + a centerline axis). Returns mass properties
        (volume = pi*h/3 * (rb^2 + rb*rt + rt^2)).
        """
        model = self._require_model()
        if bottom_diameter_mm <= 0 or height_mm <= 0:
            raise SolidWorksError("bottom_diameter and height must be > 0.")
        if top_diameter_mm < 0:
            raise SolidWorksError("top_diameter cannot be negative.")
        if top_diameter_mm >= bottom_diameter_mm:
            raise SolidWorksError("top_diameter must be smaller than bottom_diameter (otherwise use add_cylinder).")

        plane = self._first_ref_plane()
        if plane is None:
            raise SolidWorksError("No reference plane found in the feature tree.")
        if not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the reference plane.")

        rb = mm_to_m(bottom_diameter_mm / 2.0)
        rt = mm_to_m(top_diameter_mm / 2.0)
        h = mm_to_m(height_mm)
        # bottom edge, slant edge, top edge (omitted for a full cone), axis edge
        profile = [(0.0, 0.0), (rb, 0.0), (rt, h), (0.0, h)] if rt > 1e-9 else [(0.0, 0.0), (rb, 0.0), (0.0, h)]
        names = {("x", 1): "bottom_radius", ("y", 2): "height"}
        if rt > 1e-9:
            names[("x", 2)] = "top_radius"
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            lines = self._draw_polyline(sk, profile)
            axis = self._draw_centerline(sk, 0.0, 0.0, 0.0, h)  # revolve axis at x=0
            sketch = self._define_sketch(sk, lines + [axis], names=names)
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        revolve = feat_mgr.FeatureRevolve2(
            True,
            True,
            False,
            False,
            False,
            False,
            SW_END_COND_BLIND,
            0,
            deg_to_rad(360.0),
            0.0,
            False,
            False,
            0.0,
            0.0,
            0,
            0.0,
            0.0,
            True,
            True,
            True,
        )
        if revolve is None:
            raise SolidWorksError("FeatureRevolve2 failed (None). Is the profile closed?")
        return self._finish_feature(revolve, name, **sketch)

    def add_revolved_profile(
        self, profile_mm: list, angle_deg: float = 360.0, name: str = "Revolve", corner_radii_mm=None, axis_mm=None
    ) -> dict:
        """Revolve a closed profile on the Front plane about an axis in it.

        Without axis_mm: profile_mm = [[r, z], ...] in mm, r the distance from
        the revolve axis (the Y axis), z the position along it. With axis_mm =
        [[x1, y1], [x2, y2]]: profile_mm gives [x, y] points on the Front plane
        and the axis is the line through the two points, at any place and angle
        (a hub turned about its own centre); its ends are dimensions too. The
        polygon is auto-closed and spun `angle_deg` (default 360). Points on the
        axis give a solid like add_cone; a profile away from it gives a ring.
        The profile may not cross the axis. corner_radii_mm rounds corners as for
        add_extruded_profile; corners on the axis cannot be rounded. Returns mass
        properties.
        """
        pts = self._clean_polygon(profile_mm)
        if axis_mm is None:
            if any(r < -1e-9 for r, _ in pts):
                raise SolidWorksError(
                    "radius (first coordinate) cannot be negative -- the profile may not cross the axis."
                )
            z_vals = [z for _, z in pts]
            if max(z_vals) - min(z_vals) < 1e-9:
                raise SolidWorksError("The profile is flat along the axis (one z for every point): give it height.")
            start, end = (0.0, min(z_vals)), (0.0, max(z_vals))
        else:
            start, end = self._revolve_axis(axis_mm)
        offsets = [self._offset_from_line(start, end, p) for p in pts]
        if min(offsets) < -1e-9 and max(offsets) > 1e-9:
            raise SolidWorksError("The profile crosses the axis: put it on one side of the axis line.")
        if all(abs(d) < 1e-9 for d in offsets):
            raise SolidWorksError("The profile lies entirely on the axis.")
        on_axis_points = [abs(d) < 1e-9 for d in offsets]
        lone = [
            i
            for i, on in enumerate(on_axis_points)
            if on and not (on_axis_points[i - 1] or on_axis_points[(i + 1) % len(pts)])
        ]
        if lone:
            # the solid would pinch to a point there, which SolidWorks refuses (verified)
            raise SolidWorksError(
                f"Point(s) {lone} touch the axis on their own: a profile may not meet its axis "
                "in a single point. Move it off the axis, or lay a whole edge on it."
            )
        if not 0.0 < angle_deg <= 360.0:
            raise SolidWorksError(f"angle must be in (0, 360] (got {angle_deg}).")
        corners = self._profile_corners(pts, corner_radii_mm)
        on_axis = sorted(i for _, group in corners[1] for i in group if abs(offsets[i]) < 1e-9)
        if on_axis:
            raise SolidWorksError(
                f"Corner(s) {on_axis} lie on the axis and cannot be rounded; round the outer edges instead."
            )
        model = self._require_model()

        plane = self._first_ref_plane()
        if plane is None:
            raise SolidWorksError("No reference plane found in the feature tree.")
        if not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the reference plane.")

        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            lines = self._draw_polyline(sk, [(mm_to_m(x), mm_to_m(y)) for x, y in pts])
            axis = self._draw_centerline(sk, *(mm_to_m(c) for c in start), *(mm_to_m(c) for c in end))
            sketch = self._round_corners(sk, lines, corners[1], self._define_sketch(sk, lines + [axis]))
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        revolve = feat_mgr.FeatureRevolve2(
            True,
            True,
            False,
            False,
            False,
            False,
            SW_END_COND_BLIND,
            0,
            deg_to_rad(angle_deg),
            0.0,
            False,
            False,
            0.0,
            0.0,
            0,
            0.0,
            0.0,
            True,
            True,
            True,
        )
        if revolve is None:
            raise SolidWorksError("FeatureRevolve2 failed (None). Is the profile closed and valid?")
        return self._finish_feature(revolve, name, **sketch)

    @staticmethod
    def _revolve_axis(axis_mm) -> tuple:
        """[[x1, y1], [x2, y2]] -> two distinct (x, y) points (mm); pure, unit-tested."""
        try:
            (x1, y1), (x2, y2) = axis_mm
            start, end = (float(x1), float(y1)), (float(x2), float(y2))
        except (TypeError, ValueError):
            raise SolidWorksError(f"axis_mm needs two points [[x1, y1], [x2, y2]] (got {axis_mm}).") from None
        if math.dist(start, end) < 1e-6:
            raise SolidWorksError("The two axis points coincide: give two points on the axis.")
        return start, end

    @staticmethod
    def _offset_from_line(start, end, point) -> float:
        """Signed distance (mm) of `point` from the line start-end: which side, and how far."""
        dx, dy = end[0] - start[0], end[1] - start[1]
        return (dx * (point[1] - start[1]) - dy * (point[0] - start[0])) / math.hypot(dx, dy)
