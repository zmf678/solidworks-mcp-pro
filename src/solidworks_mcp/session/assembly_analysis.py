"""Interference, distance checks, motion studies and swept regions.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

from .. import binding
from ..errors import SolidWorksError
from ..mesh_tools import section
from ..region_tools import swept_outline
from ..units import m_to_mm, mm_to_m
from ._decorators import _reads_only


class AssemblyAnalysisMixin:
    """Interference, distance checks, motion studies and swept regions."""

    @_reads_only
    def check_interference(self) -> dict:
        """Find components whose solids overlap; volumes in mm^3, per pair.

        Touching faces are NOT an interference (a bed standing on the floor is
        fine); only real overlapping material counts. SolidWorks reports each
        disjoint overlapping lump separately, so the lumps are summed per
        component pair and counted as `regions`.
        """
        asm = self._require_assembly()
        manager = binding.wrap(asm.InterferenceDetectionManager, self._mod.IInterferenceDetectionMgr)
        if manager is None:
            raise SolidWorksError("Could not open the InterferenceDetectionManager.")
        manager.TreatCoincidenceAsInterference = False
        manager.TreatSubAssembliesAsComponents = True
        manager.IncludeMultibodyPartInterferences = False
        pairs = {}
        try:
            found = manager.GetInterferences()
            for item in found or []:
                interference = binding.wrap(item, self._mod.IInterference)
                components = interference.Components
                names = tuple(sorted(binding.wrap(c, self._mod.IComponent2).Name2 for c in (components or [])))
                entry = pairs.setdefault(names, {"components": list(names), "volume_mm3": 0.0, "regions": 0})
                entry["volume_mm3"] += interference.Volume * 1e9
                entry["regions"] += 1
        finally:
            manager.Done()
        result = sorted(pairs.values(), key=lambda e: -e["volume_mm3"])
        for entry in result:
            entry["volume_mm3"] = round(entry["volume_mm3"], 4)
        return {"ok": True, "count": len(result), "interferences": result}

    @_reads_only
    def measure_distance(
        self,
        component_a: str,
        component_b: str | None = None,
        point_mm: list | None = None,
        axis_mm: list | None = None,
    ) -> dict:
        """The smallest distance (mm) from a component of the current assembly to
        another one, to a point (assembly mm, with the nearest point on the
        component), or to an axis: the endless line axis_mm = [[x, y, z], [dx,
        dy, dz]] through a point along a direction, such as a bolt's axis. 0
        where they touch or overlap; check_interference tells which. A point in
        the material comes back with inside: true and its distance to the surface.
        """
        if sum(target is not None for target in (component_b, point_mm, axis_mm)) != 1:
            raise SolidWorksError("Give one of component_b, point_mm or axis_mm.")
        if point_mm is not None and len(point_mm) != 3:
            raise SolidWorksError(f"point_mm needs [x, y, z] (got {point_mm}).")
        line = None if axis_mm is None else self._axis_line(axis_mm)
        asm = self._require_assembly()
        comp = self._component_by_name(asm, component_a)
        if component_b is not None:
            return self._distance_between(comp, self._component_by_name(asm, component_b))
        if line is not None:
            with self._writing():  # it draws a temporary sketch line
                return self._distance_to_line(comp, *line)
        return self._distance_to_point(comp, [float(c) for c in point_mm])

    @staticmethod
    def _axis_line(axis_mm) -> tuple:
        """[[x, y, z], [dx, dy, dz]] -> (point, unit direction); pure, unit-tested."""
        try:
            point, direction = [[float(c) for c in vector] for vector in axis_mm]
        except (TypeError, ValueError):
            raise SolidWorksError(f"axis_mm needs [[x, y, z], [dx, dy, dz]] (got {axis_mm}).") from None
        length = math.hypot(*direction)
        if len(point) != 3 or len(direction) != 3 or length < 1e-9:
            raise SolidWorksError(f"axis_mm needs a point and a direction that is not zero (got {axis_mm}).")
        return point, [d / length for d in direction]

    def _distance_to_line(self, comp, point, direction) -> dict:
        """Measured against a temporary 3D sketch line that reaches well past the
        component either way, deleted again afterwards."""
        model = self._model
        box = self._component_box(comp)
        if box is None:
            raise SolidWorksError(f"Component '{comp.Name2}' has no solid body to measure to.")
        centre = [(lo + hi) / 2 for lo, hi in zip(box["min_mm"], box["max_mm"])]
        reach = math.dist(box["min_mm"], box["max_mm"]) + math.dist(centre, point) + 10.0
        ends = [[mm_to_m(p + sign * reach * d) for p, d in zip(point, direction)] for sign in (-1.0, 1.0)]
        before = {f.Name for f in self._iter_features()}
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.Insert3DSketch(True)
        try:
            sk.AddToDB = True
            line = sk.CreateLine(*ends[0], *ends[1])
            sk.AddToDB = False
        finally:
            sk.Insert3DSketch(True)
        helpers = [f for f in self._iter_features() if f.Name not in before]
        try:
            if line is None:
                raise SolidWorksError("Could not draw the axis line to measure to.")
            selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
            model.ClearSelection2(True)
            if not (
                comp.Select4(False, selmgr.CreateSelectData(), False)
                and binding.wrap(line, self._mod.ISketchSegment).Select4(True, selmgr.CreateSelectData())
            ):
                raise SolidWorksError(f"Could not select '{comp.Name2}' and the axis line.")
            measure = binding.wrap(
                binding.wrap(model.Extension, self._mod.IModelDocExtension).CreateMeasure(), self._mod.IMeasure
            )
            if measure is None or not measure.Calculate(None) or not (measure.IsIntersect or measure.Distance >= 0):
                raise SolidWorksError(f"SolidWorks could not measure from '{comp.Name2}' to the axis.")
            distance = 0.0 if measure.IsIntersect else measure.Distance
        finally:
            extension = binding.wrap(model.Extension, self._mod.IModelDocExtension)
            for helper in helpers:
                model.ClearSelection2(True)
                if helper.Select2(False, 0):
                    extension.DeleteSelection2(0)
            model.ClearSelection2(True)
        return {
            "ok": True,
            "from": comp.Name2,
            "axis_mm": [point, direction],
            "distance_mm": round(m_to_mm(distance), 4),
        }

    def _distance_between(self, first, second) -> dict:
        """The smallest distance between the parts of the two: SolidWorks would
        not measure to a sub-assembly as a whole."""
        distance = min(self._measured_apart(a, b) for a in self._solid_parts(first) for b in self._solid_parts(second))
        return {"ok": True, "between": [first.Name2, second.Name2], "distance_mm": round(m_to_mm(distance), 4)}

    def _measured_apart(self, first, second) -> float:
        """IMeasure between two part components, in m."""
        model = self._require_model()
        selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
        model.ClearSelection2(True)
        try:
            if not (
                first.Select4(False, selmgr.CreateSelectData(), False)
                and second.Select4(True, selmgr.CreateSelectData(), False)
            ):
                raise SolidWorksError(f"Could not select '{first.Name2}' and '{second.Name2}'.")
            measure = binding.wrap(
                binding.wrap(model.Extension, self._mod.IModelDocExtension).CreateMeasure(), self._mod.IMeasure
            )
            if measure is None or not measure.Calculate(None) or not (measure.IsIntersect or measure.Distance >= 0):
                raise SolidWorksError(f"SolidWorks could not measure between '{first.Name2}' and '{second.Name2}'.")
            # touching or overlapping: SolidWorks reports no distance then, only the meeting (verified)
            return 0.0 if measure.IsIntersect else measure.Distance
        finally:
            model.ClearSelection2(True)

    def _distance_to_point(self, comp, point_mm) -> dict:
        """Nearest point on the faces of the component's parts, each searched in
        its own frame."""
        best = None  # (gap in assembly m, face, nearest and point in part m, part frame)
        for part in self._solid_parts(comp):
            rotation, shift, scale = self._frame(part)
            relative = [mm_to_m(p) - s for p, s in zip(point_mm, shift)]
            local = [sum(rotation[row][i] * relative[row] for row in range(3)) / scale for i in range(3)]  # R^T (p - t)
            for body in self._solid_bodies(part):
                for face_dispatch in body.GetFaces() or ():
                    face = binding.wrap(face_dispatch, self._mod.IFace2)
                    nearest = face.GetClosestPointOn(*local)
                    if not nearest or len(nearest) < 3:
                        raise SolidWorksError(f"SolidWorks found no nearest point on a face of '{part.Name2}'.")
                    gap = math.dist(local, nearest[:3]) * scale
                    if best is None or gap < best[0]:
                        best = (gap, face, nearest[:3], local, (rotation, shift, scale))
        if best is None:
            raise SolidWorksError(f"Component '{comp.Name2}' has no solid body to measure to.")
        gap, face, nearest, local, (rotation, shift, scale) = best
        on_component = [scale * sum(rotation[row][i] * nearest[i] for i in range(3)) + shift[row] for row in range(3)]
        return {
            "ok": True,
            "from": comp.Name2,
            "point_mm": point_mm,
            "distance_mm": round(m_to_mm(gap), 4),
            "nearest_mm": [round(m_to_mm(c), 4) for c in on_component],
            "inside": self._on_material_side(face, nearest, local),
        }

    def _on_material_side(self, face, nearest, point) -> bool:
        """Whether `point` lies behind `face` at its nearest point `nearest`."""
        surface = binding.wrap(face.GetSurface(), self._mod.ISurface)
        normal = surface.EvaluateAtPoint(*nearest)[:3]
        # With FaceInSurfaceSense the surface normal points INTO the material
        # (verified on planes and cylinders, with both senses).
        outward = [-n for n in normal] if face.FaceInSurfaceSense() else list(normal)
        return sum((p - q) * n for p, q, n in zip(point, nearest, outward)) < 0

    def check_motion(self, dimension_name: str, values: list, distances: list | None = None) -> dict:
        """Step a dimension through `values` and check the assembly at every
        step: an angle mate's joint angle (degrees) or a distance mate's travel
        (mm), as add_mate returns them.

        Each step gives the overlapping component pairs with their volume and
        the distance between each pair in `distances` ([["Rod", "Bolt"], ...]);
        the summary gives whether every step is clash-free and each pair's
        smallest distance with the value where it occurs, and `moving` the
        components that moved. Nothing moving fails: the mate the dimension
        belongs to holds nothing any more (suppressed, or a face it used is
        gone). The dimension goes back to its value afterwards.
        """
        if not values:
            raise SolidWorksError("Give the values to step through, e.g. [30, 60, 90].")
        pairs = [list(pair) for pair in distances or ()]
        if any(len(pair) != 2 for pair in pairs):
            raise SolidWorksError(f"distances takes component pairs [[a, b], ...] (got {distances}).")
        asm = self._require_assembly()
        for name in {name for pair in pairs for name in pair}:
            self._component_by_name(asm, name)  # a wrong name fails before anything moves
        self._refuse_broken_mates()
        dim = self._dimension(dimension_name)
        unit, to_system, from_system = self._dimension_unit(dim)
        original = dim.SystemValue
        everything = self._nested_components(self._components(asm))  # a joint inside a sub-assembly moves its parts
        start = {c.Name2: self._transform_data(c) for c in everything}
        moving, steps = set(), []
        try:
            for value in values:
                target = self._joint_angle(dim, unit, value)
                rebuilt = self._write_dimension(dim, to_system(target))
                applied = from_system(dim.SystemValue)
                if abs(applied - target) > 1e-6:
                    raise SolidWorksError(
                        f"'{dimension_name}' did not take {value:g} {unit} (it reads "
                        f"{applied:g}): is it a driven dimension?"
                    )
                moving |= {c.Name2 for c in everything if self._moved(start.get(c.Name2), c)}
                steps.append(
                    {
                        f"value_{unit}": value,
                        "rebuild_ok": rebuilt,
                        "interferences": self.check_interference()["interferences"],
                        "distances": [self.measure_distance(a, b) for a, b in pairs],
                    }
                )
        finally:
            self._write_dimension(dim, original)
        if not moving and any(abs(to_system(value) - original) > 1e-12 for value in values):
            raise SolidWorksError(
                f"Stepping '{dimension_name}' through {values} moved no component: its mate holds "
                "nothing any more (suppressed, or a face it used is gone); list_components shows it."
            )
        # what moved inside a sub-assembly that moved as a whole goes with it
        moving = {name for name in moving if not any(name.startswith(other + "/") for other in moving)}
        for step in steps:
            step["distances"] = [{"between": d["between"], "distance_mm": d["distance_mm"]} for d in step["distances"]]
        smallest = []
        for i in range(len(pairs)):
            closest = min(steps, key=lambda s: s["distances"][i]["distance_mm"])
            smallest.append({**closest["distances"][i], f"at_{unit}": closest[f"value_{unit}"]})
        return {
            "ok": True,
            "dimension": dimension_name,
            "steps": steps,
            "moving": sorted(moving),
            "clash_free": not any(step["interferences"] for step in steps),
            "smallest_distances": smallest,
        }

    def _moved(self, before, comp) -> bool:
        """Whether the component's transform left `before` (a new one has moved)."""
        if before is None:
            return True
        now = self._transform_data(comp)
        return any(abs(a - b) > self._ROTATION_TOLERANCE for a, b in zip(before[:9], now[:9])) or any(
            abs(a - b) > mm_to_m(self._TRANSFORM_TOLERANCE_MM) for a, b in zip(before[9:12], now[9:12])
        )

    def swept_region(
        self,
        component: str,
        dimension: str,
        values: list,
        heights_mm: list,
        axis: str = "z",
        margin_mm: float = 0.0,
        tolerance_mm: float = 0.2,
        frame: str | None = None,
    ) -> dict:
        """What a component covers in a plane while a joint moves.

        Steps `dimension` through `values` (as check_motion), cuts the component
        at every step where `axis` = each of heights_mm, and outlines all of it
        together, margin_mm wider and within about tolerance_mm. Give a layer a
        few heights inside it, not on its faces. Coordinates are those of the
        `frame` component (the part to cut it from), else the assembly's; each
        region's outline runs counter-clockwise in the plane's other two axes,
        (x, y) across z, ready for add_sketch as a spline. The dimension goes
        back to its value afterwards.
        """
        if not values:
            raise SolidWorksError("Give the values to step through, e.g. [30, 60, 90].")
        if not heights_mm:
            raise SolidWorksError("Give the heights to cut at, e.g. [-19.2] or a few inside a layer.")
        key = str(axis).lower()
        if key not in ("x", "y", "z"):
            raise SolidWorksError(f"Unknown axis '{axis}'. Use 'x', 'y' or 'z'.")
        asm = self._require_assembly()
        comp = self._component_by_name(asm, component)
        framer = self._component_by_name(asm, frame) if frame else None
        self._refuse_broken_mates()
        pieces = [
            (
                part,
                [
                    tri[:3]
                    for body in self._solid_bodies(part)
                    for face in self._body_faces(body)
                    for tri in self._face_triangles(binding.wrap(face, self._mod.IFace2))
                ],
            )
            for part in self._solid_parts(comp)
        ]  # in each part's own coordinates, read once
        dim = self._dimension(dimension)
        unit, to_system, from_system = self._dimension_unit(dim)
        original = dim.SystemValue
        start = {part.Name2: self._transform_data(part) for part, _ in pieces}
        sections, moved = [], False
        try:
            for value in values:
                target = self._joint_angle(dim, unit, value)
                self._write_dimension(dim, to_system(target))
                applied = from_system(dim.SystemValue)
                if abs(applied - target) > 1e-6:
                    raise SolidWorksError(
                        f"'{dimension}' did not take {value:g} {unit} (it reads {applied:g}): is it a driven dimension?"
                    )
                for part, triangles in pieces:
                    moved = moved or self._moved(start[part.Name2], part)
                    place = self._placement_into(part, framer)
                    placed = [tuple(place(p) for p in tri) for tri in triangles]
                    sections += [loops for height in heights_mm if (loops := section(placed, key, height))]
        finally:
            self._write_dimension(dim, original)
        if not moved and any(abs(to_system(value) - original) > 1e-12 for value in values):
            raise SolidWorksError(
                f"Stepping '{dimension}' through {values} moved no part of '{comp.Name2}': its "
                "mate holds nothing (suppressed, or a face it used is gone), or it moves something else."
            )
        if not sections:
            raise SolidWorksError(
                f"'{comp.Name2}' does not reach {key} = {', '.join(f'{h:g}' for h in heights_mm)} "
                f"mm in {framer.Name2 if framer else 'the assembly'}'s coordinates at any step."
            )
        regions = swept_outline(sections, tolerance_mm, margin_mm)
        return {
            "ok": True,
            "component": comp.Name2,
            "frame": framer.Name2 if framer else "assembly",
            "dimension": dimension,
            f"values_{unit}": list(values),
            "axis": key,
            "heights_mm": list(heights_mm),
            "plane_axes": [a for a in ("x", "y", "z") if a != key],
            "margin_mm": margin_mm,
            "tolerance_mm": tolerance_mm,
            "count": len(regions),
            "regions": [
                {
                    **r,
                    "outline_mm": [list(p) for p in r["outline_mm"]],
                    "holes_mm": [[list(p) for p in hole] for hole in r["holes_mm"]],
                }
                for r in regions
            ],
        }

    def _placement_into(self, part, framer):
        """A function taking a point of the part (mm, its own coordinates) to
        the frame component's coordinates, or the assembly's without one."""
        rotation, shift, scale = self._frame(part)
        shift = [m_to_mm(s) for s in shift]
        if framer is None:
            back, origin, size = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [0.0] * 3, 1.0
        else:
            back, origin, size = self._frame(framer)
            origin = [m_to_mm(s) for s in origin]

        def place(p):
            world = [scale * sum(rotation[row][i] * p[i] for i in range(3)) + shift[row] for row in range(3)]
            offset = [w - o for w, o in zip(world, origin)]
            return tuple(sum(back[i][row] * offset[i] for i in range(3)) / size for row in range(3))  # R^T: the inverse

        return place

    @_reads_only
    def get_assembly_bounding_box(self) -> dict:
        """Bounding box of the whole assembly (min/max/size in mm)."""
        self._require_assembly()
        return {"ok": True, "bounding_box_mm": self._bounding_box()}
