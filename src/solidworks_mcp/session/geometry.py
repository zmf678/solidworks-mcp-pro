"""Default planes, face/edge selection and the shared extrude helper.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import itertools
import math
import re

import pythoncom

from .. import binding
from ..constants import (
    SW_BODY_SOLID,
    SW_END_COND_BLIND,
    SW_END_COND_UP_TO_NEXT,
    SW_END_COND_UP_TO_SURFACE,
    SW_START_SKETCH_PLANE,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m


class GeometryMixin:
    """Default planes, face/edge selection and the shared extrude helper."""

    def _first_ref_plane(self):
        """The Front plane, where new geometry starts (see _default_plane)."""
        return self._default_plane("front")

    def _default_plane(self, key: str):
        """The default plane 'front' / 'top' / 'right' by where it lies: through
        the origin, with the axes the sketches on it are drawn in. Not by name,
        which changes with the language, nor by place in the tree: a template
        held another plane first, and every part came out turned."""
        axes = self._DEFAULT_PLANE_AXES[key]
        planes = self._ref_planes()
        transforms = []
        for feat in planes:
            transforms.append(self._plane_transform(feat))
            if self._lies_along(transforms[-1], axes):
                return feat
        if any(self._lies_along(data, self._Z_UP_FRONT_AXES) for data in transforms):
            raise SolidWorksError(
                "This part comes from a Z-up part template (an option since SolidWorks 2025): "
                "its Front, Top and Right planes are turned, and the tools build in SolidWorks' "
                "standard Y-up frame. Make new parts Y-up: make a part with Y-up chosen in the "
                "New Document dialog, save it as a part template (.prtdot), and set that file "
                "as the part template under Tools > Options > System Options > Default "
                "Templates. Choosing Y-up in the dialog alone is not used for parts made "
                "through the API."
            )
        raise SolidWorksError(
            f"The part has no {key} plane: none of {', '.join(f.Name for f in planes)} lies "
            f"through the origin facing {axes[2]}. Is its template unusual?"
        )

    @staticmethod
    def _lies_along(data, axes) -> bool:
        """Whether a plane with Transform `data` runs through the origin with these axes."""
        through_origin = abs(sum(o * n for o, n in zip(data[9:12], data[6:9]))) < 1e-9
        return through_origin and all(abs(a - b) < 1e-9 for a, b in zip(data[:9], itertools.chain(*axes)))

    def _plane_transform(self, feat) -> tuple:
        """A reference plane's IRefPlane.Transform: x axis, y axis, normal, origin (metres)."""
        return binding.wrap(
            binding.wrap(feat.GetSpecificFeature2(), self._mod.IRefPlane).Transform, self._mod.IMathTransform
        ).ArrayData

    def _solid_body(self):
        """The first solid body of the current part (early-bound IBody2)."""
        part = self._require_part()
        bodies = part.GetBodies2(SW_BODY_SOLID, True)
        if not bodies:
            raise SolidWorksError("No solid body; build geometry first (e.g. add_box).")
        if not isinstance(bodies, (list, tuple)):
            bodies = [bodies]
        return binding.wrap(bodies[0], self._mod.IBody2)

    def _planar_faces_facing(self, faces, target) -> list:
        """(IFace2, position_mm along `target`) of every PLANAR face facing `target`.

        Non-planar faces (a cylinder left by a hole, a fillet surface) are skipped
        so every result is a valid sketch base.
        """
        tx, ty, tz = target
        found = []
        for face_dispatch in faces:
            face = binding.wrap(face_dispatch, self._mod.IFace2)
            surface = binding.wrap(face.GetSurface(), self._mod.ISurface)
            if surface is None or not surface.IsPlane():
                continue  # only sketch on flat faces
            nx, ny, nz = face.Normal
            if nx * tx + ny * ty + nz * tz < 0.999:  # ~2.6 degrees
                continue
            box = face.GetBox()  # planar face -> its box centre lies in the plane
            found.append((face, m_to_mm(sum((box[i] + box[i + 3]) / 2.0 * target[i] for i in range(3)))))
        return found

    def _pick_planar_face(self, faces, target, side: str):
        """Extreme PLANAR face along `target`: 'outer' = max, 'inner' = min position.

        Returns (IFace2, position_mm along `target`) or (None, None) if no planar
        face faces that way.
        """
        if side not in self._FACE_SIDES:
            raise SolidWorksError(f"Unknown face side '{side}'. Use 'outer' or 'inner'.")
        facing = self._planar_faces_facing(faces, target)
        if not facing:
            return None, None
        return (max if side == "outer" else min)(facing, key=lambda fp: fp[1])

    def _body_faces(self, body) -> list:
        faces = body.GetFaces()
        if not faces:
            return []
        return list(faces) if isinstance(faces, (list, tuple)) else [faces]

    def _planar_face_by_normal(self, body, target, side: str = "outer"):
        """The body's outermost (default) or innermost planar face facing `target`."""
        faces = self._body_faces(body)
        return self._pick_planar_face(faces, target, side)[0] if faces else None

    def _select_face_through(self, body, normal, side, point_mm, label: str):
        """Select the planar face facing `normal` that the 3D point lies on.

        A face selector with an explicit ':outer'/':inner' side keeps picking that
        extreme face; without one the point decides, so a pocket floor or a step
        between the outermost and innermost face can be sketched on too.
        """
        if side is not None:
            return self._select_planar_face(body, normal, label, side)
        position = sum(p * n for p, n in zip(point_mm, normal))
        facing = self._planar_faces_facing(self._body_faces(body), normal)
        at_level = [f for f, pos in facing if abs(pos - position) <= self._ON_FACE_TOLERANCE_MM]
        # faces at one height (a top split by a slot): the one the point is on
        face = min(at_level, key=lambda f: self._off_face_mm(f, point_mm), default=None)
        if face is None:
            levels = ", ".join(f"{pos:g}" for pos in sorted({round(pos, 6) for _, pos in facing})) or "none"
            raise SolidWorksError(
                f"No planar {label} face through ({', '.join(f'{c:g}' for c in point_mm)}) mm: the faces "
                f"facing that way lie at {levels} mm along it. Give a point on one of them."
            )
        self._model.ClearSelection2(True)
        if not binding.wrap(face, self._mod.IEntity).Select4(False, None):
            raise SolidWorksError(f"Could not select the {label} face.")
        return face

    def _off_face_mm(self, face, point_mm) -> float:
        """How far the 3D point lies from the face: 0 on it, more beyond its edge
        or over an opening in it, such as a hole."""
        nearest = face.GetClosestPointOn(*(mm_to_m(c) for c in point_mm))
        if not nearest or len(nearest) < 3:
            raise SolidWorksError("SolidWorks found no nearest point on the face.")
        return math.dist(point_mm, [m_to_mm(c) for c in nearest[:3]])

    def _parse_direction(self, token: str):
        """'+z'/'-x'/... -> a unit vector tuple. Raises on an unknown token."""
        key = (token or "").lower().strip()
        if key not in self._DIRECTIONS:
            raise SolidWorksError(f"Unknown direction '{token}'. Use +x/-x/+y/-y/+z/-z.")
        return self._DIRECTIONS[key]

    @staticmethod
    def _face_index(selector) -> int | None:
        """'#5' or '5' -> 5, a face by its list_faces index; a direction -> None."""
        text = str(selector).strip()
        digits = text[1:] if text.startswith("#") else text
        return int(digits) if digits.isdigit() else None

    def _parse_face_selector(self, token: str, default_side: str | None = "outer"):
        """'+z' or '+z:inner' -> ((0,0,1), 'outer'|'inner'); pure, unit-tested.

        The optional ':inner' suffix asks for the cavity-side face instead of the
        outside skin, where several faces share the same normal (a shelled box, a
        room). Without a suffix the side is `default_side`; tools that get a point
        on the face pass None and let the point pick the face.
        """
        text = (token or "").lower().strip()
        direction, _, side = text.partition(":")
        side = side.strip() or default_side
        if side is None:
            return self._parse_direction(direction), None
        if side not in self._FACE_SIDES:
            raise SolidWorksError(f"Unknown face side ':{side}' in '{token}'. Use ':outer' (default) or ':inner'.")
        return self._parse_direction(direction), side

    def _edge_parallel_to(self, edge_dispatch, target) -> bool:
        """True if a STRAIGHT edge runs parallel to unit vector `target`.

        Requires the edge's underlying curve to be a line, so arcs left by a
        fillet/chamfer (open arcs that DO have two vertices) and a hole's circle
        are never matched, then compares the line direction against `target`.
        """
        edge = binding.wrap(edge_dispatch, self._mod.IEdge)
        curve = binding.wrap(edge.GetCurve(), self._mod.ICurve)
        if curve is None or not curve.IsLine():
            return False
        start = edge.GetStartVertex()
        end = edge.GetEndVertex()
        if start is None or end is None:
            return False
        p1 = binding.wrap(start, self._mod.IVertex).GetPoint()
        p2 = binding.wrap(end, self._mod.IVertex).GetPoint()
        dx, dy, dz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
        length = (dx * dx + dy * dy + dz * dz) ** 0.5
        if length < 1e-9:
            return False
        dot = abs(dx * target[0] + dy * target[1] + dz * target[2]) / length
        return dot > 0.999  # ~2.6 degrees

    @staticmethod
    def _parse_edge_indices(selector):
        """Return a list of int indices if `selector` denotes indices, else None.

        Accepts a list/tuple of ints, or a string like '2,5' / '2 5'.
        """
        if isinstance(selector, (list, tuple)):
            return [int(i) for i in selector]
        text = str(selector).strip()
        if text and any(c.isdigit() for c in text) and all(c.isdigit() or c in ", " for c in text):
            return [int(p) for p in text.replace(",", " ").split()]
        return None

    def _select_edges(self, body, selector="all") -> int:
        """Append-select body edges matching `selector`; return how many.

        selector: 'all' = every edge; 'x'|'y'|'z' = straight edges parallel to
        that world axis (for an add_box block, 'z' is the depth edges); a face
        outline like '+z:outline' (see _select_outline); or explicit indices as
        [2, 5] or '2,5' (into list_edges order).
        """
        edges = body.GetEdges()
        if not edges:
            return 0
        if not isinstance(edges, (list, tuple)):
            edges = [edges]
        self._model.ClearSelection2(True)
        count = 0

        indices = self._parse_edge_indices(selector)
        if indices is not None:
            for idx in indices:
                if idx < 0 or idx >= len(edges):
                    raise SolidWorksError(f"Edge index {idx} is out of range (0..{len(edges) - 1}).")
                if binding.wrap(edges[idx], self._mod.IEntity).Select4(True, None):
                    count += 1
            return count

        feature = re.fullmatch(r"feature:(.+)", str(selector).strip(), re.IGNORECASE)
        if feature:
            return self._select_feature_edges(feature.group(1).strip())
        sel = str(selector).lower().replace(" ", "")
        outline = re.fullmatch(r"([+-][xyz]):outline", sel)
        if outline:
            return self._select_outline(body, outline.group(1))
        if sel != "all" and sel not in self._EDGE_AXES:
            raise SolidWorksError(
                f"Unknown edge selector '{selector}'. Use 'all', 'x'/'y'/'z', a face outline like "
                "'+z:outline', a feature's edges like 'feature:Boss', or indices like '2,5'."
            )
        target = self._EDGE_AXES.get(sel)
        for edge_dispatch in edges:
            if target is not None and not self._edge_parallel_to(edge_dispatch, target):
                continue
            if binding.wrap(edge_dispatch, self._mod.IEntity).Select4(True, None):
                count += 1
        return count

    def _select_feature_edges(self, name: str) -> int:
        """Append-select every edge of the faces feature `name` made: rounding them
        all at once gives a boss or a rib the soft look of a moulded part."""
        feature = self._history_feature(name)
        extension = binding.wrap(self._model.Extension, self._mod.IModelDocExtension)
        seen, count = set(), 0
        for face in feature.GetFaces() or ():
            for edge in binding.wrap(face, self._mod.IFace2).GetEdges() or ():
                key = bytes(extension.GetPersistReference3(edge))  # one edge, two faces: select it once
                if key in seen:
                    continue
                seen.add(key)
                if binding.wrap(edge, self._mod.IEntity).Select4(True, None):
                    count += 1
        if not count:
            raise SolidWorksError(f"Feature '{name}' has no edges to round.")
        return count

    def _select_outline(self, body, direction: str) -> int:
        """Select the outer loop of the outermost planar face facing `direction`:
        its outline, without the edges of holes and pockets inside it."""
        face = self._planar_face_by_normal(body, self._parse_direction(direction), "outer")
        if face is None:
            raise SolidWorksError(f"No planar {direction} face to take the outline of.")
        loops = [binding.wrap(loop, self._mod.ILoop2) for loop in binding.wrap(face, self._mod.IFace2).GetLoops() or ()]
        outer = next((loop for loop in loops if loop.IsOuter()), None)
        if outer is None:
            raise SolidWorksError(f"The {direction} face has no outer loop.")
        count = 0
        for edge in outer.GetEdges() or ():
            if binding.wrap(edge, self._mod.IEntity).Select4(True, None):
                count += 1
        return count

    def _finish_feature(self, feature, name: str, **extra) -> dict:
        """Name a freshly created feature, rebuild, and build the result dict.

        Shared tail for the feature builders. `rebuild_ok` mirrors set_dimension
        so the agent can tell when a feature was created but the rebuild failed.
        """
        try:
            feature.Name = name
        except pythoncom.com_error:
            pass  # naming is best-effort; we read the real name back below
        rebuilt_ok = bool(self._model.ForceRebuild3(False))
        return {
            "ok": True,
            "feature": feature.Name,
            "rebuild_ok": rebuilt_ok,
            **extra,
            "mass_properties": self.get_mass_properties()["mass_properties"],
        }

    @staticmethod
    def _with_depth(result: dict, depth_mm) -> dict:
        """Name a blind cut's depth among its dimensions; a through-all cut has none."""
        if depth_mm is not None:
            result["dimensions"]["depth"] = f"D1@{result['feature']}"
        return result

    def _extrude_sketch(
        self,
        depth_mm: float | None,
        name: str,
        sketch: dict,
        hint: str = "",
        role: str = "depth",
        reverse: bool = False,
        draft_deg: float = 0.0,
        merge: bool = True,
        end_face=None,
    ) -> dict:
        """Extrude the sketch just closed (it stays selected) depth_mm along its
        normal (reverse: the other way), merged with the body; finish the
        feature and name its depth. depth_mm None runs up to the next face of
        the part instead, or up to end_face when given, ending on its shape,
        with no depth to name.

        Shared by every boss. `sketch` is the _define_sketch result, `role` the
        depth's name among the dimensions, `hint` what to check when it fails.
        draft_deg tapers the walls inwards as they rise (negative: outwards) and
        is named 'draft'; merge=False keeps the result a body of its own, named
        in the result's 'body'.
        """
        bodies_before = {body.Name for body in self._part_bodies()}
        feat_mgr = binding.wrap(self._model.FeatureManager, self._mod.IFeatureManager)
        up_to_next = depth_mm is None
        if end_face is not None:
            data = binding.wrap(
                binding.wrap(self._model.SelectionManager, self._mod.ISelectionMgr).CreateSelectData(),
                self._mod.ISelectData,
            )
            data.Mark = 1
            if not binding.wrap(end_face, self._mod.IEntity).Select4(True, data):
                raise SolidWorksError("Could not select the face to extrude up to.")
        end = SW_END_COND_BLIND if not up_to_next else SW_END_COND_UP_TO_SURFACE if end_face else SW_END_COND_UP_TO_NEXT
        extrude = feat_mgr.FeatureExtrusion3(
            True,
            False,
            reverse,  # Sd (single dir), Flip, Dir
            end,
            0,  # T1, T2 (end conditions)
            0.0 if up_to_next else mm_to_m(depth_mm),
            0.0,  # D1 (depth), D2
            bool(draft_deg),
            False,  # Dchk1 (draft), Dchk2
            draft_deg < 0,
            False,  # Ddir1 (outward), Ddir2
            math.radians(abs(draft_deg)),
            0.0,  # Dang1, Dang2 (draft, radians)
            False,
            False,  # OffsetReverse1, OffsetReverse2
            False,
            False,  # TranslateSurface1, TranslateSurface2
            bool(merge),  # Merge
            True,  # UseFeatScope
            True,  # UseAutoSelect
            SW_START_SKETCH_PLANE,  # T0 (start condition)
            0.0,  # StartOffset
            False,  # FlipStartOffset
        )
        if extrude is None:
            raise SolidWorksError(f"FeatureExtrusion3 failed (None). {hint}".strip())
        result = self._finish_feature(extrude, name, **sketch)
        if not up_to_next:
            result["dimensions"][role] = f"D1@{result['feature']}"
        if draft_deg:
            feature = binding.wrap(extrude, self._mod.IFeature)
            result["dimensions"]["draft"] = next(
                d["name"] for d in self._dimension_entries(feature) if d["unit"] == "deg"
            )
        if not merge:
            [result["body"]] = [body.Name for body in self._part_bodies() if body.Name not in bodies_before]
        return result
