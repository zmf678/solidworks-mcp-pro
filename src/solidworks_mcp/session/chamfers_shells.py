"""Chamfers and shell operations.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

from .. import binding
from ..constants import (
    SW_CHAMFER_ANGLE_DISTANCE,
    SW_DELETE_ABSORBED,
    SW_FEATURE_CHAMFER_FLIP,
)
from ..errors import SolidWorksError
from ..units import deg_to_rad, mm_to_m


class ChamfersShellsMixin:
    """Chamfers and shell operations."""

    def add_chamfer(
        self,
        distance_mm: float,
        edges: str = "all",
        name: str = "Chamfer",
        angle_deg: float = 45.0,
        from_face: str | None = None,
    ) -> dict:
        """Chamfer edges of the part's solid body: distance_mm back along one
        face, at angle_deg to it (45, the default, is symmetric).

        edges: 'all' (default); a world axis 'x'|'y'|'z'; a face outline like
        '+z:outline'; every edge of one feature, 'feature:Boss'; or explicit
        indices like '2,5' from list_edges. Another angle than 45 needs
        from_face, which way the face the distance runs along faces ('-z': the
        underside, the chamfer leaving it at angle_deg, 60 for a printable
        edge). Round an arc the chamfer is a cone. Returns how many edges were
        chamfered and the resulting mass properties.
        """
        self._require_model()
        if distance_mm <= 0:
            raise SolidWorksError(f"distance must be > 0 (got {distance_mm}).")
        if not 0 < angle_deg < 90:
            raise SolidWorksError(f"angle_deg must be between 0 and 90 (got {angle_deg}).")
        if angle_deg != 45 and from_face is None:
            raise SolidWorksError(
                f"A chamfer at {angle_deg:g} degrees needs from_face: which way the face faces "
                "that the distance runs along and the angle is measured from, e.g. '-z'."
            )
        reference = self._parse_direction(from_face) if from_face is not None else None
        body = self._solid_body()
        chamfer, edge_count = self._insert_chamfer(body, edges, distance_mm, angle_deg, flip=False)
        if reference is not None:
            tilts = [self._tilt_deg(face, reference) for face in chamfer.GetFaces() or ()]
            if tilts and all(abs(t - (90 - angle_deg)) < self._CHAMFER_ANGLE_TOLERANCE_DEG for t in tilts):
                # SolidWorks measured from the other face of every edge
                self._model.ClearSelection2(True)
                chamfer.Select2(False, 0)
                binding.wrap(self._model.Extension, self._mod.IModelDocExtension).DeleteSelection2(SW_DELETE_ABSORBED)
                chamfer, edge_count = self._insert_chamfer(self._solid_body(), edges, distance_mm, angle_deg, flip=True)
                tilts = [self._tilt_deg(face, reference) for face in chamfer.GetFaces() or ()]
            off = [round(t, 2) for t in tilts if abs(t - angle_deg) >= self._CHAMFER_ANGLE_TOLERANCE_DEG]
            if off or not tilts:
                raise SolidWorksError(
                    f"The chamfer does not leave the {from_face} face at {angle_deg:g} degrees "
                    f"everywhere (its faces stand at {off or 'none'} to it): chamfer only edges "
                    f"of the {from_face} face, and edges that run the other way in a call of "
                    "their own."
                )
        return self._finish_feature(chamfer, name, edges_chamfered=edge_count)

    def _insert_chamfer(self, body, edges: str, distance_mm: float, angle_deg: float, flip: bool):
        """Select the edges and chamfer them; (feature, edge count)."""
        edge_count = self._select_edges(body, edges)
        if edge_count == 0:
            raise SolidWorksError(f"No edges found for selector '{edges}'.")
        feat_mgr = binding.wrap(self._model.FeatureManager, self._mod.IFeatureManager)
        chamfer = feat_mgr.InsertFeatureChamfer(
            SW_FEATURE_CHAMFER_FLIP if flip else 0,  # Options (no tangent propagation)
            SW_CHAMFER_ANGLE_DISTANCE,  # ChamferType (distance + angle)
            mm_to_m(distance_mm),  # Width (the setback distance)
            deg_to_rad(angle_deg),  # Angle (45 deg -> symmetric chamfer)
            0.0,  # OtherDist
            0.0,
            0.0,
            0.0,  # Vertex chamfer distances
        )
        if chamfer is None:
            raise SolidWorksError("InsertFeatureChamfer failed (None). Is the distance too large for the geometry?")
        return binding.wrap(chamfer, self._mod.IFeature), edge_count

    def _tilt_deg(self, face, direction) -> float:
        """The angle between a face and the plane facing `direction`, in degrees:
        between their normals, averaged over the face's facets (a cone's is the
        same all round)."""
        triangles = self._face_triangles(binding.wrap(face, self._mod.IFace2))
        if not triangles:
            return float("nan")
        cosines = [sum(n * d for n, d in zip(normal, direction)) for *_, normal in triangles]
        return math.degrees(math.acos(max(-1.0, min(1.0, sum(cosines) / len(cosines)))))

    def add_shell(self, thickness_mm: float, open_face: str | list = "+z") -> dict:
        """Hollow the part to a wall of `thickness_mm`, optionally opening faces.

        open_face: a direction '+z'/'-z'/'+x'/... selects the planar face to remove
        (an open shell), '#5' the face of that list_faces index; a list opens
        several at once; 'none' makes a fully closed hollow. Returns mass
        properties (volume drops to just the walls). InsertFeatureShell returns no
        feature object, so there is no feature name.
        """
        if thickness_mm <= 0:
            raise SolidWorksError(f"thickness must be > 0 (got {thickness_mm}).")
        opened = self._open_faces(open_face)
        model = self._require_model()
        body = self._solid_body()
        model.ClearSelection2(True)
        for selector in opened:
            index = self._face_index(selector)
            if index is None:
                normal, side = self._parse_face_selector(selector)
                face = self._planar_face_by_normal(body, normal, side)
            else:
                faces = self._body_faces(body)
                face = faces[index] if index < len(faces) else None
            if face is None:
                raise SolidWorksError(f"No face '{selector}' to open: see list_faces.")
            if not binding.wrap(face, self._mod.IEntity).Select4(True, None):
                raise SolidWorksError(f"Could not select the face '{selector}'.")

        # Outward=False: the wall grows inward, so the outer size is unchanged.
        model.InsertFeatureShell(mm_to_m(thickness_mm), False)
        rebuilt_ok = bool(model.ForceRebuild3(False))
        props = self.get_mass_properties()["mass_properties"]
        if abs(props["volume_mm3"]) < 1e-6:
            raise SolidWorksError("The shell removed all material; is the wall too thick?")
        return {"ok": True, "open_face": open_face, "rebuild_ok": rebuilt_ok, "mass_properties": props}

    def _open_faces(self, open_face) -> list:
        """The faces add_shell opens: [] for 'none', else the selectors, each a
        direction or '#index', checked before SolidWorks is touched."""
        if isinstance(open_face, str) and open_face.strip().lower() in ("none", ""):
            return []
        selectors = [open_face] if isinstance(open_face, str) else list(open_face or [])
        if not selectors:
            raise SolidWorksError("open_face needs a face, a list of faces, or 'none'.")
        for selector in selectors:
            if self._face_index(selector) is None:
                try:
                    self._parse_face_selector(str(selector))
                except SolidWorksError as exc:
                    raise SolidWorksError(f"open_face '{selector}' is no direction or '#index': {exc}") from exc
        return [str(s).strip().lower() for s in selectors]

    def _first_edge_along(self, body, direction):
        """First straight edge parallel to `direction`; returns (p1, p2, dispatch).

        Returns the edge's raw dispatch too so the caller can select the exact
        edge it analysed (keeping a computed flip in lockstep with the selection),
        rather than re-resolving by coordinate. (None, None, None) if no match.
        """
        edges = body.GetEdges()
        if not edges:
            return None, None, None
        if not isinstance(edges, (list, tuple)):
            edges = [edges]
        for edge_dispatch in edges:
            edge = binding.wrap(edge_dispatch, self._mod.IEdge)
            curve = binding.wrap(edge.GetCurve(), self._mod.ICurve)
            if not (curve is not None and curve.IsLine()):
                continue
            start, end = edge.GetStartVertex(), edge.GetEndVertex()
            if start is None or end is None:
                continue
            p1 = binding.wrap(start, self._mod.IVertex).GetPoint()
            p2 = binding.wrap(end, self._mod.IVertex).GetPoint()
            dx, dy, dz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
            length = (dx * dx + dy * dy + dz * dz) ** 0.5
            if length > 1e-9 and abs(dx * direction[0] + dy * direction[1] + dz * direction[2]) / length > 0.999:
                return p1, p2, edge_dispatch
        return None, None, None
