"""Features built on a planar face: holes, bosses, pads and text.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import pythoncom
import win32com.client
import win32gui

from .. import binding
from ..constants import (
    SW_END_COND_BLIND,
    SW_END_COND_THROUGH_ALL,
    SW_START_SKETCH_PLANE,
    SW_TEXT_JUSTIFY_LEFT,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m


class FaceFeaturesMixin:
    """Features built on a planar face: holes, bosses, pads and text."""

    def _sketch_coords(self, sketch, x_m, y_m, z_m):
        """A 3D model point (m) in the sketch's own coordinates (u, v, w), in m.

        Via ISketch.ModelToSketchTransform; w is the distance off the sketch
        plane. The point must be a proper SAFEARRAY VARIANT -- a plain Python
        list is mis-marshalled by CreatePoint.
        """
        xform = binding.wrap(sketch.ModelToSketchTransform, self._mod.IMathTransform)
        mathutil = binding.wrap(self._sw.GetMathUtility(), self._mod.IMathUtility)
        coords = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x_m, y_m, z_m])
        p = binding.wrap(mathutil.CreatePoint(coords), self._mod.IMathPoint)
        return binding.wrap(p.MultiplyTransform(xform), self._mod.IMathPoint).ArrayData

    @staticmethod
    def _plane_point_size(points_mm) -> int:
        """2 for points [u, v] in a plane's own frame, 3 for [x, y, z] on it.
        Checked before any sketch opens: [u, v] given where [x, y, z] was
        read took SolidWorks down."""
        sizes = {
            len(p) if isinstance(p, (list, tuple)) and all(isinstance(c, (int, float)) for c in p) else 0
            for p in points_mm
        }
        if len(sizes) != 1 or sizes.pop() not in (2, 3):
            raise SolidWorksError(
                f"Give the points all as [u, v] on the plane or all as [x, y, z] on it, in mm (got {points_mm})."
            )
        return len(points_mm[0])

    def _plane_points_uv(self, sketch, points_mm, in_plane: bool, label: str) -> list:
        """The points as the open sketch's (u, v) in metres: [u, v] are that
        already (the frame add_plane and add_sketch give); [x, y, z] must lie on the plane."""
        if in_plane:
            return [(mm_to_m(u), mm_to_m(v)) for u, v in points_mm]
        return [self._model_to_sketch_uv(sketch, *(mm_to_m(c) for c in p), label) for p in points_mm]

    def _model_to_sketch_uv(self, sketch, x_m, y_m, z_m, face):
        """Map a 3D model point (m) to the active sketch's local 2D (u, v) (m).

        The point must LIE on the sketch's face: local[2] is its perpendicular
        distance to the face plane, which we reject past _ON_FACE_TOLERANCE_MM so
        an off-face point fails fast instead of being silently projected onto the
        face (which would place the feature at the wrong spot). `face` names the
        face in the error.
        """
        local = self._sketch_coords(sketch, x_m, y_m, z_m)
        off_mm = m_to_mm(local[2])
        if abs(off_mm) > self._ON_FACE_TOLERANCE_MM:
            raise SolidWorksError(
                f"Point ({m_to_mm(x_m):g}, {m_to_mm(y_m):g}, {m_to_mm(z_m):g}) mm is not "
                f"on the {face} face: it is {off_mm:.3f} mm off the face. Give a "
                f"point on the face (the perpendicular distance must be ~0)."
            )
        return local[0], local[1]

    def _open_sketch_on_face(self, face: str, point_mm):
        """Select the face -- the one through point_mm unless the selector names a
        side -- and open a sketch on it. Returns (sketch manager, open sketch)."""
        sk, sketch, _ = self._open_sketch_on_face_of(face, point_mm)
        return sk, sketch

    def _open_sketch_on_face_of(self, face: str, point_mm):
        """As _open_sketch_on_face, and the face itself: (sketch manager, sketch, face)."""
        body = self._solid_body()
        normal, side = self._parse_face_selector(face, default_side=None)
        picked = self._select_face_through(body, normal, side, point_mm, face)
        sk = binding.wrap(self._model.SketchManager, self._mod.ISketchManager)
        return sk, self._open_face_sketch(sk, face), picked

    def _sketch_circle_on_face(
        self, face: str, diameter_mm: float, x_mm: float, y_mm: float, z_mm: float, from_edges: bool = False
    ) -> dict:
        """A fully defined circle on the face through (x, y, z); the sketch is
        closed again. from_edges dimensions its centre from the face's nearest
        straight edges instead of the origin, so it follows them."""
        before = {f.Name for f in self._history()}
        sk, sketch, picked = self._open_sketch_on_face_of(face, (x_mm, y_mm, z_mm))
        try:
            try:
                u, v = self._model_to_sketch_uv(sketch, mm_to_m(x_mm), mm_to_m(y_mm), mm_to_m(z_mm), face)
                circle = self._draw_circle(sk, u, v, mm_to_m(diameter_mm / 2.0))
                if not from_edges:
                    # x/y are the face sketch's own horizontal/vertical directions
                    return self._define_sketch(sk, circles=[circle], names={("x", 0): "x", ("y", 0): "y"})
                return self._define_from_edges(sk, sketch, circle, picked, face)
            finally:
                self._model.ClearSelection2(True)
                sk.InsertSketch(True)  # close the sketch, also when the point is rejected
        except SolidWorksError:
            if from_edges:
                self._remove_features_since(before)  # a refused from_edges leaves no sketch behind
            raise

    def _define_from_edges(self, sk, sketch, circle, face_dispatch, label: str) -> dict:
        """Define a circle by its diameter and its centre's distances to the
        nearest straight edge of the face along each sketch axis."""
        _, definer = self._open_sketch_definer(sk)
        arc = binding.wrap(circle, self._mod.ISketchArc)
        centre = binding.wrap(arc.GetCenterPoint2(), self._mod.ISketchPoint)
        nearest = {}  # axis -> (distance, edge, its end points in model mm)
        for dispatch in binding.wrap(face_dispatch, self._mod.IFace2).GetEdges() or ():
            edge = binding.wrap(dispatch, self._mod.IEdge)
            curve = binding.wrap(edge.GetCurve(), self._mod.ICurve)
            if curve is None or not curve.IsLine():
                continue
            ends = [binding.wrap(v, self._mod.IVertex).GetPoint() for v in (edge.GetStartVertex(), edge.GetEndVertex())]
            (u1, v1, _), (u2, v2, _) = (self._sketch_coords(sketch, *p) for p in ends)
            # an edge along the sketch's v axis fixes x (u), one along u fixes y (v)
            for axis, across, along, place in (
                ("x", abs(u2 - u1), abs(v2 - v1), u1),
                ("y", abs(v2 - v1), abs(u2 - u1), v1),
            ):
                if across < 1e-9 < along:
                    distance = abs(place - (centre.X if axis == "x" else centre.Y))
                    if distance < nearest.get(axis, (float("inf"),))[0]:
                        nearest[axis] = (distance, dispatch, [[round(m_to_mm(c), 4) for c in p] for p in ends])
        missing = [axis for axis in ("x", "y") if axis not in nearest]
        if missing:
            raise SolidWorksError(
                f"from_edges needs a straight edge on the {label} face along each sketch axis; "
                f"there is none to measure {' and '.join(missing)} from. Leave from_edges out "
                "to dimension from the origin."
            )
        dims = {"diameter": definer._diameter(arc, "diameter")}
        for axis, add in (("x", self._model.AddHorizontalDimension2), ("y", self._model.AddVerticalDimension2)):
            entity = binding.wrap(nearest[axis][1], self._mod.IEntity)
            dims[axis] = definer.dimension_to(add, centre, entity, axis)
        return {
            "dimensions": dims,
            "fully_defined": definer.fully_defined(),
            "measured_from": {axis: {"edge_mm": nearest[axis][2]} for axis in ("x", "y")},
        }

    def _sketch_polygon_on_face(self, face: str, points_mm, corner_radii_mm=None) -> dict:
        """A fully defined polygon through 3D points on the face, its corners
        rounded by corner_radii_mm; the sketch is closed again."""
        if not points_mm:
            raise SolidWorksError("No profile points given.")
        corners = self._profile_corners(points_mm, corner_radii_mm)
        sk, sketch = self._open_sketch_on_face(face, points_mm[0])
        try:
            uv_m = [
                self._model_to_sketch_uv(sketch, mm_to_m(p[0]), mm_to_m(p[1]), mm_to_m(p[2]), face) for p in points_mm
            ]
            # x/y dimensions run along the face sketch's own axes
            return self._draw_defined_polygon(sk, self._clean_polygon(uv_m), corners)
        finally:
            self._model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the sketch, also when a point is rejected

    def add_hole_on_face(
        self,
        diameter_mm: float,
        face: str,
        x_mm: float,
        y_mm: float,
        z_mm: float,
        depth_mm: float | None = None,
        name: str = "Hole",
        from_edges: bool = False,
    ) -> dict:
        """Drill a round hole on any planar face, centred at 3D point (x, y, z).

        face is a direction '+x'/'-x'/'+y'/'-y'/'+z'/'-z'; the planar face facing
        that way THROUGH the point is used, so a pocket floor or a step works too
        (':outer'/':inner' force the outermost/innermost face). The hole runs
        through all material along the face normal, or depth_mm deep: a blind
        hole for a heat-set insert or a screw pilot. (add_hole is the +Z 2D
        convenience version of this.) from_edges=True dimensions the centre
        from the face's nearest straight edges, not the origin, so the hole
        keeps its distance to them when the part changes (`measured_from`).
        """
        model = self._require_model()
        if diameter_mm <= 0:
            raise SolidWorksError(f"diameter must be > 0 (got {diameter_mm}).")
        if depth_mm is not None and depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        defined = self._sketch_circle_on_face(face, diameter_mm, x_mm, y_mm, z_mm, from_edges)

        t1, d1 = (SW_END_COND_THROUGH_ALL, 0.0) if depth_mm is None else (SW_END_COND_BLIND, mm_to_m(depth_mm))
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        cut = feat_mgr.FeatureCut4(
            True,
            False,
            False,
            t1,
            0,
            d1,
            0.0,
            False,
            False,
            False,
            False,
            0.0,
            0.0,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            False,
            False,
            SW_START_SKETCH_PLANE,
            0.0,
            False,
            False,
        )
        if cut is None:
            raise SolidWorksError(f"FeatureCut4 failed (None). Is ({x_mm}, {y_mm}, {z_mm}) on the {face} face?")
        return self._with_depth(self._finish_feature(cut, name, **defined), depth_mm)

    def add_boss_on_face(
        self,
        diameter_mm: float,
        face: str,
        x_mm: float,
        y_mm: float,
        z_mm: float,
        height_mm: float,
        name: str = "Boss",
        from_edges: bool = False,
    ) -> dict:
        """Grow a round boss (standoff, peg) height_mm out of any planar face.

        Centred at 3D point (x, y, z) on the face; the face is found as for
        add_hole_on_face, and from_edges works as there. Add a blind hole in
        its top for a heat-set insert. Volume added = pi * (d/2)^2 * height.
        """
        self._require_model()
        if diameter_mm <= 0 or height_mm <= 0:
            raise SolidWorksError(f"diameter and height must be > 0 (got {diameter_mm}, {height_mm}).")
        defined = self._sketch_circle_on_face(face, diameter_mm, x_mm, y_mm, z_mm, from_edges)
        return self._extrude_sketch(height_mm, name, defined, "Is the circle on the face?", role="height")

    def add_extruded_profile_on_face(
        self, points_mm: list, face: str, depth_mm: float, name: str = "Boss", corner_radii_mm=None
    ) -> dict:
        """Grow a polygon boss depth_mm out of any planar face.

        points_mm are 3D [x, y, z] vertices on the face (auto-closed); the face is
        found as for add_hole_on_face. For pads, ledges and mounting blocks on an
        existing part. corner_radii_mm rounds the corners as for
        add_extruded_profile. Volume added = polygon area * depth.
        """
        self._require_model()
        if depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        defined = self._sketch_polygon_on_face(face, points_mm, corner_radii_mm)
        return self._extrude_sketch(depth_mm, name, defined, "Is the profile closed and on the face?")

    @staticmethod
    def _require_installed_font(font: str) -> None:
        """Windows draws an unknown font in another one, silently, and SolidWorks
        still reports the name it was given: so check the installed families."""
        families = set()

        def collect(logfont, *_):
            families.add(logfont.lfFaceName.lower())
            return 1

        screen = win32gui.GetDC(0)
        try:
            win32gui.EnumFontFamilies(screen, None, collect, None)
        finally:
            win32gui.ReleaseDC(0, screen)
        if font.lower() not in families:
            raise SolidWorksError(f"Font '{font}' is not installed; leave font out for SolidWorks' own.")

    def add_text_on_face(
        self,
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
        """Engrave text into any planar face, or emboss it (emboss=True).

        (x, y, z) is the lower-left corner of the text, on the face (found as
        for add_hole_on_face); the text runs along the face sketch's horizontal
        axis: upright along +x on the +z and -y faces, turned on the others
        (see Docs/PROGRESS.md). height_mm is the character height, depth_mm how
        deep the letters go or how high they stand. The position is two
        dimensions from the origin ('x', 'y') and the depth a third; font is an
        installed font (default SolidWorks' own). Letters have no hand
        calculation, so the result gives text_area_mm2 = volume change / depth.
        """
        if not str(text).strip():
            raise SolidWorksError("No text given.")
        if height_mm <= 0 or depth_mm <= 0:
            raise SolidWorksError(f"height and depth must be > 0 (got {height_mm}, {depth_mm}).")
        model = self._require_model()
        if font is not None:
            self._require_installed_font(font)
        before_volume = self.get_mass_properties()["mass_properties"]["volume_mm3"]
        sk, sketch = self._open_sketch_on_face(face, (x_mm, y_mm, z_mm))
        try:
            u, v = self._model_to_sketch_uv(sketch, mm_to_m(x_mm), mm_to_m(y_mm), mm_to_m(z_mm), face)
            sketch_text = binding.wrap(
                model.InsertSketchText(u, v, 0.0, str(text), SW_TEXT_JUSTIFY_LEFT, 0, 0, 100, 100),
                self._mod.ISketchText,
            )
            if sketch_text is None:
                raise SolidWorksError("InsertSketchText failed (None).")
            text_format = binding.wrap(sketch_text.GetTextFormat(), self._mod.ITextFormat)
            text_format.CharHeight = mm_to_m(height_mm)
            if font is not None:
                text_format.TypeFaceName = font
            if not sketch_text.SetTextFormat(False, text_format):
                raise SolidWorksError("Could not set the text's height and font.")
            points = sketch.GetSketchPoints2() or ()
            if len(points) != 1:
                raise SolidWorksError(f"Expected one insertion point in the text sketch, found {len(points)}.")
            _, definer = self._open_sketch_definer(sk)
            u0, v0, _ = self._sketch_coords(sketch, 0.0, 0.0, 0.0)  # the origin, projected
            dims = definer.place_point(
                binding.wrap(points[0], self._mod.ISketchPoint),
                (m_to_mm(u - u0), m_to_mm(v - v0)),
                {("x", 0): "x", ("y", 0): "y"},
            )
            defined = {"dimensions": dims, "fully_defined": definer.fully_defined()}
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the sketch, also when the text was refused

        if emboss:
            result = self._extrude_sketch(depth_mm, name, defined, f"Is ({x_mm}, {y_mm}, {z_mm}) on the {face} face?")
        else:
            feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
            cut = feat_mgr.FeatureCut4(
                True,
                False,
                False,
                SW_END_COND_BLIND,
                0,
                mm_to_m(depth_mm),
                0.0,
                False,
                False,
                False,
                False,
                0.0,
                0.0,
                False,
                False,
                False,
                False,
                False,
                True,
                True,
                False,
                False,
                False,
                SW_START_SKETCH_PLANE,
                0.0,
                False,
                False,
            )
            if cut is None:
                raise SolidWorksError(f"FeatureCut4 failed (None). Is ({x_mm}, {y_mm}, {z_mm}) on the {face} face?")
            result = self._with_depth(self._finish_feature(cut, name, **defined), depth_mm)
        change = abs(result["mass_properties"]["volume_mm3"] - before_volume)
        if change < 1e-6:
            raise SolidWorksError("The text changed nothing; is its point inside the face?")  # run_guarded cleans up
        result["text_area_mm2"] = round(change / depth_mm, 4)
        return result
