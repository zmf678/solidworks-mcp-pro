"""Mates, mate measurement and mate repair.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    MATE_TYPES,
    SW_ADD_MATE_NO_ERROR,
    SW_DELETE_ABSORBED,
    SW_MATE_ALIGN_CLOSEST,
    SW_SUPPRESS_FEATURE,
    SW_THIS_CONFIGURATION,
    SW_UNSUPPRESS_DEPENDENT,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m


class AssemblyMatesMixin:
    """Mates, mate measurement and mate repair."""

    def _mate_entry(self, mate) -> dict:
        entry = {"name": mate.Name, "type": mate.GetTypeName2()}
        dimensions = self._dimension_entries(mate)
        if dimensions:
            entry["dimensions"] = [{key: d[key] for key in ("name", "value", "unit")} for d in dimensions]
        trouble = self._mate_trouble(mate)
        if trouble:
            entry["error"] = trouble
        return entry

    def _mate_trouble(self, mate) -> dict | None:
        """What is wrong with a mate: the error SolidWorks flags, or a face or
        edge it lost without one (a mate entity left without its reference)."""
        code, warning = mate.GetErrorCode2()
        if code:
            return self._error_entry(code, warning)
        details = binding.wrap(mate.GetSpecificFeature2(), self._mod.IMate2)
        if details is None or mate.IsSuppressed():  # suppressed, it holds nothing on purpose
            return None
        entities = [
            binding.wrap(details.MateEntity(i), self._mod.IMateEntity2) for i in range(details.GetMateEntityCount())
        ]
        if any(entity is None or entity.Reference is None for entity in entities):
            return {"code": None, "warning": False, "cause": "broken: a face or edge it used is gone"}
        return None

    def _refuse_broken_mates(self) -> None:
        """Stepping a joint while a mate is broken lets the parts it should hold
        drift: a concentric mate on a hole that was made again held nothing,
        and a part slid off its axis through the next one."""
        self._model.ForceRebuild3(False)
        broken = [
            f"{mate.Name} ({trouble['cause']})"
            for mate in self._mates()
            if (trouble := self._mate_trouble(mate)) and not trouble["warning"]
        ]
        if broken:
            raise SolidWorksError(
                f"Mate(s) {', '.join(broken)}: the parts they should hold can drift, so stepping "
                "the joint means nothing. Repair them, or delete_mate and add them again."
            )

    def _mate_by_name(self, name: str):
        mates = self._mates()
        found = [m for m in mates if m.Name == name] or [m for m in mates if m.Name.lower() == str(name).lower()]
        if len(found) != 1:
            raise SolidWorksError(f"No mate '{name}' (there are: {', '.join(m.Name for m in mates) or 'none'}).")
        return found[0]

    def delete_mate(self, name: str) -> dict:
        """Delete a mate of the current assembly by name (list_components, or
        add_mate's 'mate'); its components are free to move again."""
        model = self._require_model()
        asm = self._require_assembly()
        mate = self._mate_by_name(name)
        title = mate.Name
        model.ClearSelection2(True)
        if not mate.Select2(False, 0):
            raise SolidWorksError(f"Could not select mate '{title}'.")
        if not binding.wrap(model.Extension, self._mod.IModelDocExtension).DeleteSelection2(SW_DELETE_ABSORBED):
            raise SolidWorksError(f"SolidWorks refused to delete mate '{title}'.")
        model.ClearSelection2(True)
        asm.EditRebuild()
        return {"ok": True, "deleted": title, "mates": [m.Name for m in self._mates()]}

    def suppress_mate(self, name: str, suppress: bool = True) -> dict:
        """Suppress a mate, so it stops holding its components while it stays in
        the tree, or bring it back with suppress=False."""
        self._require_model()
        asm = self._require_assembly()
        mate = self._mate_by_name(name)
        action = SW_SUPPRESS_FEATURE if suppress else SW_UNSUPPRESS_DEPENDENT
        if not mate.SetSuppression2(action, SW_THIS_CONFIGURATION, None):
            raise SolidWorksError(
                f"SolidWorks refused to {'suppress' if suppress else 'unsuppress'} mate '{mate.Name}'."
            )
        asm.EditRebuild()
        mate = self._mate_by_name(name)
        return {"ok": True, "mate": mate.Name, "suppressed": self._is_suppressed(mate)}

    def _component_faces(self, comp) -> list:
        """Every face of every solid body of the component as (face, part): a
        part component's own faces, or those of every part in a sub-assembly.
        Faces keep their part's coordinates. They come in a fixed order, by
        part, planar first, then centre and area, so an index stays the same
        face while the shape stays: SolidWorks' own order changed between two
        calls in one assembly, after a mate."""
        faces = []
        for part in self._solid_parts(comp):
            for body in self._solid_bodies(part):
                faces.extend((binding.wrap(face, self._mod.IFace2), part) for face in body.GetFaces() or ())
        if not faces:
            raise SolidWorksError(f"Component '{comp.Name2}' has no solid body to pick a face on.")
        return sorted(faces, key=lambda found: (found[1].Name2, *self._face_order(found[0])))

    def _face_order(self, face) -> tuple:
        surface = binding.wrap(face.GetSurface(), self._mod.ISurface)
        box = face.GetBox()
        centre = tuple(round(m_to_mm((box[j] + box[j + 3]) / 2), 3) for j in range(3))
        return (0 if surface is not None and surface.IsPlane() else 1, *centre, round(face.GetArea() * 1e6, 3))

    def _part_frame_in(self, comp, part) -> tuple:
        """(rotation rows, shift mm) taking `part` coordinates into the coordinates
        of `comp`, the component it sits in (identity for comp itself)."""
        if part.Name2 == comp.Name2:
            return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [0.0, 0.0, 0.0]
        outer, inner = self._frame(comp), self._frame(part)
        rotation, shift = self._relative_frame((outer[0], outer[1]), (inner[0], inner[1]))
        return rotation, [m_to_mm(s) for s in shift]

    @staticmethod
    def _relative_frame(outer, inner) -> tuple:
        """(rotation rows, shift) taking `inner` coordinates into `outer`'s, both
        given as (rotation rows, shift) relative to one root: R_o^T R_i and
        R_o^T (t_i - t_o). Pure, unit-tested."""
        (r_o, t_o), (r_i, t_i) = outer, inner
        rotation = [[sum(r_o[k][row] * r_i[k][col] for k in range(3)) for col in range(3)] for row in range(3)]
        shift = [sum(r_o[k][row] * (t_i[k] - t_o[k]) for k in range(3)) for row in range(3)]
        return rotation, shift

    def _component_face(self, comp, selector: str):
        """Face '+x' / '-z:inner' of a component, face '#5' by its
        list_faces(component=...) index, or face '@x,y,z' through that point;
        returns (IFace2, the part it is on).

        The direction is read in the COMPONENT's own coordinate system (verified:
        a component's faces keep part coordinates however the component is
        turned), so '-x' is always the part's own -X face; in a sub-assembly, the
        sub-assembly's -X. ':inner' picks the cavity side of a hollow part -- the
        inside of a room wall, not its skin. An index reaches any face, such as a
        hole for a concentric mate; so does a point on it, in the same coordinates.
        """
        faces = self._component_faces(comp)
        if str(selector).strip().startswith("@"):
            return self._component_face_at(comp, faces, self._point_selector(selector))
        index = self._face_index(selector)
        if index is not None:
            if index >= len(faces):
                raise SolidWorksError(
                    f"Component '{comp.Name2}' has faces #0 to #{len(faces) - 1}; list_faces(component=...) shows them."
                )
            face, part = faces[index]
            return binding.wrap(face, self._mod.IFace2), part
        normal, side = self._parse_face_selector(selector)
        if side not in self._FACE_SIDES:
            raise SolidWorksError(f"Unknown face side '{side}'. Use 'outer' or 'inner'.")
        facing = []
        for part in {part.Name2: part for _, part in faces}.values():
            rotation, shift = self._part_frame_in(comp, part)
            # the direction as the part sees it, and where its faces lie along it in comp's frame
            target = [sum(rotation[k][i] * normal[k] for k in range(3)) for i in range(3)]
            along = sum(s * n for s, n in zip(shift, normal))
            facing += [
                (face, position + along, part)
                for face, position in self._planar_faces_facing([f for f, p in faces if p is part], target)
            ]
        if not facing:
            raise SolidWorksError(f"Component '{comp.Name2}' has no planar face pointing {selector}.")
        face, _, part = (max if side == "outer" else min)(facing, key=lambda found: found[1])
        return face, part

    @staticmethod
    def _point_selector(selector) -> list:
        """'@0, 0, 20.2' -> [0.0, 0.0, 20.2]; pure, unit-tested."""
        try:
            point = [float(c) for c in str(selector).strip()[1:].split(",")]
        except ValueError:
            point = []
        if len(point) != 3:
            raise SolidWorksError(f"A face by a point on it is '@x,y,z', in mm (got {selector!r}).")
        return point

    def _component_face_at(self, comp, faces, point_mm):
        """The component's face through point_mm, in the component's own coordinates."""
        best = None
        for face, part in faces:
            rotation, shift = self._part_frame_in(comp, part)
            local = [sum(rotation[k][i] * (point_mm[k] - shift[k]) for k in range(3)) for i in range(3)]  # R^T
            nearest = face.GetClosestPointOn(*(mm_to_m(c) for c in local))
            gap = math.dist(local, [m_to_mm(c) for c in nearest[:3]])
            if best is None or gap < best[0]:
                best = (gap, face, part)
        gap, face, part = best
        if gap > self._ON_COMPONENT_FACE_MM:
            raise SolidWorksError(
                f"No face of '{comp.Name2}' goes through ({', '.join(f'{c:g}' for c in point_mm)}) "
                f"in its own coordinates: the nearest lies {gap:.3g} mm away."
            )
        return face, part

    def _face_plane_in_assembly(self, comp, face):
        """A planar component face as (point on its plane, normal) in ASSEMBLY
        coordinates, in metres.

        The face is reported in component coordinates, so both are pushed through
        the component transform: p' = R*p + t for the point, R*n for the normal
        (R is orthonormal here -- components are never scaled). The point is the
        plane's own root point: the box centre of a slanted face that is not
        symmetric lies off its plane (0.87 mm on a drafted wedge, measured).
        """
        data = self._transform_data(comp)
        rot, trans = data[:9], data[9:12]

        def rotate(v):
            # ArrayData is COLUMN-major: rot[3*col + row] is row `row` of column `col`.
            return [sum(rot[3 * col + row] * v[col] for col in range(3)) for row in range(3)]

        root = rotate(list(binding.wrap(face.GetSurface(), self._mod.ISurface).PlaneParams)[3:6])
        point = [root[i] + trans[i] for i in range(3)]
        return point, rotate(list(face.Normal))

    def _measure_mate(self, comp_a, face_a, comp_b, face_b) -> tuple:
        """(perpendicular distance mm, angle between normals deg) after a rebuild.

        The angle is 0..180 degrees: normals pointing the same way are 0 apart."""
        point_a, normal_a = self._face_plane_in_assembly(comp_a, face_a)
        point_b, normal_b = self._face_plane_in_assembly(comp_b, face_b)
        gap = abs(sum((point_b[i] - point_a[i]) * normal_a[i] for i in range(3)))
        dot = sum(normal_a[i] * normal_b[i] for i in range(3))
        return m_to_mm(gap), math.degrees(math.acos(max(-1.0, min(1.0, dot))))

    def _axis_in_assembly(self, comp, face):
        """A cylindrical component face's axis as (point, unit direction) in
        ASSEMBLY coordinates, in metres."""
        params = binding.wrap(face.GetSurface(), self._mod.ISurface).CylinderParams
        rotation, shift, scale = self._frame(comp)
        point = [scale * sum(rotation[row][i] * params[i] for i in range(3)) + shift[row] for row in range(3)]
        direction = [sum(rotation[row][i] * params[3 + i] for i in range(3)) for row in range(3)]
        length = math.hypot(*direction)
        return point, [d / length for d in direction]

    def _axes_apart(self, comp_a, face_a, comp_b, face_b) -> tuple:
        """(distance mm of b's axis from a's, angle deg between the axes) for two
        cylindrical faces: both 0 when they share one axis."""
        point_a, axis_a = self._axis_in_assembly(comp_a, face_a)
        point_b, axis_b = self._axis_in_assembly(comp_b, face_b)
        offset = [b - a for a, b in zip(point_a, point_b)]
        along = sum(o * d for o, d in zip(offset, axis_a))
        across = math.dist(offset, [along * d for d in axis_a])
        dot = abs(sum(a * b for a, b in zip(axis_a, axis_b)))
        return m_to_mm(across), math.degrees(math.acos(max(-1.0, min(1.0, dot))))

    def _check_mate_faces(self, key, faces):
        """Concentric takes cylinders, every other type planar faces."""
        for selector, comp, face in faces:
            surface = binding.wrap(face.GetSurface(), self._mod.ISurface)
            if key == "concentric" and not surface.IsCylinder():
                raise SolidWorksError(
                    f"A concentric mate takes cylindrical faces; {comp.Name2}:{selector} is not "
                    "one. list_faces(component=...) shows the cylinders with their index."
                )
            if key != "concentric" and not surface.IsPlane():
                raise SolidWorksError(f"A {key} mate takes planar faces; {comp.Name2}:{selector} is not planar.")

    def _mates(self) -> list:
        """The assembly's mates (the MateGroup's sub-features), in tree order."""
        return [
            mate
            for feat in self._iter_features()
            if feat.GetTypeName2() == "MateGroup"
            for mate in self._sub_features(feat)
        ]

    def _undo_mate(self, asm, mates_before: set, placements: list) -> None:
        """Delete the mates added since mates_before and put the components back,
        so a refused mate does not stay to fight the next attempt."""
        model = self._model
        extension = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        for mate in [m for m in self._mates() if m.Name not in mates_before]:
            model.ClearSelection2(True)
            if mate.Select2(False, 0):
                extension.DeleteSelection2(0)
        model.ClearSelection2(True)
        for comp, data in placements:
            comp.Transform2 = self._transform_from_data(data)
        asm.EditRebuild()

    def _transform_from_data(self, data):
        mathutil = binding.wrap(self._sw.GetMathUtility(), self._mod.IMathUtility)
        coords = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, list(data))
        return binding.wrap(mathutil.CreateTransform(coords), self._mod.IMathTransform)

    def _mate_problem(self, key, first, face_1, second, face_2, distance_mm, angle_deg) -> str | None:
        """Why the rebuilt mate does not hold what was asked, or None."""
        where = f"{first.Name2} and {second.Name2}"
        if key == "concentric":
            across_mm, tilt_deg = self._axes_apart(first, face_1, second, face_2)
            if across_mm > self._MATE_DISTANCE_TOLERANCE_MM or tilt_deg > self._MATE_ANGLE_TOLERANCE_DEG:
                return (
                    f"Mate 'concentric' was built but the axes of {where} are {across_mm:.4f} mm and "
                    f"{tilt_deg:.4f} degrees apart. Check whether another mate works against it."
                )
            return None
        measured_mm, measured_deg = self._measure_mate(first, face_1, second, face_2)
        expected_mm = {"distance": distance_mm, "coincident": 0.0}.get(key)
        if expected_mm is not None and abs(measured_mm - expected_mm) > self._MATE_DISTANCE_TOLERANCE_MM:
            return (
                f"Mate '{key}' was built but gives {measured_mm:.4f} mm instead of {expected_mm:g} mm "
                f"between {where}. Try flip=True, or check whether another mate works against it."
            )
        if key in self._MATE_EXPECTED_ANGLE_DEG:
            # parallel and perpendicular hold whichever way the normals point
            apart = min(measured_deg, 180.0 - measured_deg)
            if abs(apart - self._MATE_EXPECTED_ANGLE_DEG[key]) > self._MATE_ANGLE_TOLERANCE_DEG:
                return (
                    f"Mate '{key}' was built but the faces of {where} are {apart:.4f} degrees apart "
                    f"instead of {self._MATE_EXPECTED_ANGLE_DEG[key]:g}."
                )
        if key == "angle" and abs(measured_deg - angle_deg) > self._MATE_ANGLE_TOLERANCE_DEG:
            return (
                f"Mate 'angle' was built but the faces of {where} are {measured_deg:.4f} degrees apart "
                f"instead of {angle_deg:g}. Check whether another mate works against it."
            )
        return None

    def _mate_dimension(self, mate) -> str:
        """The name set_dimension takes for a distance or angle mate's value."""
        display = binding.wrap(binding.wrap(mate, self._mod.IMate2).DisplayDimension2(0), self._mod.IDisplayDimension)
        if display is None:
            raise SolidWorksError("The mate has no dimension to drive.")
        return binding.wrap(display.GetDimension2(0), self._mod.IDimension).GetNameForSelection()

    def add_mate(
        self,
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

        comp_a/comp_b are component names ('Bed' or 'Bed-1'); face_a/face_b are
        direction selectors in each component's OWN frame ('+x', '-z', or
        '+y:inner' for the cavity side of a hollow part), or a face index from
        list_faces(component=...) ('#5'). mate_type: 'coincident', 'distance'
        (distance_mm), 'parallel', 'perpendicular' or 'angle' (angle_deg, the
        angle between the faces' normals) between planar faces; 'concentric'
        between two cylindrical faces (a pin in a hole, a hinge), which leaves
        the turn about the axis free. flip takes the other solution: the
        mirror side of a distance, the other turning direction of an angle.

        A distance or angle mate returns its `dimension`, which set_dimension
        and check_motion drive: a joint angle as one number. After the rebuild
        the result is measured back from the geometry; a mate that does not
        hold what was asked is removed again and the components put back.
        """
        key = (mate_type or "").lower().strip()
        if key not in MATE_TYPES:
            raise SolidWorksError(f"Unknown mate type '{mate_type}'. Use one of: {sorted(MATE_TYPES)}.")
        if key == "distance" and distance_mm < 0:
            raise SolidWorksError(f"distance must be >= 0 (got {distance_mm}).")
        if key == "angle" and not 0.0 < angle_deg < 180.0:
            raise SolidWorksError(
                f"angle must be between 0 and 180 degrees (got {angle_deg}); 0 and 180 are a parallel mate."
            )
        if (comp_a or "").strip().lower() == (comp_b or "").strip().lower():
            raise SolidWorksError("A mate constrains two DIFFERENT components.")
        asm = self._require_assembly()
        model = self._model

        first = self._component_by_name(asm, comp_a)
        second = self._component_by_name(asm, comp_b)
        # a face in a sub-assembly lies on one of its parts, whose transform places it
        face_1, part_1 = self._component_face(first, face_a)
        face_2, part_2 = self._component_face(second, face_b)
        self._check_mate_faces(key, ((face_a, first, face_1), (face_b, second, face_2)))
        placements = [(comp, self._transform_data(comp)) for comp in (first, second)]
        mates_before = {m.Name for m in self._mates()}

        # Both mate entities go in with selection mark 1 (cracked empirically).
        model.ClearSelection2(True)
        selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
        select_data = selmgr.CreateSelectData()
        select_data.Mark = 1
        for entity, comp, selector in ((face_1, first, face_a), (face_2, second, face_b)):
            if not binding.wrap(entity, self._mod.IEntity).Select4(True, select_data):
                raise SolidWorksError(f"Could not select face {selector} of component '{comp.Name2}'.")

        distance_m = mm_to_m(distance_mm) if key == "distance" else 0.0
        angle_rad = math.radians(angle_deg) if key == "angle" else 0.0
        result = asm.AddMate5(
            MATE_TYPES[key],  # MateTypeFromEnum
            SW_MATE_ALIGN_CLOSEST,  # AlignFromEnum (components are pre-positioned)
            bool(flip),  # Flip
            distance_m,  # Distance
            distance_m,
            distance_m,  # DistanceAbsUpperLimit, DistanceAbsLowerLimit
            1.0,
            1.0,  # GearRatioNumerator, GearRatioDenominator
            angle_rad,  # Angle
            angle_rad,
            angle_rad,  # AngleAbsUpperLimit, AngleAbsLowerLimit
            False,  # ForPositioningOnly
            False,  # LockRotation
            0,  # WidthMateOption
            0,  # ErrorStatus (out)
        )
        model.ClearSelection2(True)
        mate, status = (result[0], result[-1]) if isinstance(result, tuple) else (result, None)
        if mate is None or (status is not None and int(status) != SW_ADD_MATE_NO_ERROR):
            # An over-defining mate is added all the same, in error, and flags the
            # mates it fights (verified), so name those before it goes again.
            fought = [m.Name for m in self._mates() if m.Name in mates_before and m.GetErrorCode2()[0]]
            self._undo_mate(asm, mates_before, placements)
            raise SolidWorksError(
                f"Mate '{key}' between {first.Name2}:{face_a} and {second.Name2}:{face_b} "
                f"failed (AddMate5 status {status}). "
                + (
                    f"It contradicts {', '.join(fought)}."
                    if fought
                    else "Are the faces in a position that allows this mate, without contradicting existing mates?"
                )
            )

        asm.EditRebuild()
        problem = self._mate_problem(key, part_1, face_1, part_2, face_2, distance_mm, angle_deg)
        if problem:
            self._undo_mate(asm, mates_before, placements)
            raise SolidWorksError(problem)
        entry = {
            "ok": True,
            "mate": next((m.Name for m in self._mates() if m.Name not in mates_before), None),
            "mate_type": key,
            "components": [first.Name2, second.Name2],
            "faces": [face_a, face_b],
            "placements": {c.Name2: self._placement(c) for c in (first, second)},
        }
        if key == "concentric":
            entry["axis_offset_mm"] = round(self._axes_apart(part_1, face_1, part_2, face_2)[0], 6)
        else:
            measured_mm, measured_deg = self._measure_mate(part_1, face_1, part_2, face_2)
            entry.update(distance_mm=round(measured_mm, 6), angle_deg=round(measured_deg, 6))
        if key in ("distance", "angle"):
            entry["dimension"] = self._mate_dimension(mate)
        return entry
