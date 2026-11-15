"""Reading and building on sketches authored by a person.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    SKETCH_STATUSES,
    SW_END_COND_BLIND,
    SW_END_COND_THROUGH_ALL,
    SW_FULLY_CONSTRAINED,
    SW_SEL_FACES,
    SW_SKETCH_ARC,
    SW_SKETCH_LINE,
    SW_SKETCH_SPLINE,
    SW_SKETCH_TEXT,
    SW_START_SKETCH_PLANE,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m
from ._decorators import _reads_only


class PersonSketchMixin:
    """Reading and building on sketches authored by a person."""

    def _sketch_by_name(self, name: str):
        """A sketch of the current part by name, also one absorbed by a feature."""
        self._require_part()
        sketches = [
            candidate
            for feat in self._iter_features()
            for candidate in [feat, *self._sub_features(feat)]
            if candidate.GetTypeName2() == "ProfileFeature"
        ]
        for sketch in sketches:
            if sketch.Name == name:
                return sketch
        names = sorted({s.Name for s in sketches})
        raise SolidWorksError(f"No sketch '{name}' in the part (there are: {', '.join(names) or 'none'}).")

    @_reads_only
    def read_sketch(self, name: str) -> dict:
        """A sketch of the current part read back in MODEL coordinates (mm): its
        lines, arcs, circles and splines (construction ones marked), its
        dimensions, and whether it is fully defined. For checking a design
        against fixed points before building on it.
        """
        feature = self._sketch_by_name(name)
        sketch = binding.wrap(feature.GetSpecificFeature2(), self._mod.ISketch)
        to_model = binding.wrap(
            binding.wrap(sketch.ModelToSketchTransform, self._mod.IMathTransform).Inverse(), self._mod.IMathTransform
        )
        segments = [self._segment_entry(s, to_model) for s in sketch.GetSketchSegments() or ()]
        status = sketch.GetConstrainedStatus()
        return {
            "ok": True,
            "name": feature.Name,
            "fully_defined": status == SW_FULLY_CONSTRAINED,
            "status": SKETCH_STATUSES.get(status, f"status {status}"),
            "segments": segments,
            "dimensions": self._dimension_entries(feature),
        }

    def _segment_entry(self, segment_dispatch, to_model) -> dict:
        segment = binding.wrap(segment_dispatch, self._mod.ISketchSegment)
        kind = segment.GetType()
        entry = {"construction": bool(segment.ConstructionGeometry)}

        def point(dispatch):
            p = binding.wrap(dispatch, self._mod.ISketchPoint)
            return self._to_model_mm(to_model, p.X, p.Y, p.Z)

        if kind == SW_SKETCH_LINE:
            line = binding.wrap(segment_dispatch, self._mod.ISketchLine)
            entry.update(type="line", start_mm=point(line.GetStartPoint2()), end_mm=point(line.GetEndPoint2()))
        elif kind == SW_SKETCH_ARC:
            arc = binding.wrap(segment_dispatch, self._mod.ISketchArc)
            circle = bool(arc.IsCircle())
            entry.update(
                type="circle" if circle else "arc",
                centre_mm=point(arc.GetCenterPoint2()),
                radius_mm=round(m_to_mm(arc.GetRadius()), 4),
            )
            if not circle:
                entry.update(start_mm=point(arc.GetStartPoint2()), end_mm=point(arc.GetEndPoint2()))
        else:
            names = {SW_SKETCH_SPLINE: "spline", SW_SKETCH_TEXT: "text"}
            entry.update(type=names.get(kind, f"segment type {kind}"), length_mm=round(m_to_mm(segment.GetLength()), 4))
        return entry

    def _to_model_mm(self, transform, x_m, y_m, z_m) -> list:
        mathutil = binding.wrap(self._sw.GetMathUtility(), self._mod.IMathUtility)
        coords = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x_m, y_m, z_m])
        moved = binding.wrap(
            binding.wrap(mathutil.CreatePoint(coords), self._mod.IMathPoint).MultiplyTransform(transform),
            self._mod.IMathPoint,
        )
        return [round(m_to_mm(c), 4) + 0.0 for c in moved.ArrayData]

    def extrude_sketch(
        self,
        sketch: str,
        depth_mm: float | None = None,
        reverse: bool = False,
        name: str = "Extrude",
        up_to: str | None = None,
    ) -> dict:
        """Extrude an existing sketch of the current part, by name (one a person
        drew), depth_mm along its normal (reverse=True: the other way), merged
        with the body; or with up_to='next' up to the next face of the part,
        ending on its shape, such as a post into a curved wall, and following
        it when the wall changes; or with up_to='@x,y,z' up to the face through
        that point. The sketch's own dimensions come back."""
        if depth_mm is not None and up_to is not None:
            raise SolidWorksError("Give depth_mm or up_to, not both.")
        if depth_mm is None and up_to is None:
            raise SolidWorksError("extrude_sketch needs depth_mm or up_to='next'.")
        if up_to is not None and up_to != "next" and not str(up_to).strip().startswith("@"):
            raise SolidWorksError(
                f"Unknown up_to '{up_to}'. Use 'next': up to the next face of the part, or "
                "'@x,y,z': up to the face through that point."
            )
        if depth_mm is not None and depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        end_face = self._part_face_at(self._point_selector(up_to)) if up_to not in (None, "next") else None
        defined = self._select_person_sketch(sketch)
        hint = (
            f"Is '{sketch}' a closed profile?"
            if up_to is None
            else (
                f"Is '{sketch}' a closed profile with {'that face' if end_face else 'a face of the part'} ahead of it"
                f"{'' if reverse else ' (or behind it: reverse=True)'}?"
            )
        )
        try:
            return self._extrude_sketch(depth_mm, name, defined, hint, reverse=reverse, end_face=end_face)
        except SolidWorksError as exc:
            if up_to != "next":
                raise
            ahead = self._face_ahead(sketch, reverse)
            if ahead is None:
                raise
            # a side of the profile on a face of the part (a strip against a boss) fails 'next' alone
            raise SolidWorksError(
                f"{exc} Up to next also fails when a side of the profile lies on a face of the "
                f"part. The face ahead of the profile's middle: up_to='@{ahead}' ends on it."
            ) from exc

    def _face_ahead(self, sketch_name: str, reverse: bool) -> str | None:
        """Where a ray from the middle of the sketch, along its extrusion,
        first meets the part: 'x,y,z' in mm for up_to, or None."""
        sketch = binding.wrap(self._sketch_by_name(sketch_name).GetSpecificFeature2(), self._mod.ISketch)
        to_model = binding.wrap(
            binding.wrap(sketch.ModelToSketchTransform, self._mod.IMathTransform).Inverse(), self._mod.IMathTransform
        )
        origin = self._to_model_mm(to_model, 0.0, 0.0, 0.0)
        normal = [
            (c - o) * (-1 if reverse else 1) for c, o in zip(self._to_model_mm(to_model, 0.0, 0.0, 0.001), origin)
        ]
        corners = [
            s["start_mm"]
            for s in self.read_sketch(sketch_name)["segments"]
            if "start_mm" in s and not s["construction"]
        ]
        if not corners:
            return None
        middle = [sum(c[i] for c in corners) / len(corners) for i in range(3)]
        model = self._model
        model.ClearSelection2(True)
        extension = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        try:
            if not extension.SelectByRay(
                *(mm_to_m(c) for c in middle), *normal, mm_to_m(self._ON_FACE_TOLERANCE_MM), SW_SEL_FACES, False, 0, 0
            ):
                return None
            hit = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr).GetSelectionPoint2(1, -1)
            return ",".join(f"{m_to_mm(c):.3f}" for c in hit[:3])  # well within the 0.01 mm a face is found by
        finally:
            model.ClearSelection2(True)

    def _part_face_at(self, point_mm: list):
        """The current part's face through point_mm."""

        def gap(face) -> float:
            nearest = face.GetClosestPointOn(*(mm_to_m(c) for c in point_mm))
            return math.dist(point_mm, [m_to_mm(c) for c in nearest[:3]])

        faces = [binding.wrap(f, self._mod.IFace2) for body in self._part_bodies() for f in body.GetFaces() or ()]
        face = min(faces, key=gap)
        if gap(face) > self._ON_COMPONENT_FACE_MM:
            raise SolidWorksError(
                f"No face of the part goes through ({', '.join(f'{c:g}' for c in point_mm)}): "
                f"the nearest lies {gap(face):.3g} mm away."
            )
        return face

    def cut_sketch(self, sketch: str, depth_mm: float | None = None, reverse: bool = False, name: str = "Cut") -> dict:
        """Cut an existing sketch of the current part, by name, into the body:
        depth_mm deep, or through all when depth_mm is None, against the
        sketch's normal (FeatureCut4's own direction, verified): into the part
        from a face. reverse=True cuts along the normal, as needed from a plane
        with the part in front of it."""
        if depth_mm is not None and depth_mm <= 0:
            raise SolidWorksError(f"depth must be > 0 (got {depth_mm}).")
        model = self._require_model()
        defined = self._select_person_sketch(sketch)
        t1, d1 = (SW_END_COND_THROUGH_ALL, 0.0) if depth_mm is None else (SW_END_COND_BLIND, mm_to_m(depth_mm))
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        cut = feat_mgr.FeatureCut4(
            True,
            False,
            reverse,
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
            raise SolidWorksError(
                f"FeatureCut4 failed (None). Is '{sketch}' a closed profile that meets the part"
                f"{'' if reverse else ' (or does it need reverse=True)'}?"
            )
        return self._with_depth(self._finish_feature(cut, name, **defined), depth_mm)

    def _select_person_sketch(self, name: str) -> dict:
        """Select a sketch by name for a feature; its dimensions and definition state."""
        feature = self._sketch_by_name(name)
        self._model.ClearSelection2(True)
        if not feature.Select2(False, 0):
            raise SolidWorksError(f"Could not select the sketch '{name}'.")
        dims = {entry["name"].split("@")[0]: entry["name"] for entry in self._dimension_entries(feature)}
        status = binding.wrap(feature.GetSpecificFeature2(), self._mod.ISketch).GetConstrainedStatus()
        return {"dimensions": dims, "fully_defined": status == SW_FULLY_CONSTRAINED}
