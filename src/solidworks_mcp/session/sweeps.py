"""Sweeps, lofts and ribs, including their path/profile helpers.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    SW_SKETCH_ARC,
    SW_SKETCH_LINE,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m


class SweepsMixin:
    """Sweeps, lofts and ribs, including their path/profile helpers."""

    def _draw_path_on_front(self, model, path_mm, bend_radius_mm) -> tuple:
        """Draw a rounded polyline path on the Front plane.

        Returns (the new sketch's name, its _fix_sketch result). Shared by the
        sweep builders. Pins the sketch to the Front plane (every builder selects
        its plane explicitly), rounds interior corners with bend_radius_mm (see
        _round_polyline), and identifies the just-drawn sketch via a
        ProfileFeature before/after diff. The path is fixed rather than
        dimensioned: it is given as points, and its bends follow from them.
        Drawn with AddToDB, so no automatic relation makes the Fix redundant.
        """
        segs = self._round_polyline(path_mm, bend_radius_mm)
        plane = self._first_ref_plane()
        if plane is None:
            raise SolidWorksError("No reference plane found in the feature tree.")
        if not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the reference plane.")

        before = self._profile_feature_names()
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            drawn = []
            sk.AddToDB = True
            try:
                for s in segs:
                    if s[0] == "line":
                        (x1, y1), (x2, y2) = s[1], s[2]
                        seg = sk.CreateLine(mm_to_m(x1), mm_to_m(y1), 0.0, mm_to_m(x2), mm_to_m(y2), 0.0)
                        if not seg:
                            raise SolidWorksError("Could not create a path line.")
                    else:
                        _, c, p1, p2, direction = s
                        seg = sk.CreateArc(
                            mm_to_m(c[0]),
                            mm_to_m(c[1]),
                            0.0,
                            mm_to_m(p1[0]),
                            mm_to_m(p1[1]),
                            0.0,
                            mm_to_m(p2[0]),
                            mm_to_m(p2[1]),
                            0.0,
                            direction,
                        )
                        if seg is None:
                            raise SolidWorksError("Could not create a path arc.")
                    drawn.append(seg)
            finally:
                sk.AddToDB = False
            fixed = self._fix_sketch(sk, drawn)
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the path sketch

        new_names = self._profile_feature_names() - before
        if len(new_names) != 1:
            raise SolidWorksError(
                f"Could not identify the path just drawn (expected 1 new sketch, found {len(new_names)})."
            )
        return new_names.pop(), fixed

    def add_swept_pipe(
        self, path_mm: list, diameter_mm: float, bend_radius_mm: float = 0.0, name: str = "Pipe", smooth: bool = False
    ) -> dict:
        """Sweep a circular profile (pipe/tube/rod) along a 2D path on the Front plane.

        path_mm = [[x, y], ...] in mm: the pipe centreline. Interior corners are
        rounded with bend_radius_mm (required when the path has corners; a 2-point
        straight path needs none); smooth=True runs a spline through the points
        instead, a flowing curve without straight stretches. diameter_mm is the
        outer diameter; the round profile is generated perpendicular to the path
        automatically. Returns mass properties (volume = pi*(d/2)^2 * path_length)
        and path_length_mm. Use new_part first.
        """
        model = self._require_model()
        if diameter_mm <= 0:
            raise SolidWorksError(f"diameter must be > 0 (got {diameter_mm}).")

        if smooth:
            path_name, path = self._draw_spline_path_on_front(model, path_mm)
        else:
            path_name, path = self._draw_path_on_front(model, path_mm, bend_radius_mm)
        model.ClearSelection2(True)
        ext = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        if not ext.SelectByID2(path_name, "SKETCH", 0.0, 0.0, 0.0, False, 4, None, 0):  # mark 4 = sweep path
            raise SolidWorksError(f"Could not select the path '{path_name}'.")

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        pipe = feat_mgr.InsertProtrusionSwept4(
            False,  # Propagate
            False,  # Alignment
            0,  # TwistCtrlOption
            False,  # KeepTangency
            False,  # BAdvancedSmoothing
            0,
            0,  # Start/EndMatchingType
            False,  # IsThinBody
            0.0,
            0.0,
            0,  # Thickness1, Thickness2, ThinType
            0,  # PathAlign
            True,  # Merge
            True,  # UseFeatScope
            True,  # UseAutoSelect
            0.0,  # TwistAngle
            True,  # BMergeSmoothFaces
            True,  # CircularProfile (auto round profile, perpendicular to path)
            mm_to_m(diameter_mm),  # CircularProfileDiameter
            0,  # Direction
        )
        if pipe is None:
            raise SolidWorksError(
                "InsertProtrusionSwept4 failed (None). Is the path valid (no overlapping bends, radius fits)?"
            )
        return self._finish_feature(pipe, name, **path)

    def _draw_spline_path_on_front(self, model, path_mm) -> tuple:
        """Draw an open spline through path_mm on the Front plane, fixed (its
        points are the design). Returns (the sketch's name, its fix result with
        the path's length)."""
        pts = [(float(p[0]), float(p[1])) for p in path_mm]
        if len(pts) < 2 or len({p for p in pts}) != len(pts):
            raise SolidWorksError(f"A smooth path needs 2 or more distinct points (got {path_mm}).")
        plane = self._first_ref_plane()
        if plane is None or not plane.Select2(False, 0):
            raise SolidWorksError("Could not select the Front plane for the path.")
        before = self._profile_feature_names()
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            coords = [mm_to_m(c) for x, y in pts for c in (x, y, 0.0)]
            sk.AddToDB = True
            try:
                spline = sk.CreateSpline2(win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, coords), False)
            finally:
                sk.AddToDB = False
            if not spline:
                raise SolidWorksError("Spline path failed: CreateSpline2 returned nothing.")
            length = m_to_mm(binding.wrap(spline, self._mod.ISketchSegment).GetLength())
            fixed = self._fix_sketch(sk, [spline])
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)
        new_names = self._profile_feature_names() - before
        if len(new_names) != 1:
            raise SolidWorksError(f"Could not identify the path just drawn (found {len(new_names)} new sketches).")
        return new_names.pop(), {**fixed, "path_length_mm": round(length, 4)}

    @staticmethod
    def _require_path_starts_along_x(path_mm) -> None:
        """Fail-fast: a swept-profile path must start at the origin heading +X.

        The cross-section sits on the Right plane (normal +X), so the path's start
        tangent must be +X for the profile to be perpendicular to it. Pure helper.
        """
        raw = [(float(x), float(y)) for x, y in path_mm]
        if len(raw) < 2:
            raise SolidWorksError("path needs at least 2 points.")
        p0 = raw[0]
        p1 = next((p for p in raw[1:] if abs(p[0] - p0[0]) > 1e-9 or abs(p[1] - p0[1]) > 1e-9), None)
        if p1 is None:
            raise SolidWorksError("path needs at least 2 distinct points.")
        if math.hypot(p0[0], p0[1]) > 1e-6:
            raise SolidWorksError("path must start at the origin (0,0).")
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        if dx / math.hypot(dx, dy) < 1.0 - 1e-6:  # start tangent not +X
            raise SolidWorksError("path must start along +X (first segment pointing +X).")

    def add_swept_profile(
        self, profile_mm: list, path_mm: list, bend_radius_mm: float = 0.0, name: str = "Sweep", corner_radii_mm=None
    ) -> dict:
        """Sweep an arbitrary closed PROFILE (cross-section) along a 2D PATH.

        profile_mm = [[u, v], ...] in mm: the closed cross-section, drawn on the
        Right plane (u along world -Z, v along world +Y), centred near the origin.
        path_mm = [[x, y], ...] in mm on the Front plane; it MUST start at the
        origin heading +X (so the profile is perpendicular to the path there).
        Interior path corners are rounded with bend_radius_mm; corner_radii_mm
        rounds the profile's corners as for add_extruded_profile. Volume =
        profile_area * path_length (Pappus). For non-round extrusions along a path
        (rails, gaskets, trim, channels). Returns mass properties. Use new_part first.
        """
        model = self._require_model()
        prof = self._clean_polygon(profile_mm)  # >= 3 distinct points
        corners = self._profile_corners(prof, corner_radii_mm)
        self._require_path_starts_along_x(path_mm)

        right = self._default_plane("right")

        # profile (cross-section) on the Right plane, perpendicular to the +X start
        if not right.Select2(False, 0):
            raise SolidWorksError("Could not select the Right plane.")
        before = self._profile_feature_names()
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            profile = self._draw_defined_polygon(sk, [(mm_to_m(u), mm_to_m(v)) for u, v in prof], corners)
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)
        profile_names = self._profile_feature_names() - before
        if len(profile_names) != 1:
            raise SolidWorksError("Could not identify the profile after drawing it.")
        profile_name = profile_names.pop()

        # path on the Front plane (reuses the rounded-polyline path builder)
        path_name, path = self._draw_path_on_front(model, path_mm, bend_radius_mm)

        model.ClearSelection2(True)
        ext = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        if not ext.SelectByID2(profile_name, "SKETCH", 0.0, 0.0, 0.0, False, 1, None, 0):  # mark 1 = profile
            raise SolidWorksError(f"Could not select the profile '{profile_name}'.")
        if not ext.SelectByID2(path_name, "SKETCH", 0.0, 0.0, 0.0, True, 4, None, 0):  # mark 4 = path
            raise SolidWorksError(f"Could not select the path '{path_name}'.")

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        sweep = feat_mgr.InsertProtrusionSwept4(
            False,  # Propagate
            False,  # Alignment
            0,  # TwistCtrlOption
            False,  # KeepTangency
            False,  # BAdvancedSmoothing
            0,
            0,  # Start/EndMatchingType
            False,  # IsThinBody
            0.0,
            0.0,
            0,  # Thickness1, Thickness2, ThinType
            0,  # PathAlign
            True,  # Merge
            True,  # UseFeatScope
            True,  # UseAutoSelect
            0.0,  # TwistAngle
            True,  # BMergeSmoothFaces
            False,  # CircularProfile (use the selected profile sketch)
            0.0,  # CircularProfileDiameter
            0,  # Direction
        )
        if sweep is None:
            raise SolidWorksError(
                "InsertProtrusionSwept4 failed (None). Is the profile on the Right plane "
                "and does the path start at the origin along +X?"
            )
        return self._finish_feature(
            sweep,
            name,
            dimensions=profile["dimensions"],
            fully_defined=profile["fully_defined"] and path["fully_defined"],
        )

    def add_lofted_solid(self, profiles_mm: list, heights_mm: list, name: str = "Loft") -> dict:
        """Loft (blend) 2+ closed profiles on parallel planes stacked along +Z.

        profiles_mm: a list of profiles, each a list of [x, y] vertices (mm) in the
        Front-plane coordinate system (same convention as add_extruded_profile),
        or a round section {"center_mm": [x, y], "diameter_mm": d}: thick at the
        knee, thin towards the foot, the centres free to wander. heights_mm: the
        +Z offset (mm) of each profile's plane; same length as profiles_mm,
        strictly increasing, starting at 0. A 2-profile loft is a ruled
        transition; 3+ profiles blend smoothly through the intermediate ones.
        Each profile starts at its first vertex (a round one on +x), so give
        polygons in a consistent vertex order/orientation to avoid a twisted
        blend. Returns mass properties. Use new_part first.
        """
        model = self._require_model()
        if len(profiles_mm) != len(heights_mm):
            raise SolidWorksError("profiles_mm and heights_mm must have the same length.")
        if len(profiles_mm) < 2:
            raise SolidWorksError("A loft needs at least 2 profiles.")
        if heights_mm[0] != 0:
            raise SolidWorksError("heights_mm[0] must be 0 (the first profile sits on the Front plane).")
        for lo, hi in zip(heights_mm, heights_mm[1:]):
            if hi <= lo:
                raise SolidWorksError("heights_mm must be strictly increasing.")
        cleaned = [self._loft_section(p) for p in profiles_mm]  # a circle, or >= 3 distinct points

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)

        sketch_names = []
        helper_planes = []
        dimensions, fully_defined = {}, True
        for k, (poly, height) in enumerate(zip(cleaned, heights_mm)):
            plane, created = self._plane_at("front", height)
            if created:
                helper_planes.append(plane)
                dimensions[f"profile{k}_height"] = self._first_dimension_name(plane)
            model.ClearSelection2(True)
            if not plane.Select2(False, 0):
                raise SolidWorksError(f"Could not select the plane at z={height}.")
            before = self._profile_feature_names()
            sk.InsertSketch(True)
            try:
                if isinstance(poly, dict):
                    (cx, cy), diameter = poly["center_mm"], poly["diameter_mm"]
                    circle = self._draw_circle(sk, mm_to_m(cx), mm_to_m(cy), mm_to_m(diameter / 2))
                    defined = self._define_sketch(
                        sk, circles=[circle], names={("x", 0): "x", ("y", 0): "y", ("diameter", 0): "diameter"}
                    )
                else:
                    defined = self._define_sketch(
                        sk, self._draw_polyline(sk, [(mm_to_m(x), mm_to_m(y)) for x, y in poly])
                    )
            finally:
                model.ClearSelection2(True)
                sk.InsertSketch(True)
            dimensions.update({f"profile{k}_{role}": dim for role, dim in defined["dimensions"].items()})
            fully_defined = fully_defined and defined["fully_defined"]
            new_names = self._profile_feature_names() - before
            if len(new_names) != 1:
                raise SolidWorksError(f"Could not identify the profile at z={height}.")
            sketch_names.append(new_names.pop())

        model.ClearSelection2(True)
        ext = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        for sketch_name, poly, height in zip(sketch_names, cleaned, heights_mm):
            # The pick point is the profile's start point: each on +x of its circle
            # (or each first vertex) keeps the loft from twisting (verified)
            x, y = self._loft_start(poly)
            if not ext.SelectByID2(
                sketch_name, "SKETCH", mm_to_m(x), mm_to_m(y), mm_to_m(height), True, 1, None, 0
            ):  # mark 1, append
                raise SolidWorksError(f"Could not select profile '{sketch_name}'.")

        loft = feat_mgr.InsertProtrusionBlend(
            False,  # Closed
            False,  # KeepTangency
            False,  # ForceNonRational
            1.0,  # TessToleranceFactor
            0,
            0,  # Start/EndMatchingType
            0.0,
            0.0,  # Start/EndTangentLength
            False,
            False,  # Start/EndTangentDir
            False,  # IsThinBody
            0.0,
            0.0,
            0,  # Thickness1, Thickness2, ThinType
            True,  # Merge
            True,  # UseFeatScope
            True,  # UseAutoSelect
        )
        if loft is None:
            raise SolidWorksError("InsertProtrusionBlend failed (None). Are the profiles stacked validly?")
        # The offset planes are construction geometry; hide them so they don't
        # clutter screenshots.
        for plane in helper_planes:
            if plane.Select2(False, 0):
                model.BlankRefGeom()
        model.ClearSelection2(True)
        return self._finish_feature(loft, name, dimensions=dimensions, fully_defined=fully_defined)

    def loft_sketches(self, sketches: list, name: str = "Loft") -> dict:
        """Loft through 2+ closed sketches of the part, by name, in order: on
        any planes (add_plane, add_sketch), so a loft runs in any direction.
        Each sketch is picked at its first segment's start (a circle on its
        sketch x axis): start the sketches at matching corners to keep the
        loft from twisting. Their dimensions come back. Returns mass properties."""
        if len(sketches) < 2:
            raise SolidWorksError("A loft needs at least 2 sketches.")
        model = self._require_model()
        self._require_part()
        picks = [(sketch, self._loft_pick_point(sketch)) for sketch in sketches]
        model.ClearSelection2(True)
        ext = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        for sketch, (x, y, z) in picks:
            if not ext.SelectByID2(sketch, "SKETCH", mm_to_m(x), mm_to_m(y), mm_to_m(z), True, 1, None, 0):
                raise SolidWorksError(f"Could not select the sketch '{sketch}'.")
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        loft = feat_mgr.InsertProtrusionBlend(
            False, False, False, 1.0, 0, 0, 0.0, 0.0, False, False, False, 0.0, 0.0, 0, True, True, True
        )
        model.ClearSelection2(True)
        if loft is None:
            raise SolidWorksError(
                f"SolidWorks could not loft through {', '.join(sketches)}: is each sketch one "
                "closed outline, and do they lie apart from each other?"
            )
        dimensions = {
            f"{d['name']}": d["name"] for s in sketches for d in self._dimension_entries(self._sketch_by_name(s))
        }
        return self._finish_feature(loft, name, dimensions=dimensions)

    def _loft_pick_point(self, name: str) -> list:
        """Where a loft picks the sketch `name`, in model mm: the start of its
        first segment, or a circle's point on the sketch's x axis."""
        sketch = binding.wrap(self._sketch_by_name(name).GetSpecificFeature2(), self._mod.ISketch)
        to_model = binding.wrap(
            binding.wrap(sketch.ModelToSketchTransform, self._mod.IMathTransform).Inverse(), self._mod.IMathTransform
        )
        for dispatch in sketch.GetSketchSegments() or ():
            segment = binding.wrap(dispatch, self._mod.ISketchSegment)
            if segment.ConstructionGeometry:
                continue
            if segment.GetType() == SW_SKETCH_LINE:
                start = binding.wrap(
                    binding.wrap(dispatch, self._mod.ISketchLine).GetStartPoint2(), self._mod.ISketchPoint
                )
                return self._to_model_mm(to_model, start.X, start.Y, start.Z)
            if segment.GetType() == SW_SKETCH_ARC:
                arc = binding.wrap(dispatch, self._mod.ISketchArc)
                if arc.IsCircle():
                    centre = binding.wrap(arc.GetCenterPoint2(), self._mod.ISketchPoint)
                    return self._to_model_mm(to_model, centre.X + arc.GetRadius(), centre.Y, centre.Z)
                start = binding.wrap(arc.GetStartPoint2(), self._mod.ISketchPoint)
                return self._to_model_mm(to_model, start.X, start.Y, start.Z)
            break
        raise SolidWorksError(f"The sketch '{name}' starts with no line or arc to loft from.")

    @staticmethod
    def _rib_material_reversed(start, end, toward) -> bool:
        """Whether InsertRib must reverse its material side to grow toward `toward`.

        SolidWorks grows a rib to the RIGHT of start->end (viewed from +Z), so a
        toward point on the left needs ReverseMaterialDir. Pure, unit-tested.
        """
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            raise SolidWorksError("The rib line has zero length: start and end coincide.")
        side = dx * (toward[1] - start[1]) - dy * (toward[0] - start[0])  # > 0: left
        if abs(side) / length < 1e-6:
            raise SolidWorksError("toward_mm lies on the rib line; pick a point on the side to fill.")
        return side > 0

    def add_rib(
        self, start_mm: list, end_mm: list, toward_mm: list, thickness_mm: float, z_mm: float, name: str = "Rib"
    ) -> dict:
        """Add a straight rib (gusset) in a plane parallel to the Front plane at z_mm.

        The rib's free edge runs start_mm -> end_mm ([x, y], the same Front-plane
        coordinates as add_extruded_profile). SolidWorks grows it toward toward_mm
        (any point on the side to fill, e.g. an L-bracket's inner corner) until it
        meets the part, thickness_mm thick and centred on the plane. Returns mass
        properties: a triangular gusset with legs a and b adds a*b/2 * thickness.
        """
        model = self._require_model()
        if thickness_mm <= 0:
            raise SolidWorksError(f"thickness_mm must be > 0 (got {thickness_mm}).")
        if z_mm < 0:
            raise SolidWorksError(f"z_mm must be >= 0 (got {z_mm}); planes are offset from the Front plane toward +Z.")
        reverse = self._rib_material_reversed(start_mm, end_mm, toward_mm)

        plane, created = self._plane_at("front", z_mm)
        helper_plane = plane if created else None
        model.ClearSelection2(True)
        if not plane.Select2(False, 0):
            raise SolidWorksError(f"Could not select the plane at z={z_mm}.")
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        try:
            sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
            sk.InsertSketch(True)
            try:
                line = self._draw_polyline(
                    sk,
                    [(mm_to_m(start_mm[0]), mm_to_m(start_mm[1])), (mm_to_m(end_mm[0]), mm_to_m(end_mm[1]))],
                    closed=False,
                )
                sketch = self._define_sketch(sk, line)
            finally:
                model.ClearSelection2(True)
                sk.InsertSketch(True)  # close the sketch; it stays selected for the rib
            before = {f.Name for f in self._iter_features()}
            # InsertRib returns nothing, so the new feature is taken from the tree.
            feat_mgr.InsertRib(True, False, mm_to_m(thickness_mm), 0, reverse, False, False, 0.0, False, False)
            rib = next((f for f in self._iter_features() if f.Name not in before and f.GetTypeName2() == "Rib"), None)
        finally:
            if helper_plane is not None and helper_plane.Select2(False, 0):
                model.BlankRefGeom()  # construction geometry; keep screenshots clean
            model.ClearSelection2(True)
        if rib is None:
            raise SolidWorksError(
                "Rib not created: on the toward_mm side the rib meets no material. "
                "Pick toward_mm on the side where the part is (e.g. the inner corner)."
            )
        return self._finish_feature(rib, name, **sketch)
