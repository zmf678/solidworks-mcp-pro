"""Linear/circular patterns and reference planes.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

from .. import binding
from ..constants import (
    SW_REF_PLANE_ANGLE,
    SW_REF_PLANE_COINCIDENT,
    SW_REF_PLANE_DISTANCE,
    SW_REF_PLANE_FLIP,
)
from ..errors import SolidWorksError
from ..units import deg_to_rad, m_to_mm, mm_to_m


class PatternsPlanesMixin:
    """Linear/circular patterns and reference planes."""

    def add_linear_pattern(
        self, count: int, spacing_mm: float, direction: str = "+x", feature_name: str | None = None
    ) -> dict:
        """Repeat a feature `count` times, `spacing_mm` apart, along a direction.

        direction: '+x'/'-x'/'+y'/... (a body edge parallel to that axis sets the
        direction; flip is chosen so the pattern runs the requested way).
        feature_name: the feature to repeat (e.g. 'Hole'); defaults to the most
        recently added feature. Selection marks: direction edge = 1, seed = 4.
        """
        model = self._require_model()
        if count < 2:
            raise SolidWorksError(f"count must be >= 2 (got {count}).")
        if spacing_mm <= 0:
            raise SolidWorksError(f"spacing must be > 0 (got {spacing_mm}).")

        dvec = self._parse_direction(direction)
        body = self._solid_body()
        p1, p2, edge_dispatch = self._first_edge_along(body, dvec)
        if p1 is None:
            raise SolidWorksError(f"No straight edge parallel to {direction} found.")
        along = (p2[0] - p1[0]) * dvec[0] + (p2[1] - p1[1]) * dvec[1] + (p2[2] - p1[2]) * dvec[2]
        flip = along < 0  # pattern follows the edge's p1->p2 dir; flip to match `direction`

        seed = feature_name or self._last_feature_name()
        selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
        model.ClearSelection2(True)
        select_data = binding.wrap(selmgr.CreateSelectData(), self._mod.ISelectData)
        select_data.Mark = 1
        if not binding.wrap(edge_dispatch, self._mod.IEntity).Select4(False, select_data):
            raise SolidWorksError("Could not select the direction edge.")
        ext = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        if not ext.SelectByID2(seed, "BODYFEATURE", 0.0, 0.0, 0.0, True, 4, None, 0):
            raise SolidWorksError(f"Could not select the seed feature '{seed}'.")

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        pattern = feat_mgr.FeatureLinearPattern(count, mm_to_m(spacing_mm), 1, 0.0, flip, False, "", "")
        if pattern is None:
            raise SolidWorksError("FeatureLinearPattern failed (None). Do all instances fit on the part?")
        return self._finish_feature(pattern, "LinearPattern", instances=count, seed=seed, direction=direction)

    def _cylindrical_face_near(self, body, cx_mm, cy_mm):
        """Raw dispatch of the CYLINDRICAL face whose bbox-centre (x,y) is nearest
        (cx,cy) and within tolerance, else None.

        Verifies the surface is actually a cylinder (not a cone/fillet/sphere) and
        applies a distance floor, mirroring the rigour of _planar_face_by_normal.
        """
        faces = body.GetFaces()
        if not faces:
            return None
        if not isinstance(faces, (list, tuple)):
            faces = [faces]
        best, best_d = None, None
        for face_dispatch in faces:
            face = binding.wrap(face_dispatch, self._mod.IFace2)
            surface = binding.wrap(face.GetSurface(), self._mod.ISurface)
            if surface is None or not surface.IsCylinder():
                continue
            box = face.GetBox()
            if not box or len(box) < 6:
                continue
            ccx = m_to_mm((box[0] + box[3]) / 2)
            ccy = m_to_mm((box[1] + box[4]) / 2)
            d = (ccx - cx_mm) ** 2 + (ccy - cy_mm) ** 2
            if best_d is None or d < best_d:
                best_d, best = d, face_dispatch
        if best is None or best_d > self._CYL_AXIS_TOLERANCE_MM**2:
            return None
        return best

    def add_circular_pattern(
        self, count: int, center_x_mm: float, center_y_mm: float, feature_name: str | None = None
    ) -> dict:
        """Repeat a feature `count` times evenly around 360 deg about an axis.

        The axis is the cylindrical face nearest (center_x_mm, center_y_mm) -- e.g.
        a centre hole drilled there. feature_name defaults to the last feature.
        A bolt circle: drill a centre hole + one bolt hole, then pattern the bolt
        hole. Selection marks: axis face = 1, seed feature = 4; the per-instance
        angle is 360/count degrees.
        """
        model = self._require_model()
        if count < 2:
            raise SolidWorksError(f"count must be >= 2 (got {count}).")

        body = self._solid_body()
        face = self._cylindrical_face_near(body, center_x_mm, center_y_mm)
        if face is None:
            raise SolidWorksError(
                f"No cylindrical face found at ({center_x_mm}, {center_y_mm}) to use as the axis. "
                "Drill a centre hole there first."
            )
        seed = feature_name or self._last_feature_name()
        selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
        model.ClearSelection2(True)
        select_data = binding.wrap(selmgr.CreateSelectData(), self._mod.ISelectData)
        select_data.Mark = 1
        if not binding.wrap(face, self._mod.IEntity).Select4(True, select_data):
            raise SolidWorksError("Could not select the axis face.")
        ext = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        if not ext.SelectByID2(seed, "BODYFEATURE", 0.0, 0.0, 0.0, True, 4, None, 0):
            raise SolidWorksError(f"Could not select the seed feature '{seed}'.")

        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        pattern = feat_mgr.FeatureCircularPattern(count, deg_to_rad(360.0) / count, False, "")
        if pattern is None:
            raise SolidWorksError("FeatureCircularPattern failed (None).")
        return self._finish_feature(
            pattern, "CircularPattern", instances=count, seed=seed, center_mm=[center_x_mm, center_y_mm]
        )

    def _named_plane(self, plane: str):
        """A reference plane: 'front' / 'top' / 'right' (the default planes, in
        any template language) or the name of a plane in the tree, such as one a
        person made. Returns (plane, label)."""
        key = str(plane).lower()
        if key in self._DEFAULT_PLANE_AXES:
            return self._default_plane(key), f"{key} plane"
        planes = self._ref_planes()
        named = [p for p in planes if p.Name == plane] or [p for p in planes if p.Name.lower() == key]
        if len(named) != 1:
            raise SolidWorksError(
                f"No plane '{plane}'. Use 'front', 'top', 'right' or a plane of the part: "
                f"{', '.join(p.Name for p in planes)}."
            )
        return named[0], f"plane '{named[0].Name}'"

    def _plane_at(self, plane: str, offset_mm: float):
        """The plane `plane` (see _named_plane), or a new plane parallel to it
        offset_mm along its normal (negative: the other way). Returns (plane, created)."""
        model = self._require_model()
        base, label = self._named_plane(plane)
        if offset_mm == 0:
            return base, False
        model.ClearSelection2(True)
        if not base.Select2(False, 0):
            raise SolidWorksError(f"Could not select the {label}.")
        constraint = SW_REF_PLANE_DISTANCE | (SW_REF_PLANE_FLIP if offset_mm < 0 else 0)
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        if feat_mgr.InsertRefPlane(constraint, mm_to_m(abs(offset_mm)), 0, 0.0, 0, 0.0) is None:
            raise SolidWorksError(f"Could not create a plane {offset_mm:g} mm from the {label}.")
        # InsertRefPlane's return is a generic dispatch without Select2; take the
        # new plane from the tree instead.
        return self._last_ref_plane(), True

    def add_plane(
        self,
        base: str = "front",
        offset_mm: float = 0.0,
        angle_deg: float = 0.0,
        about: str | None = None,
        name: str | None = None,
    ) -> dict:
        """A reference plane to build on, its position a dimension.

        Either `base` (front/top/right or a plane by name) moved offset_mm along
        its normal, or a default plane turned angle_deg about the model axis
        `about` that it holds (front holds x and y, top x and z, right y and z),
        by the right-hand rule. For both, turn first and offset that plane next.
        Returns the plane's name and how a sketch on it lies in the model:
        origin_mm, normal, x_axis and y_axis, so a point (u, v) on it is
        origin + u x_axis + v y_axis.
        """
        if bool(offset_mm) == bool(angle_deg):
            raise SolidWorksError("Give offset_mm or angle_deg (for both: turn first, then offset that plane).")
        key = axis = None
        if angle_deg:
            key, axis = str(base).lower(), str(about or "").lower()
            if axis not in self._AXIS_PLANES:
                raise SolidWorksError(f"about must be 'x', 'y' or 'z' (got {about!r}).")
            if key not in self._AXIS_PLANES[axis]:
                raise SolidWorksError(
                    f"The {axis} axis lies in the {' and '.join(self._AXIS_PLANES[axis])} planes: "
                    f"turn one of those about it (got '{base}')."
                )
            if not 0.0 < abs(angle_deg) < 180.0:
                raise SolidWorksError(f"angle_deg must be between -180 and 180, not 0 (got {angle_deg}).")
        self._require_model()
        if angle_deg:
            plane = self._turned_plane(key, axis, angle_deg)
        else:
            plane, _ = self._plane_at(base, offset_mm)
        if name:
            plane.Name = name
            if plane.Name != name:
                raise SolidWorksError(
                    f"The plane could not be named '{name}' (it is '{plane.Name}'): is the name taken?"
                )
        dimension = self._first_dimension_name(plane)
        return {
            "ok": True,
            "plane": plane.Name,
            "dimensions": {"angle" if angle_deg else "offset": dimension},
            **self._plane_frame(plane),
        }

    def _turned_plane(self, base: str, axis: str, angle_deg: float):
        """The default plane `base` turned angle_deg about the model axis `axis`
        (right-hand rule). SolidWorks picks its own sense, so the normal is
        checked and the plane built the other way round when it is wrong."""
        model = self._model
        base_plane, _ = self._named_plane(base)
        expected = self._turned_normal(self._PLANE_NORMALS[base], axis, angle_deg)
        reference_axis = self._model_axis(axis)
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        for flip in (False, True):
            before = {f.Name for f in self._history()}
            model.ClearSelection2(True)
            if not (base_plane.Select2(False, 0) and reference_axis.Select2(True, 1)):
                raise SolidWorksError(f"Could not select the {base} plane and the {axis} axis.")
            constraint = SW_REF_PLANE_ANGLE | (SW_REF_PLANE_FLIP if flip else 0)
            if (
                feat_mgr.InsertRefPlane(constraint, math.radians(abs(angle_deg)), SW_REF_PLANE_COINCIDENT, 0.0, 0, 0.0)
                is None
            ):
                raise SolidWorksError(f"Could not turn the {base} plane {angle_deg:g} degrees about {axis}.")
            plane = self._last_ref_plane()
            normal = self._plane_frame(plane)["normal"]
            if abs(sum(n * e for n, e in zip(normal, expected))) > 1 - 1e-6:
                return plane
            self._remove_features_since(before)  # turned the wrong way: build it the other way round
        raise SolidWorksError(f"SolidWorks did not turn the {base} plane {angle_deg:g} degrees about {axis}.")

    @staticmethod
    def _turned_normal(normal, axis: str, angle_deg: float) -> list:
        """`normal` turned angle_deg about the model axis `axis` by the right-hand
        rule; pure, unit-tested."""
        c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
        x, y, z = normal
        if axis == "x":
            return [x, c * y - s * z, s * y + c * z]
        if axis == "y":
            return [c * x + s * z, y, -s * x + c * z]
        return [c * x - s * y, s * x + c * y, z]

    def _model_axis(self, axis: str):
        """A reference axis along the model axis `axis`, where its two default
        planes meet; made once, named 'Axis X' etc., and hidden."""
        label = f"Axis {axis.upper()}"
        found = [f for f in self._history() if f.Name == label and f.GetTypeName2() == "RefAxis"]
        if found:
            return found[0]
        model = self._model
        first, second = (self._named_plane(key)[0] for key in self._AXIS_PLANES[axis])
        model.ClearSelection2(True)
        if not (first.Select2(False, 0) and second.Select2(True, 0)) or not model.InsertAxis2(True):
            raise SolidWorksError(f"Could not make a reference axis along {axis}.")
        made = [f for f in self._history() if f.GetTypeName2() == "RefAxis"][-1]
        made.Name = label
        if made.Select2(False, 0):
            model.BlankRefGeom()  # construction geometry; keep screenshots clean
        model.ClearSelection2(True)
        return made
