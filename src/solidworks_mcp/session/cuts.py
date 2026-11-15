"""Profile cuts, pockets, through-plane cuts and slots.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

from .. import binding
from ..constants import (
    SW_END_COND_BLIND,
    SW_END_COND_MID_PLANE,
    SW_END_COND_THROUGH_ALL,
    SW_FULLY_CONSTRAINED,
    SW_SKETCH_ARC,
    SW_SKETCH_LINE,
    SW_SLOT_CREATION_LINE,
    SW_SLOT_LENGTH_CENTER,
    SW_START_SKETCH_PLANE,
)
from ..errors import SolidWorksError
from ..units import deg_to_rad, mm_to_m


class CutsMixin:
    """Profile cuts, pockets, through-plane cuts and slots."""

    def cut_profile(
        self,
        points_mm: list,
        depth_mm: float | None = None,
        name: str = "Cut",
        corner_radii_mm=None,
        rotate_deg: float = 0.0,
        about_mm: list | None = None,
    ) -> dict:
        """Cut a polygonal pocket/slot from the +Z face, blind or through.

        points_mm is a list of [x, y] vertices (mm) in add_box coordinates. The
        polygon is auto-closed and cut into the part: blind by depth_mm, or all
        the way through when depth_mm is None. corner_radii_mm rounds the
        corners as for add_extruded_profile; rotate_deg turns the profile about
        about_mm first, as there. Returns mass properties.
        """
        model = self._require_model()
        if not points_mm:
            raise SolidWorksError("No profile points given.")
        points_mm = self._turned_points(points_mm, rotate_deg, about_mm)
        if depth_mm is not None and depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")

        body = self._solid_body()
        self._select_planar_face(body, (0.0, 0.0, 1.0), "+Z")
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sketch = self._sketch_closed_polygon(sk, points_mm, corner_radii_mm)

        if depth_mm is None:
            t1, d1 = SW_END_COND_THROUGH_ALL, 0.0
        else:
            t1, d1 = SW_END_COND_BLIND, mm_to_m(depth_mm)

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
            raise SolidWorksError("FeatureCut4 failed (None). Is the profile on the +Z face?")
        return self._with_depth(self._finish_feature(cut, name, **sketch), depth_mm)

    def cut_profile_on_face(
        self, points_mm: list, face: str, depth_mm: float | None = None, name: str = "Cut", corner_radii_mm=None
    ) -> dict:
        """Cut a polygon pocket/slot on ANY planar face, blind or through.

        points_mm is a list of 3D [x, y, z] vertices (mm) that lie on one face
        facing `face` ('+x'/'-x'/...): the face through them is used, as for
        add_hole_on_face. Each is mapped into the face-sketch via the
        model->sketch transform. The polygon is auto-closed; cut blind by depth_mm
        or through when depth_mm is None. corner_radii_mm rounds the corners as
        for add_extruded_profile. Returns mass properties.
        """
        model = self._require_model()
        if depth_mm is not None and depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        defined = self._sketch_polygon_on_face(face, points_mm, corner_radii_mm)

        if depth_mm is None:
            t1, d1 = SW_END_COND_THROUGH_ALL, 0.0
        else:
            t1, d1 = SW_END_COND_BLIND, mm_to_m(depth_mm)

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
            raise SolidWorksError(f"FeatureCut4 failed (None). Are the points on the {face} face?")
        return self._with_depth(self._finish_feature(cut, name, **defined), depth_mm)

    def cut_offset_pocket(
        self,
        face: str,
        x_mm: float,
        y_mm: float,
        z_mm: float,
        rim_mm: float,
        depth_mm: float | None = None,
        name: str = "Pocket",
    ) -> dict:
        """Pocket a planar face, leaving a rim rim_mm wide along its outline.

        The recessed web of an I-beam that follows a curved link, a tray, or a
        frame (depth_mm None: through all). The face is the one facing `face`
        through (x, y, z), as for the *_on_face tools. The rim follows the
        outline, arcs and splines included; holes in the face stay holes. The
        pocket's edge is the outline offset inwards, tied to it, so rim and
        depth are dimensions and the pocket follows the outline when it changes.
        """
        if rim_mm <= 0:
            raise SolidWorksError(f"rim must be > 0 (got {rim_mm}).")
        if depth_mm is not None and depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        model = self._require_model()
        normal, side = self._parse_face_selector(face, default_side=None)
        target = self._select_face_through(self._solid_body(), normal, side, (x_mm, y_mm, z_mm), face)
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sketch = self._open_face_sketch(sk, face)
        try:
            fully_defined = self._offset_outline(sketch, target, rim_mm, face)
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)
        dimensions = {"rim": self._rename_first_dimension(self._history()[-1], "rim")}
        model.ClearSelection2(True)
        if not self._history()[-1].Select2(False, 0):
            raise SolidWorksError("Could not select the pocket's sketch.")
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
            raise SolidWorksError(f"FeatureCut4 failed (None) for the pocket in the {face} face.")
        return self._with_depth(
            self._finish_feature(cut, name, dimensions=dimensions, fully_defined=fully_defined), depth_mm
        )

    def _offset_outline(self, sketch, face, offset_mm: float, label: str) -> bool:
        """Draw the face's outer loop offset offset_mm inwards in the open sketch
        (Offset Entities: tied to the edges by one dimension); whether the
        sketch is then fully defined."""
        loops = [binding.wrap(loop, self._mod.ILoop2) for loop in binding.wrap(face, self._mod.IFace2).GetLoops() or ()]
        outer = next((loop for loop in loops if loop.IsOuter()), None)
        if outer is None:
            raise SolidWorksError(f"The {label} face has no outer loop.")
        self._model.ClearSelection2(True)
        for edge in outer.GetEdges() or ():
            if not binding.wrap(edge, self._mod.IEntity).Select4(True, None):
                raise SolidWorksError(f"Could not select the outline of the {label} face.")
        # a negative offset runs inwards from a face's outer loop (verified)
        if not self._model.SketchOffsetEntities2(-mm_to_m(offset_mm), False, True):
            raise SolidWorksError(
                f"SolidWorks could not offset the {label} face's outline by {offset_mm:g} mm: "
                "is the rim wider than half the face?"
            )
        return sketch.GetConstrainedStatus() == SW_FULLY_CONSTRAINED

    def _rename_first_dimension(self, feature, role: str) -> str:
        """Give the feature's first dimension the name `role`; returns the name
        set_dimension takes, e.g. 'rim@Sketch2'."""
        display = binding.wrap(feature.GetFirstDisplayDimension(), self._mod.IDisplayDimension)
        if display is None:
            raise SolidWorksError(f"'{feature.Name}' has no dimension to name '{role}'.")
        dim = binding.wrap(display.GetDimension2(0), self._mod.IDimension)
        dim.Name = role
        return dim.GetNameForSelection()

    def cut_profile_through_plane(
        self,
        points_mm: list,
        plane: str,
        depth_mm: float | None = None,
        name: str = "Cut",
        corner_radii_mm=None,
        keep_inside: bool = False,
    ) -> dict:
        """Cut a polygon sketched on a reference plane, symmetric about it.

        plane: 'front' (z = 0), 'top' (y = 0), 'right' (x = 0) or the name of
        another plane in the part (e.g. 'Plane1'). points_mm are 3D [x, y, z]
        vertices ON that plane (e.g. x = 0 for 'right'), or all [u, v] in the
        plane's own frame. The cut runs
        through all in both directions (depth_mm None), or depth_mm in total,
        centred on the plane. For shapes seen from the side: wedges, windows and
        recesses symmetric about the plane. corner_radii_mm rounds the corners
        as for add_extruded_profile. keep_inside=True cuts away everything
        OUTSIDE the profile instead (through all): the part becomes what it has
        in common with the profile seen from that side, so a front view
        extruded and a side view cut this way give a 3D shape. Returns mass
        properties.
        """
        if depth_mm is not None and depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        if keep_inside and depth_mm is not None:
            raise SolidWorksError("keep_inside cuts through all: leave depth_mm out.")
        if not points_mm:
            raise SolidWorksError("No profile points given.")
        in_plane = self._plane_point_size(points_mm) == 2
        model = self._require_model()
        corners = self._profile_corners(points_mm, corner_radii_mm)

        ref, label = self._named_plane(plane)
        model.ClearSelection2(True)
        if not ref.Select2(False, 0):
            raise SolidWorksError(f"Could not select the {label}.")
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sketch = self._open_face_sketch(sk, label)
        try:
            uv_m = self._plane_points_uv(sketch, points_mm, in_plane, label)
            defined = self._draw_defined_polygon(sk, self._clean_polygon(uv_m), corners)
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the sketch, also when a point is rejected

        if depth_mm is None:
            single, t1, t2, d1 = False, SW_END_COND_THROUGH_ALL, SW_END_COND_THROUGH_ALL, 0.0
        else:
            single, t1, t2, d1 = True, SW_END_COND_MID_PLANE, 0, mm_to_m(depth_mm)
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        cut = feat_mgr.FeatureCut4(
            single,
            bool(keep_inside),
            False,
            t1,
            t2,
            d1,
            0.0,  # Flip: cut away the outside
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
            raise SolidWorksError(f"FeatureCut4 failed (None). Does the profile on the {label} cross the part?")
        return self._with_depth(self._finish_feature(cut, name, **defined), depth_mm)

    def add_extruded_profile_on_plane(
        self,
        points_mm: list,
        plane: str,
        depth_mm: float,
        reverse: bool = False,
        name: str = "Extrude",
        corner_radii_mm=None,
        draft_deg: float = 0.0,
        merge: bool = True,
    ) -> dict:
        """Extrude a polygon sketched on a reference plane, merged with the body.

        plane: 'front', 'top', 'right' or a plane by name, such as one add_plane
        made at an angle. points_mm are 3D [x, y, z] vertices ON that plane
        (add_plane gives its origin and axes: origin + u x_axis + v y_axis), or
        all [u, v] in that frame.
        depth_mm along the plane's normal, or the other way with reverse=True.
        corner_radii_mm, draft_deg and merge work as for add_extruded_profile.
        Returns mass properties.
        """
        if depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        if not points_mm:
            raise SolidWorksError("No profile points given.")
        in_plane = self._plane_point_size(points_mm) == 2
        self._check_draft(draft_deg)
        corners = self._profile_corners(points_mm, corner_radii_mm)
        model = self._require_model()
        ref, label = self._named_plane(plane)
        model.ClearSelection2(True)
        if not ref.Select2(False, 0):
            raise SolidWorksError(f"Could not select the {label}.")
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sketch = self._open_face_sketch(sk, label)
        try:
            uv_m = self._plane_points_uv(sketch, points_mm, in_plane, label)
            defined = self._draw_defined_polygon(sk, self._clean_polygon(uv_m), corners)
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the sketch, also when a point is rejected
        return self._extrude_sketch(
            depth_mm,
            name,
            defined,
            f"Is the profile on the {label} closed?",
            reverse=reverse,
            draft_deg=draft_deg,
            merge=merge,
        )

    def _define_slot(self, sk) -> dict:
        """Define an open straight-slot sketch by its end-arc centres and width.

        Only the construction centreline and one end arc get constraints: the
        slot's own relations tie its straight edges and other arc to them.
        """
        sketch = binding.wrap(sk.ActiveSketch, self._mod.ISketch)
        segments = [binding.wrap(s, self._mod.ISketchSegment) for s in (sketch.GetSketchSegments() or ())]
        centreline = next((s for s in segments if s.GetType() == SW_SKETCH_LINE and s.ConstructionGeometry), None)
        arc = next((s for s in segments if s.GetType() == SW_SKETCH_ARC), None)
        if centreline is None or arc is None:
            raise SolidWorksError("The slot sketch has no centreline or end arc to dimension.")
        names = {
            ("x", 0): "end1_x",
            ("y", 0): "end1_y",
            ("x", 1): "end2_x",
            ("y", 1): "end2_y",
            ("diameter", 0): "width",
        }
        return self._define_sketch(sk, [centreline], [arc], names=names)

    def _sketch_slot(self, sk, c1, c2, width_mm: float) -> dict:
        """Draw a straight slot in the open sketch between end-arc centres c1 and
        c2 ([x, y] mm) and define it; returns the _define_slot result."""
        dx, dy = c2[0] - c1[0], c2[1] - c1[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            raise SolidWorksError("The slot's two ends coincide; give two different points.")
        px, py = -dy / length, dx / length  # perpendicular: CreateSketchSlot takes a point on a side
        edge = ((c1[0] + c2[0]) / 2 + width_mm / 2 * px, (c1[1] + c2[1]) / 2 + width_mm / 2 * py)
        seg = sk.CreateSketchSlot(
            SW_SLOT_CREATION_LINE,
            SW_SLOT_LENGTH_CENTER,
            mm_to_m(width_mm),
            mm_to_m(c1[0]),
            mm_to_m(c1[1]),
            0.0,
            mm_to_m(c2[0]),
            mm_to_m(c2[1]),
            0.0,
            mm_to_m(edge[0]),
            mm_to_m(edge[1]),
            0.0,
            1,
            False,
        )
        if not seg:
            raise SolidWorksError("Slot sketch failed: CreateSketchSlot returned nothing.")
        return self._define_slot(sk)

    def add_extruded_slot(
        self, start_mm: list, end_mm: list, width_mm: float, depth_mm: float, name: str = "Slot"
    ) -> dict:
        """Extrude a stadium on the first plane: half circles of diameter width_mm
        centred on start_mm and end_mm ([x, y] mm), joined by straight sides.

        A rounded tab, lug or link between two points, with the points themselves
        as the arc centres (end1_x ... end2_y and width are its dimensions).
        Volume = (width * length + pi * (width / 2)^2) * depth.
        """
        model = self._require_model()
        if width_mm <= 0 or depth_mm <= 0:
            raise SolidWorksError(f"width and depth must be > 0 (got {width_mm}, {depth_mm}).")
        plane = self._first_ref_plane()
        if plane is None or not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the Front plane.")
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            sketch = self._sketch_slot(
                sk, (float(start_mm[0]), float(start_mm[1])), (float(end_mm[0]), float(end_mm[1])), width_mm
            )
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)
        return self._extrude_sketch(depth_mm, name, sketch, "Is the slot valid?")

    def cut_slot(
        self,
        length_mm: float,
        width_mm: float,
        x_mm: float,
        y_mm: float,
        angle_deg: float = 0.0,
        depth_mm: float | None = None,
        name: str = "Slot",
    ) -> dict:
        """Cut a straight slotted hole (obround) on the +Z face, blind or through.

        Centred at (x_mm, y_mm); length_mm is centre-to-centre of the end arcs,
        width_mm the slot width, angle_deg the orientation in the +Z plane. Cut
        blind by depth_mm or through (None). Returns mass properties.
        """
        model = self._require_model()
        if length_mm <= 0 or width_mm <= 0:
            raise SolidWorksError("length and width must be > 0.")

        rad = deg_to_rad(angle_deg)
        ax, ay = math.cos(rad), math.sin(rad)  # slot axis direction
        half = length_mm / 2.0
        c1 = (x_mm - half * ax, y_mm - half * ay)
        c2 = (x_mm + half * ax, y_mm + half * ay)

        body = self._solid_body()
        self._select_planar_face(body, (0.0, 0.0, 1.0), "+Z")
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            sketch = self._sketch_slot(sk, c1, c2, width_mm)
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)

        if depth_mm is None:
            t1, d1 = SW_END_COND_THROUGH_ALL, 0.0
        else:
            if depth_mm <= 0:
                raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
            t1, d1 = SW_END_COND_BLIND, mm_to_m(depth_mm)

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
            raise SolidWorksError("FeatureCut4 failed (None). Does the slot fit on the +Z face?")
        return self._with_depth(self._finish_feature(cut, name, **sketch), depth_mm)
