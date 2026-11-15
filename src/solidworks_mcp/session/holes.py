"""Holes, counterbores, modeled ISO threads and Hole Wizard standards.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math
import re

from .. import binding
from ..constants import (
    SCREW_FITS,
    SW_COSMETIC_THREAD_WITH_CALLOUT,
    SW_END_COND_BLIND,
    SW_END_COND_THROUGH_ALL,
    SW_FM_SWEEP_THREAD,
    SW_SEL_FACES,
    SW_START_SKETCH_PLANE,
    SW_THREAD_END_BLIND,
    SW_THREAD_METHOD_CUT,
    SW_WZD_STANDARD_ISO,
    THREAD_PROFILE_EXTERNAL,
    THREAD_PROFILE_INTERNAL,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m


class HolesMixin:
    """Holes, counterbores, modeled ISO threads and Hole Wizard standards."""

    def _cut_circle_on_z(
        self, model, diameter_mm: float, x_mm: float, y_mm: float, through: bool, depth_mm: float = 0.0
    ):
        """Cut one circle on the +Z face -- through-all or blind to depth_mm.

        Returns (the sketch's _define_sketch result, the raw FeatureCut4 feature
        or None on failure) so callers attach their own error message. Shared
        by add_hole and add_counterbore_hole; sketching on the selected +Z face is
        what makes the cut direction unambiguous. (x_mm, y_mm) are in add_box
        coordinates.
        """
        body = self._solid_body()
        self._select_planar_face(body, (0.0, 0.0, 1.0), "+Z")
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)  # the sketch is created on the selected face
        try:
            circle = self._draw_circle(sk, mm_to_m(x_mm), mm_to_m(y_mm), mm_to_m(diameter_mm / 2.0))
            sketch = self._define_sketch(sk, circles=[circle], names={("x", 0): "x", ("y", 0): "y"})
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the sketch

        t1 = SW_END_COND_THROUGH_ALL if through else SW_END_COND_BLIND
        d1 = 0.0 if through else mm_to_m(depth_mm)
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        return sketch, feat_mgr.FeatureCut4(
            True,
            False,
            False,  # Sd, Flip, Dir
            t1,
            0,  # T1 (end condition), T2
            d1,
            0.0,  # D1 (depth, 0 for through-all), D2
            False,
            False,  # Dchk1, Dchk2
            False,
            False,  # Ddir1, Ddir2
            0.0,
            0.0,  # Dang1, Dang2
            False,
            False,  # OffsetReverse1, OffsetReverse2
            False,
            False,  # TranslateSurface1, TranslateSurface2
            False,  # NormalCut
            True,  # UseFeatScope
            True,  # UseAutoSelect
            False,  # AssemblyFeatureScope
            False,  # AutoSelectComponents
            False,  # PropagateFeatureToParts
            SW_START_SKETCH_PLANE,  # T0 (start condition)
            0.0,  # StartOffset
            False,  # FlipStartOffset
            False,  # OptimizeGeometry
        )

    def add_hole(self, diameter_mm: float, x_mm: float, y_mm: float, name: str = "Hole") -> dict:
        """Cut a circular through-hole at (x, y), straight through the depth axis.

        Selects the +Z face (the face parallel to add_box's width x height
        profile) and cuts through all material to the opposite face -- i.e. a hole
        through a plate's thickness, along the extrude direction. (x_mm, y_mm) are
        in add_box's coordinate system, so the centre of a 40x20 profile is x=20,
        y=10. Returns the resulting mass properties.
        """
        model = self._require_model()
        if diameter_mm <= 0:
            raise SolidWorksError(f"diameter must be > 0 (got {diameter_mm}).")
        sketch, cut = self._cut_circle_on_z(model, diameter_mm, x_mm, y_mm, through=True)
        if cut is None:
            raise SolidWorksError("FeatureCut4 failed (None). Is (x, y) inside the part's material?")
        return self._finish_feature(cut, name, **sketch)

    def add_counterbore_hole(
        self,
        clearance_diameter_mm: float,
        cbore_diameter_mm: float,
        cbore_depth_mm: float,
        x_mm: float,
        y_mm: float,
        name: str = "Counterbore",
    ) -> dict:
        """Cut a counterbored screw hole on the +Z face at (x, y).

        A clearance shank cut THROUGH_ALL, plus a larger coaxial flat-bottom pocket
        cut BLIND to cbore_depth_mm from +Z -- so a cap-head screw (or heat-set
        insert) sits flush/recessed. Volume removed =
        pi*r_clear^2*thickness + pi*(R_cbore^2 - r_clear^2)*cbore_depth.
        Returns mass properties. Use after building a plate (e.g. add_box).
        """
        model = self._require_model()
        if clearance_diameter_mm <= 0 or cbore_diameter_mm <= 0:
            raise SolidWorksError("diameters must be > 0.")
        if cbore_diameter_mm <= clearance_diameter_mm:
            raise SolidWorksError("cbore_diameter must be larger than clearance_diameter.")
        if cbore_depth_mm <= 0:
            raise SolidWorksError(f"cbore_depth must be > 0 (got {cbore_depth_mm}).")

        # Through clearance shank first (clean +Z face), then the blind pocket: the
        # pocket removes the annular ring around the already-cut shank.
        shank_sketch, shank = self._cut_circle_on_z(model, clearance_diameter_mm, x_mm, y_mm, through=True)
        if shank is None:
            raise SolidWorksError("Clearance hole (FeatureCut4) failed (None). Is (x, y) inside the material?")
        cbore_sketch, cbore = self._cut_circle_on_z(
            model, cbore_diameter_mm, x_mm, y_mm, through=False, depth_mm=cbore_depth_mm
        )
        if cbore is None:
            raise SolidWorksError("Counterbore pocket (FeatureCut4) failed (None).")
        # two sketches, one per cut: the pocket's position is its own, set it along
        # (a centre on an origin axis has a relation there, not a dimension)
        dimensions = {
            ("clearance_diameter" if role == "diameter" else role): dim
            for role, dim in shank_sketch["dimensions"].items()
        }
        dimensions.update({f"cbore_{role}": dim for role, dim in cbore_sketch["dimensions"].items()})
        result = self._finish_feature(
            cbore,
            name,
            dimensions=dimensions,
            fully_defined=shank_sketch["fully_defined"] and cbore_sketch["fully_defined"],
        )
        dimensions["cbore_depth"] = f"D1@{result['feature']}"
        return result

    @staticmethod
    def _parse_thread_size(size) -> tuple:
        """(diameter, pitch) in mm from an ISO metric size like 'M10x1.5'; pure."""
        match = re.fullmatch(r"M(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", str(size))
        if not match:
            raise SolidWorksError(f"Unknown thread size '{size}'. Use ISO metric notation like 'M10x1.5' or 'M3x0.5'.")
        return float(match.group(1)), float(match.group(2))

    @staticmethod
    def _thread_minor_diameter(diameter_mm, pitch_mm) -> float:
        """ISO basic minor diameter D1 = D - 2 * 5*sqrt(3)/16 * P (ISO 724); pure."""
        return diameter_mm - 5 * math.sqrt(3) / 8 * pitch_mm

    def _circular_edges_at(self, x_mm, y_mm, z_mm) -> list:
        """(raw edge, radius in mm) of every circular edge centred on (x, y, z) mm."""
        edges = self._solid_body().GetEdges() or ()
        if not isinstance(edges, (list, tuple)):
            edges = [edges]
        found = []
        for edge_dispatch in edges:
            curve = binding.wrap(binding.wrap(edge_dispatch, self._mod.IEdge).GetCurve(), self._mod.ICurve)
            if curve is None or not curve.IsCircle():
                continue
            params = curve.CircleParams  # centre xyz, axis xyz, radius (m)
            centre = [m_to_mm(v) for v in params[0:3]]
            if math.dist(centre, (x_mm, y_mm, z_mm)) < self._EDGE_POINT_TOLERANCE_MM:
                found.append((edge_dispatch, m_to_mm(params[6])))
        return found

    def add_thread(
        self,
        size: str,
        x_mm: float,
        y_mm: float,
        z_mm: float,
        length_mm: float,
        internal: bool = False,
        name: str = "Thread",
    ) -> dict:
        """Cut a real (printable) ISO metric thread with SolidWorks' Thread feature.

        size: ISO metric as SolidWorks names it, e.g. 'M10x1.5', 'M3x0.5', 'M10x1.0'.
        (x_mm, y_mm, z_mm): centre of the circular edge where the thread starts --
        the end face of a rod (external) or the mouth of a hole (internal); the
        thread runs length_mm into the material, right-handed.
        External: the rod must have the nominal diameter (M10 -> Ø10).
        Internal: the hole must have the ISO basic minor diameter D - 1.0825*P
        (M10x1.5 -> Ø8.376). SolidWorks shifts a tapped thread with the hole, so
        any other hole would give a wrong thread and is refused.
        """
        model = self._require_model()
        if length_mm <= 0:
            raise SolidWorksError(f"length_mm must be > 0 (got {length_mm}).")
        diameter, pitch = self._parse_thread_size(size)
        needed = self._thread_minor_diameter(diameter, pitch) if internal else diameter
        what = "hole" if internal else "rod"

        edges = self._circular_edges_at(x_mm, y_mm, z_mm)
        if not edges:
            raise SolidWorksError(
                f"No circular edge centred on ({x_mm:g}, {y_mm:g}, {z_mm:g}) mm. Give the centre "
                f"of the {what}'s edge on the face where the thread starts."
            )
        edge, radius = min(edges, key=lambda e: abs(2 * e[1] - needed))
        if abs(2 * radius - needed) > self._THREAD_DIAMETER_TOLERANCE_MM:
            hint = " Drill that ISO basic minor diameter first." if internal else ""
            raise SolidWorksError(
                f"An {'internal' if internal else 'external'} {size} thread needs a Ø{needed:.3f} "
                f"{what}, but the edge at ({x_mm:g}, {y_mm:g}, {z_mm:g}) is Ø{2 * radius:.3f}.{hint}"
            )

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        data = binding.wrap(feat_mgr.CreateDefinition(SW_FM_SWEEP_THREAD), self._mod.IThreadFeatureData)
        if data is None:
            raise SolidWorksError("CreateDefinition gave no thread definition (needs SOLIDWORKS 2016 or later).")
        data.InitializeThreadData()
        profile = THREAD_PROFILE_INTERNAL if internal else THREAD_PROFILE_EXTERNAL
        data.Type = profile
        library = data.Type  # SolidWorks resolves the name to its .sldlfp file, or '' if missing
        if not library:
            raise SolidWorksError(
                f"Thread profile library '{profile}' not found (Tools > Options > File Locations > Thread Profiles)."
            )
        # SolidWorks accepts ANY size string and silently cuts garbage for an unknown
        # one, so check it against the library's configurations (one per size).
        sizes = list(self._sw.GetConfigurationNames(library) or ())
        if size not in sizes:
            same = [s for s in sizes if s.startswith(f"M{diameter:g}x")]
            raise SolidWorksError(
                f"'{size}' is not a {profile} size. "
                + (f"Valid M{diameter:g} sizes: {same}." if same else f"Valid sizes: {sizes}.")
            )
        data.Edge = edge
        data.ThreadMethod = SW_THREAD_METHOD_CUT
        data.Size = size
        data.EndCondition = SW_THREAD_END_BLIND
        data.BlindDepth = mm_to_m(length_mm)
        data.RightHanded = True
        thread = binding.wrap(feat_mgr.CreateFeature(data), self._mod.IFeature)
        if thread is None:
            raise SolidWorksError(
                f"The thread feature failed (CreateFeature returned None). Is there "
                f"{length_mm:g} mm of material behind the edge?"
            )
        return self._finish_feature(
            thread,
            name,
            thread={
                "size": size,
                "pitch_mm": pitch,
                "major_diameter_mm": diameter,
                "minor_diameter_mm": round(self._thread_minor_diameter(diameter, pitch), 4),
                "length_mm": length_mm,
                "internal": internal,
                "right_handed": True,
            },
        )

    @staticmethod
    def _wizard_values(kind: str, fit: int, through: bool) -> list:
        """HoleWizard5's Value1..Value12 for `kind`; -1 means 'from the standard'.

        Found by trial on SOLIDWORKS 2026, each vector verified by a volume test:
        a plain hole cut through all fails unless its unused values are 0, while a
        tapped hole given zeros cuts garbage. A tapped hole keeps its cosmetic
        thread: without one SolidWorks mills the threaded length at the major
        diameter.
        """
        if kind == "tapped":
            thread_end = 1.0 if through else 0.0  # swWzdHoleThreadEndCondition_e
            return [-1.0] * 6 + [float(SW_COSMETIC_THREAD_WITH_CALLOUT), thread_end] + [-1.0] * 4
        if kind == "clearance":
            return [float(fit)] + [0.0 if through else -1.0] * 11
        return [-1.0, -1.0, -1.0, float(fit)] + [-1.0] * 8  # counterbore/countersink: fit is Value4

    def _coarse_thread_size(self, size: str) -> str:
        """'M3' -> 'M3x0.5': the coarse (largest) pitch the Metric Tap library has."""
        if not re.fullmatch(r"M\d+(?:\.\d+)?", str(size)):
            raise SolidWorksError(f"A modeled thread needs an ISO metric size like 'M3' (got '{size}').")
        feat_mgr = binding.wrap(self._model.FeatureManager, self._mod.IFeatureManager)
        data = binding.wrap(feat_mgr.CreateDefinition(SW_FM_SWEEP_THREAD), self._mod.IThreadFeatureData)
        if data is None:
            raise SolidWorksError("CreateDefinition gave no thread definition (needs SOLIDWORKS 2016 or later).")
        data.InitializeThreadData()
        data.Type = THREAD_PROFILE_INTERNAL
        sizes = [s for s in (self._sw.GetConfigurationNames(data.Type) or ()) if s.startswith(f"{size}x")]
        if not sizes:
            raise SolidWorksError(f"The '{THREAD_PROFILE_INTERNAL}' thread library has no {size} size.")
        return max(sizes, key=lambda s: self._parse_thread_size(s)[1])

    def _through_length(self, point_mm, normal, radius_mm: float) -> float:
        """How far a hole of radius_mm entering at point_mm runs along -normal, to its far edge."""
        edges = self._solid_body().GetEdges() or ()
        if not isinstance(edges, (list, tuple)):
            edges = [edges]
        length = 0.0
        for edge_dispatch in edges:
            curve = binding.wrap(binding.wrap(edge_dispatch, self._mod.IEdge).GetCurve(), self._mod.ICurve)
            if curve is None or not curve.IsCircle():
                continue
            params = curve.CircleParams  # centre xyz, axis xyz, radius (m)
            if abs(m_to_mm(params[6]) - radius_mm) > self._THREAD_DIAMETER_TOLERANCE_MM:
                continue
            offset = [m_to_mm(c) - p for c, p in zip(params[0:3], point_mm)]
            depth = -sum(o * n for o, n in zip(offset, normal))
            off_axis = math.dist(offset, [-depth * n for n in normal])
            if off_axis < self._EDGE_POINT_TOLERANCE_MM:
                length = max(length, depth)
        if length <= 0:
            raise SolidWorksError("Could not find where the through hole leaves the part.")
        return length

    def _pin_wizard_position(self, feat, point_mm) -> tuple:
        """Fully define a wizard hole's position sketch, AT point_mm.

        The Hole Wizard puts its hole where the face was picked, which lands some
        0.04 mm off, in an under-defined sketch. Its point gets dimensions from the
        origin that carry the exact coordinates. Returns (dimensions, fully_defined).
        """
        model = self._model
        position = next(
            (
                s
                for s in self._sub_features(feat)
                if s.GetTypeName2() == "ProfileFeature"
                and len(binding.wrap(s.GetSpecificFeature2(), self._mod.ISketch).GetSketchPoints2() or ()) == 1
                and not binding.wrap(s.GetSpecificFeature2(), self._mod.ISketch).GetSketchSegments()
            ),
            None,
        )
        if position is None:
            raise SolidWorksError(f"The Hole Wizard hole '{feat.Name}' has no position sketch to define.")
        model.ClearSelection2(True)
        if not position.Select2(False, 0):
            raise SolidWorksError(f"Could not select the position sketch of '{feat.Name}'.")
        model.EditSketch()
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        try:
            sketch, definer = self._open_sketch_definer(sk)
            point = binding.wrap(sketch.GetSketchPoints2()[0], self._mod.ISketchPoint)
            u, v, _ = self._sketch_coords(sketch, *(mm_to_m(c) for c in point_mm))
            u0, v0, _ = self._sketch_coords(sketch, 0.0, 0.0, 0.0)
            # x/y are the face sketch's own horizontal/vertical directions
            dims = definer.place_point(point, (m_to_mm(u - u0), m_to_mm(v - v0)))
            return dims, definer.fully_defined()
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # leave the position sketch

    def _wizard_hole_info(self, feat, kind: str, size: str, fit: str) -> dict:
        """The sizes SolidWorks took from its standard table for this hole (mm, degrees)."""
        data = binding.wrap(feat.GetDefinition(), self._mod.IWizardHoleFeatureData2)

        def mm(value):
            return round(m_to_mm(value), 4)

        info = {"standard": "ISO", "kind": kind, "size": size}
        if kind == "tapped":
            info.update(
                tap_drill_diameter_mm=mm(data.TapDrillDiameter or data.ThruTapDrillDiameter),
                thread_diameter_mm=mm(data.ThreadDiameter),
                thread_depth_mm=mm(data.ThreadDepth),
                cosmetic_thread=data.CosmeticThreadType > 0,
            )
        else:
            info.update(fit=fit, diameter_mm=mm(data.ThruHoleDiameter or data.HoleDiameter))
        if kind == "counterbore":
            info.update(cbore_diameter_mm=mm(data.CounterBoreDiameter), cbore_depth_mm=mm(data.CounterBoreDepth))
        if kind == "countersink":
            info.update(
                csink_diameter_mm=mm(data.CounterSinkDiameter),
                csink_angle_deg=round(math.degrees(data.CounterSinkAngle), 3),
            )
        return info

    def add_hole_wizard(
        self,
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
    ) -> dict:
        """An ISO hole from SolidWorks' Hole Wizard, sized by its standard tables.

        kind: 'clearance' (ISO 273), 'counterbore' (socket head cap screw,
        ISO 4762), 'countersink' (socket countersunk screw, ISO 10642) or
        'tapped'. size: ISO metric, e.g. 'M3'. Centred at 3D point (x, y, z) on
        the face through it (as add_hole_on_face); through all, or depth_mm deep
        (a blind hole ends in a 118 degree drill point). fit: 'close', 'normal'
        or 'loose' (not for tapped). thread (tapped only): 'cosmetic' drills the
        ISO tap drill and adds SolidWorks' cosmetic thread; 'modeled' drills the
        ISO basic minor diameter and cuts a real, printable thread over the
        standard thread depth (all the way through a through hole). Returns the
        standard's sizes in `hole`, and the position as dimensions x/y.
        """
        model = self._require_model()
        if kind not in self._WIZARD_KINDS:
            raise SolidWorksError(f"Unknown hole kind '{kind}'. Use one of {sorted(self._WIZARD_KINDS)}.")
        if fit not in SCREW_FITS:
            raise SolidWorksError(f"Unknown fit '{fit}'. Use one of {sorted(SCREW_FITS)}.")
        if thread not in self._WIZARD_THREADS:
            raise SolidWorksError(f"Unknown thread '{thread}'. Use 'cosmetic' or 'modeled'.")
        if thread == "modeled" and kind != "tapped":
            raise SolidWorksError("A modeled thread needs kind='tapped'.")
        if depth_mm is not None and depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        point = (x_mm, y_mm, z_mm)
        coarse = self._coarse_thread_size(size) if thread == "modeled" else None
        diameter_m = -1.0  # from the standard
        if coarse:
            major, pitch = self._parse_thread_size(coarse)
            diameter_m = mm_to_m(self._thread_minor_diameter(major, pitch))

        normal, side = self._parse_face_selector(face, default_side=None)
        target = self._select_face_through(self._solid_body(), normal, side, point, face)
        off = self._off_face_mm(target, point)
        if off > self._ON_FACE_TOLERANCE_MM:  # the pick would land on whatever lies there, e.g. a countersink
            raise SolidWorksError(
                f"({x_mm:g}, {y_mm:g}, {z_mm:g}) mm is not on the {face} face but {off:.3g} mm off it: "
                f"beyond its edge, or over an opening such as an earlier hole. Give a point on the face."
            )
        model.ClearSelection2(True)
        ext = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        # The wizard drills where the face is picked. SelectByID2 picks what the
        # view shows first at that spot (in a side view: another face, or none),
        # so a ray from just above the point straight into the face picks it.
        start = [mm_to_m(c + n * self._PICK_ABOVE_MM) for c, n in zip(point, normal)]
        if not ext.SelectByRay(
            *start, *(-n for n in normal), mm_to_m(self._ON_FACE_TOLERANCE_MM), SW_SEL_FACES, False, 0, 0
        ):
            raise SolidWorksError(f"Could not pick the {face} face at ({x_mm:g}, {y_mm:g}, {z_mm:g}) mm.")
        hole_type, fastener = self._WIZARD_KINDS[kind]
        through = depth_mm is None
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        feat = feat_mgr.HoleWizard5(
            hole_type,
            SW_WZD_STANDARD_ISO,
            fastener,
            size,
            SW_END_COND_THROUGH_ALL if through else SW_END_COND_BLIND,
            diameter_m,
            -1.0 if through else mm_to_m(depth_mm),
            -1.0,  # Diameter, Depth, Length (slots)
            *self._wizard_values(kind, SCREW_FITS[fit], through),
            "",
            False,
            False,
            True,
            False,
            False,
            False,  # ThreadClass (inch only), RevDir, scope flags
        )
        if feat is None:
            raise SolidWorksError(
                f"The Hole Wizard made no {kind} hole of size '{size}'. Is it an ISO metric size "
                f"in SolidWorks' table (e.g. 'M3', 'M4', 'M10'), with material at the point?"
            )
        feat = binding.wrap(feat, self._mod.IFeature)
        dims, fully_defined = self._pin_wizard_position(feat, point)
        info = self._wizard_hole_info(feat, kind, size, fit)
        result = self._finish_feature(feat, name or feat.Name, dimensions=dims, fully_defined=fully_defined, hole=info)
        if coarse:
            radius = m_to_mm(diameter_m) / 2
            length = self._through_length(point, normal, radius) if through else info["thread_depth_mm"]
            threaded = self.add_thread(
                coarse, x_mm, y_mm, z_mm, length, internal=True, name=f"{result['feature']} Thread"
            )
            result.update(thread=threaded["thread"], mass_properties=threaded["mass_properties"])
        return result
