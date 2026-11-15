"""Mass properties, bounding boxes, faces, edges and solid bodies.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    SW_BODY_SOLID,
    SW_DOC_ASSEMBLY,
)
from ..errors import SolidWorksError
from ..units import m_to_mm
from ._decorators import _reads_only


class InspectionMixin:
    """Mass properties, bounding boxes, faces, edges and solid bodies."""

    def rebuild(self, top_only: bool = False) -> dict:
        model = self._require_model()
        rebuilt_ok = bool(model.ForceRebuild3(top_only))
        result = {"ok": True, "rebuild_ok": rebuilt_ok}
        if int(model.GetType()) == SW_DOC_ASSEMBLY:  # a mate that lost its face holds nothing, yet rebuilds fine
            result["mate_errors"] = [
                {"name": mate.Name, "error": trouble} for mate in self._mates() if (trouble := self._mate_trouble(mate))
            ]
        return result

    @_reads_only
    def get_mass_properties(self) -> dict:
        """Volume/mass/area/centre-of-mass plus bounding box, all in SI->mm, forced SI."""
        model = self._require_model()
        ext = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        mp = binding.wrap(ext.CreateMassProperty(), self._mod.IMassProperty)
        if mp is None:
            raise SolidWorksError("CreateMassProperty returned None.")
        # Force SI (m, kg) regardless of document units. This is coupled to the
        # fixed 1e9/1e6/m_to_mm factors below, so do NOT swallow a failure here:
        # silently wrong units would be worse than a loud error.
        mp.UseSystemUnits = True
        if not mp.UseSystemUnits:
            raise SolidWorksError("Could not force mass properties to SI units (UseSystemUnits=False).")
        com = mp.CenterOfMass
        props = {
            "volume_mm3": mp.Volume * 1e9,
            "mass_kg": mp.Mass,
            "density_kg_m3": mp.Density,
            "surface_area_mm2": mp.SurfaceArea * 1e6,
            "center_of_mass_mm": [round(m_to_mm(c), 6) for c in com],
        }
        props["bounding_box_mm"] = self._bounding_box()
        return {"ok": True, "mass_properties": props}

    def _bounding_box(self):
        # IModelDoc2 has no GetBox, so the call depends on the document type. A
        # part joins its solid bodies' tight boxes, from their extreme points:
        # IPartDoc.GetPartBox runs loose round curved faces (10.004 for a loft
        # ending at 10, verified; millimetres round spline cuts). An empty part
        # has no box. An assembly joins the tight boxes of its components:
        # IAssemblyDoc.GetBox joins their turned outer boxes, too big for a
        # rotated part (verified: a 20 mm disc turned 45 degrees came out 28.3 wide).
        model = self._require_model()
        if int(model.GetType()) == SW_DOC_ASSEMBLY:
            assembly = binding.wrap(model, self._mod.IAssemblyDoc)
            assembly.EditRebuild()  # mates move components on a rebuild: measure where they end up
            return self._joined_box([self._component_box(c) for c in self._components(assembly)])
        return self._joined_box([self._body_box(body) for body in self._part_bodies()])

    @_reads_only
    def get_bounding_box(self) -> dict:
        self._require_model()
        return {"ok": True, "bounding_box_mm": self._bounding_box()}

    def _axis_of(self, dx, dy, dz, length):
        """Return 'x'|'y'|'z' if the vector is parallel to that axis, else None."""
        if length < 1e-9:
            return None
        for axis, (tx, ty, tz) in self._EDGE_AXES.items():
            if abs(dx * tx + dy * ty + dz * tz) / length > 0.999:
                return axis
        return None

    @_reads_only
    def list_faces(self, component: str | None = None) -> dict:
        """Inspect faces: index, planar?, normal, area, centre; a cylindrical face
        also gives its axis, radius and a point on the axis (a hole's centre).

        Lets an agent see the geometry before choosing one. Indices are positional
        in the body's face list and shift as features are added. component names
        a component of the current assembly; its faces are given in its own frame,
        e.g. to read a hole circle off an imported part.
        """
        if component is None:
            self._require_model()
            out = [self._face_entry(i, face) for i, face in enumerate(self._body_faces(self._solid_body()))]
        else:
            comp = self._component_by_name(self._require_assembly(), component)
            out = []
            for i, (face, part) in enumerate(self._component_faces(comp)):
                entry = self._face_entry(i, face, self._part_frame_in(comp, part))
                if part.Name2 != comp.Name2:
                    entry["part"] = part.Name2  # a part inside a sub-assembly
                out.append(entry)
        return {"ok": True, "count": len(out), "faces": out}

    def _face_entry(self, index: int, face_dispatch, frame=None) -> dict:
        """A face's index, type, area and centre; a planar face's normal, a
        cylinder's axis. `frame` (rotation rows, shift mm) moves it from its
        part's coordinates into a sub-assembly's."""
        face = binding.wrap(face_dispatch, self._mod.IFace2)
        surface = binding.wrap(face.GetSurface(), self._mod.ISurface)
        planar = bool(surface is not None and surface.IsPlane())
        rotation, shift = frame or ([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [0.0, 0.0, 0.0])

        def turn(v):
            return [sum(rotation[row][i] * v[i] for i in range(3)) for row in range(3)]

        def place(p):
            return [c + s for c, s in zip(turn(p), shift)]

        box = face.GetBox()
        center = None
        if box and len(box) >= 6:
            center = [m_to_mm((box[j] + box[j + 3]) / 2) for j in range(3)]
        entry = {
            "index": index,
            "type": "planar" if planar else "curved",
            "area_mm2": round(face.GetArea() * 1e6, 3),
            "center_mm": None if center is None else [round(c, 3) + 0.0 for c in place(center)],
        }
        if planar:
            entry["normal"] = [round(n, 4) + 0.0 for n in turn(face.Normal)]
        elif surface is not None and surface.IsCylinder() and center is not None:
            cylinder = self._cylinder_entry(surface, center)
            entry["cylinder"] = {
                "axis": [round(a, 6) + 0.0 for a in turn(cylinder["axis"])],
                "point_mm": [round(p, 4) + 0.0 for p in place(cylinder["point_mm"])],
                "radius_mm": cylinder["radius_mm"],
            }
        return entry

    @staticmethod
    def _cylinder_entry(surface, center_mm) -> dict:
        """Axis (either sense), radius, and the point on the axis nearest the
        face's centre: for a hole, its centre halfway down."""
        params = surface.CylinderParams  # axis origin xyz, axis direction xyz, radius (metres)
        origin = [m_to_mm(c) for c in params[0:3]]
        length = math.hypot(*params[3:6])
        axis = [c / length for c in params[3:6]]
        along = sum((c - o) * a for c, o, a in zip(center_mm, origin, axis))
        point = [o + along * a for o, a in zip(origin, axis)]
        return {"axis": axis, "point_mm": point, "radius_mm": round(m_to_mm(params[6]), 4)}

    @_reads_only
    def list_edges(
        self, face=None, feature: str | None = None, within_mm=None, min_length_mm: float | None = None
    ) -> dict:
        """Inspect the solid body's edges: index, type, length and ends (a full
        circle has none); lines also give axis and midpoint. Narrow the list
        with face (a list_faces index, '#5'), feature (the edges of the faces it
        made), within_mm ([[x1, y1, z1], [x2, y2, z2]]: both ends inside) and
        min_length_mm. Indices stay those of the whole list, for add_fillet."""
        self._require_model()
        body = self._solid_body()
        edges = list(body.GetEdges() or ())
        chosen = range(len(edges))
        if face is not None or feature is not None:
            index_of = {ref: i for i, ref in enumerate(self._persist_refs(edges))}
            for picked in (
                self._face_edges(body, face) if face is not None else None,
                self._feature_edges(feature) if feature is not None else None,
            ):
                if picked is not None:
                    keep = {index_of[ref] for ref in self._persist_refs(picked) if ref in index_of}
                    chosen = [i for i in chosen if i in keep]
        box = self._box_corners(within_mm) if within_mm is not None else None
        out = []
        for i in chosen:
            entry = self._edge_entry(i, edges[i])
            if min_length_mm is not None and entry["length_mm"] < min_length_mm:
                continue
            if box is not None and not all(
                all(lo <= c <= hi for c, lo, hi in zip(p, *box)) for p in entry.get("ends_mm", [entry["start_mm"]])
            ):
                continue
            entry.pop("start_mm")
            out.append(entry)
        return {"ok": True, "count": len(out), "edges": out}

    def _edge_entry(self, index: int, edge_dispatch) -> dict:
        """One edge in four COM calls: its curve, the curve's type, its ends and
        parameter range in one array (GetCurveParams2), and its length."""
        edge = binding.wrap(edge_dispatch, self._mod.IEdge)
        curve = binding.wrap(edge.GetCurve(), self._mod.ICurve)
        params = edge.GetCurveParams2()  # start xyz, end xyz (m), start and end parameter
        start = [round(m_to_mm(v), 4) + 0.0 for v in params[0:3]]
        end = [round(m_to_mm(v), 4) + 0.0 for v in params[3:6]]
        kind = self._CURVE_TYPES.get(curve.Identity(), "curve")
        length = m_to_mm(curve.GetLength3(params[6], params[7]))
        entry = {"index": index, "type": kind, "length_mm": round(length, 3), "start_mm": start}
        if math.dist(start, end) > 1e-6:  # a full circle starts where it ends
            entry["ends_mm"] = [start, end]
        if kind == "line":
            d = [b - a for a, b in zip(start, end)]
            entry["midpoint_mm"] = [round((a + b) / 2, 3) for a, b in zip(start, end)]
            entry["axis"] = self._axis_of(*d, math.dist(start, end))
        return entry

    def _persist_refs(self, entities) -> list:
        extension = binding.wrap(self._model.Extension, self._mod.IModelDocExtension)
        return [bytes(extension.GetPersistReference3(e)) for e in entities]

    def _face_edges(self, body, face) -> list:
        index = self._face_index(face)
        faces = self._body_faces(body)
        if index is None or not 0 <= index < len(faces):
            raise SolidWorksError(f"face takes a list_faces index, '#0' to '#{len(faces) - 1}' (got {face!r}).")
        return list(binding.wrap(faces[index], self._mod.IFace2).GetEdges() or ())

    def _feature_edges(self, name: str) -> list:
        return [
            edge
            for face in (self._history_feature(name).GetFaces() or ())
            for edge in binding.wrap(face, self._mod.IFace2).GetEdges() or ()
        ]

    @staticmethod
    def _box_corners(within_mm) -> tuple:
        """[[x1, y1, z1], [x2, y2, z2]] -> (low, high), corners in any order; pure."""
        try:
            (a, b) = within_mm
            a, b = [float(c) for c in a], [float(c) for c in b]
            assert len(a) == len(b) == 3
        except (TypeError, ValueError, AssertionError):
            raise SolidWorksError(
                f"within_mm takes two corners [[x1, y1, z1], [x2, y2, z2]] (got {within_mm})."
            ) from None
        return [min(p, q) for p, q in zip(a, b)], [max(p, q) for p, q in zip(a, b)]

    def _part_bodies(self) -> list:
        """The current part's solid bodies (IBody2), in SolidWorks' order."""
        bodies = binding.wrap(self._model, self._mod.IPartDoc).GetBodies2(SW_BODY_SOLID, False) or ()
        return [binding.wrap(body, self._mod.IBody2) for body in bodies]

    @_reads_only
    def list_bodies(self) -> dict:
        """The part's solid bodies: name, volume and bounding box. A part holds
        several after merge=False or split_body; combine_bodies joins them."""
        self._require_part()
        out = []
        for body in self._part_bodies():
            out.append(
                {
                    "name": body.Name,
                    "volume_mm3": round(body.GetMassProperties(1.0)[3] * 1e9, 4),
                    "bounding_box_mm": self._body_box(body),
                }
            )
        return {"ok": True, "count": len(out), "bodies": out}

    def _body_box(self, body) -> dict:
        """A body's tight box in part coordinates (mm), from its extreme points."""
        low = [
            m_to_mm(self._extreme_point(body, [-1.0 if i == axis else 0.0 for i in range(3)])[axis])
            for axis in range(3)
        ]
        high = [
            m_to_mm(self._extreme_point(body, [1.0 if i == axis else 0.0 for i in range(3)])[axis]) for axis in range(3)
        ]
        return self._joined_box([{"min_mm": [round(v, 4) for v in low], "max_mm": [round(v, 4) for v in high]}])

    def combine_bodies(self, operation: str, main: str, tools: list | None = None, name: str = "Combine") -> dict:
        """Combine solid bodies of the part into `main` (a list_bodies name):
        'add' joins the tools to it, 'subtract' cuts them out of it, 'common'
        keeps only what it shares with them. tools: body names, every other body
        by default."""
        key = str(operation).lower()
        if key not in self._BODY_OPERATIONS:
            raise SolidWorksError(f"operation must be one of {sorted(self._BODY_OPERATIONS)} (got '{operation}').")
        model = self._require_model()
        self._require_part()
        bodies = {body.Name: body for body in self._part_bodies()}
        if main not in bodies:
            raise SolidWorksError(f"No body '{main}' (there are: {', '.join(bodies) or 'none'}).")
        names = list(tools) if tools else [n for n in bodies if n != main]
        unknown = [n for n in names if n not in bodies or n == main]
        if unknown or not names:
            raise SolidWorksError(
                f"Give other bodies of the part to combine with '{main}' (there are: {', '.join(bodies)}; got {names})."
            )
        model.ClearSelection2(True)
        # the list holds the main body too: add and common fail without it (verified)
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        combined = feat_mgr.InsertCombineFeature(
            self._BODY_OPERATIONS[key],
            bodies[main],
            win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [bodies[n]._oleobj_ for n in [main, *names]]
            ),
        )
        if combined is None:
            raise SolidWorksError(f"SolidWorks could not {key} {', '.join(names)} and '{main}': do they overlap?")
        result = self._finish_feature(combined, name, combined=[main, *names])
        result["bodies"] = [body.Name for body in self._part_bodies()]
        return result

    def split_body(self, plane: str, name: str = "Split") -> dict:
        """Split the part's body in two along a plane (front/top/right or a plane
        by name, such as one add_plane made): two bodies, named in the result,
        to combine differently or check apart."""
        model = self._require_model()
        self._require_part()
        ref, label = self._named_plane(plane)
        model.ClearSelection2(True)
        if not ref.Select2(False, 0):
            raise SolidWorksError(f"Could not select the {label}.")
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        pieces = feat_mgr.PreSplitBody() or ()
        if len(pieces) < 2:
            model.ClearSelection2(True)
            raise SolidWorksError(f"The {label} does not cut through the part.")
        # one empty origin and save path per piece: keep them all in this part (verified)
        split = feat_mgr.PostSplitBody(
            win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [getattr(p, "_oleobj_", p) for p in pieces]
            ),
            False,
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [None] * len(pieces)),
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [""] * len(pieces)),
        )
        if split is None:
            raise SolidWorksError(f"SolidWorks could not split the part along the {label}.")
        result = self._finish_feature(split, name)
        result["bodies"] = [body.Name for body in self._part_bodies()]
        return result
