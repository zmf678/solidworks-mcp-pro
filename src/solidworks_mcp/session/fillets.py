"""Fillets, variable-radius fillets and full rounds.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    SW_DELETE_ABSORBED,
    SW_FILLET_OPT_PROPAGATE,
    SW_FILLET_OPT_STRAIGHT_TRANSITION,
    SW_FILLET_OPT_UNIFORM_RADIUS,
    SW_FILLET_TYPE_FULL_ROUND,
    SW_FILLET_TYPE_SIMPLE,
    SW_FILLET_TYPE_VARIABLE,
    SW_MARK_FULL_ROUND_CENTRE,
    SW_MARK_FULL_ROUND_SIDE_1,
    SW_MARK_FULL_ROUND_SIDE_2,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m


class FilletsMixin:
    """Fillets, variable-radius fillets and full rounds."""

    def add_fillet(
        self,
        radius_mm: float,
        edges: str = "all",
        name: str = "Fillet",
        radii_at_mm: list | None = None,
        skip_shorter_mm: float | None = None,
        tangent_propagation: bool = False,
    ) -> dict:
        """Round edges of the part's solid body with one constant radius.

        edges: 'all' (default); a world axis 'x'|'y'|'z' (straight edges parallel
        to it, e.g. 'z' = the depth edges of an add_box block); a face outline
        like '+z:outline' (the outer edges of the top face, not those of holes in
        it); every edge of one feature, 'feature:Boss'; or explicit indices like
        '2,5' from list_edges. radii_at_mm = [[x, y, z, r], ...] makes the radius
        vary: r at the edge end at each point (list_edges gives the ends),
        radius_mm at the other ends, straight in between; 'vertex_radii' names
        each end's radius dimension. skip_shorter_mm leaves out the edges shorter
        than that (slivers a radius cannot follow). tangent_propagation=True
        carries the round on along the edges that run on smoothly from the given
        ones, as SolidWorks' own default does: an edge that ends where it runs
        into another tangentially, such as round a fillet, rounds only so. When
        SolidWorks refuses, each edge is tried alone, also with propagation, and
        the error names the ones that do not fit. Returns how many edges were
        filleted and the resulting mass properties (volume drops as convex edges
        are rounded off).
        """
        self._require_model()
        if radius_mm <= 0:
            raise SolidWorksError(f"radius must be > 0 (got {radius_mm}).")

        body = self._solid_body()
        edge_count = self._select_edges(body, edges)
        if edge_count == 0:
            raise SolidWorksError(f"No edges found for selector '{edges}'.")
        skipped = 0
        if skip_shorter_mm is not None:
            skipped = self._deselect_short_edges(skip_shorter_mm)
            edge_count -= skipped
            if edge_count == 0:
                raise SolidWorksError(f"Every edge of '{edges}' is shorter than {skip_shorter_mm:g} mm.")
        if radii_at_mm:
            return self._variable_fillet(radius_mm, radii_at_mm, edge_count, name)

        selected = self._selected_objects()
        fillet = self._uniform_fillet(radius_mm, tangent_propagation)
        if fillet is None:
            raise SolidWorksError(self._fillet_refusal(radius_mm, selected, tangent_propagation))
        result = self._finish_feature(fillet, name, edges_filleted=edge_count)
        if skip_shorter_mm is not None:
            result["edges_skipped"] = skipped
        return result

    def _uniform_fillet(self, radius_mm: float, propagate: bool = False):
        """FeatureFillet3 on the selected edges with one radius; None when refused."""
        feat_mgr = binding.wrap(self._model.FeatureManager, self._mod.IFeatureManager)
        return feat_mgr.FeatureFillet3(
            SW_FILLET_OPT_UNIFORM_RADIUS | (SW_FILLET_OPT_PROPAGATE if propagate else 0),  # Options
            mm_to_m(radius_mm),  # R1 (uniform radius)
            0.0,
            0.0,  # R2, Rho
            SW_FILLET_TYPE_SIMPLE,  # Ftyp
            0,
            0,  # OverflowType, ConicRhoType
            None,
            None,
            None,
            None,  # Radii, Dist2Arr, RhoArr, SetBackDistances
            None,
            None,
            None,  # PointRadius/Dist2/Rho arrays
        )

    def _selected_objects(self) -> list:
        selmgr = binding.wrap(self._model.SelectionManager, self._mod.ISelectionMgr)
        return [selmgr.GetSelectedObject6(i, -1) for i in range(1, selmgr.GetSelectedObjectCount2(-1) + 1)]

    def _deselect_short_edges(self, shorter_mm: float) -> int:
        """Keep only the selected edges at least shorter_mm long; return how many went."""
        selected = self._selected_objects()
        long_enough = [e for e in selected if self._edge_entry(0, e)["length_mm"] >= shorter_mm]
        self._model.ClearSelection2(True)
        for edge in long_enough:
            binding.wrap(edge, self._mod.IEntity).Select4(True, None)
        return len(selected) - len(long_enough)

    def _fillet_refusal(self, radius_mm: float, edges: list, propagate: bool = False) -> str:
        """Why a fillet was refused. The edges are added one at a time to a
        trial fillet (removed again each time): an edge that breaks the group
        is left out, and tried alone to tell which fail on their own; one that
        does is tried with tangent propagation too, when that was off."""
        if len(edges) > self._MAX_FILLET_TRIALS:
            return f"SolidWorks could not round {len(edges)} edge(s) with R{radius_mm:g}: is the radius too large?"
        model = self._model
        extension = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        index_of = {ref: i for i, ref in enumerate(self._persist_refs(self._solid_body().GetEdges() or ()))}

        def rounds(refs, chain=propagate, radius=radius_mm) -> bool:
            model.ClearSelection2(True)
            for ref in refs:
                binding.wrap(extension.GetObjectByPersistReference3(ref)[0], self._mod.IEntity).Select4(True, None)
            trial = self._uniform_fillet(radius, chain)
            model.ClearSelection2(True)
            if trial is None:
                return False
            binding.wrap(trial, self._mod.IFeature).Select2(False, 0)
            extension.DeleteSelection2(SW_DELETE_ABSORBED)
            model.ClearSelection2(True)
            return True

        fits, alone, together = [], [], []
        for ref in self._persist_refs(edges):
            if rounds(fits + [ref]):
                fits.append(ref)
            else:
                (together if rounds([ref]) else alone).append(ref)
        chained = [ref for ref in alone if not propagate and rounds([ref], True)]
        alone = [ref for ref in alone if ref not in chained]

        def named(refs) -> str:
            return ", ".join(
                f"{index_of.get(ref, -1)} ({self._edge_entry(0, extension.GetObjectByPersistReference3(ref)[0])['length_mm']:g} mm)"
                for ref in refs
            )

        parts = []
        if chained:
            parts.append(
                f"edge(s) {named(chained)} fail alone but round with tangent_propagation=True: they end where "
                "they run on smoothly into further edges, such as round a fillet, which the round must follow"
            )
        if alone:
            parts.append(
                f"edge(s) {named(alone)} fail even alone{'' if propagate else ', also with tangent propagation'}"
                + self._largest_rounds(alone, index_of, lambda ref, r: rounds([ref], radius=r), radius_mm)
            )
        if together:
            parts.append(f"edge(s) {named(together)} round alone but not with the others")
        message = f"R{radius_mm:g} does not round all {len(edges)} edge(s): {'; '.join(parts)}."
        if fits:
            keep = ",".join(str(index_of.get(ref, -1)) for ref in fits)
            message += f' The other {len(fits)} round together: edges="{keep}" (list_edges indices).'
        return message + " Else a smaller radius, or skip_shorter_mm for slivers."

    def _largest_rounds(self, refs, index_of, rounds, radius_mm: float) -> str:
        """', the largest round each takes: 13 R1.99, ...', found by halving
        the step between a round that fits and one that does not; '' for more
        edges than are worth the trials."""
        if len(refs) > self._MAX_RADIUS_SEARCHES:
            return ""
        found = []
        for ref in refs:
            low, high = 0.0, radius_mm
            for _ in range(self._RADIUS_STEPS):
                middle = (low + high) / 2
                low, high = (middle, high) if rounds(ref, middle) else (low, middle)
            largest = math.floor(low * 100) / 100
            found.append(
                ("" if len(refs) == 1 else f"{index_of.get(ref, -1)} ") + (f"R{largest:g}" if largest else "none")
            )
        label = "the largest round it takes" if len(refs) == 1 else "the largest round each takes"
        return f"; {label}: {', '.join(found)}"

    def _variable_fillet(self, radius_mm: float, radii_at_mm, edge_count: int, name: str) -> dict:
        """Fillet the selected edges with a radius that runs straight from end to
        end: radii_at_mm at the ends there, radius_mm at the others."""
        ends = self._selected_edge_ends()
        radii = self._vertex_radii(ends, radii_at_mm, radius_mm)
        feat_mgr = binding.wrap(self._model.FeatureManager, self._mod.IFeatureManager)
        fillet = feat_mgr.FeatureFillet3(
            SW_FILLET_OPT_STRAIGHT_TRANSITION,
            mm_to_m(radius_mm),
            0.0,
            0.0,
            SW_FILLET_TYPE_VARIABLE,
            0,
            0,
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [mm_to_m(r) for r in radii]),  # one per end
            None,
            None,
            None,
            None,
            None,
            None,
        )
        if fillet is None:
            raise SolidWorksError("FeatureFillet3 failed (None). Is a radius too large for the geometry?")
        result = self._finish_feature(fillet, name, edges_filleted=edge_count)
        feature = binding.wrap(fillet, self._mod.IFeature)
        self._check_vertex_radii(feature, dict(zip(ends, radii)))
        values = {d["name"]: d["value"] for d in self._dimension_entries(feature)}
        result["vertex_radii"] = []
        for k, (end, radius) in enumerate(zip(ends, radii)):
            dimension = f"{self._vertex_radius_dimension(k)}@{result['feature']}"
            if values.get(dimension) is None or abs(values[dimension] - radius) > 1e-6:
                raise SolidWorksError(f"Could not find the dimension of the radius at {list(end)} ({dimension}).")
            result["vertex_radii"].append({"at_mm": list(end), "radius_mm": radius, "dimension": dimension})
        return result

    def _vertex_mm(self, vertex) -> tuple:
        return tuple(round(m_to_mm(c), 4) for c in binding.wrap(vertex, self._mod.IVertex).GetPoint())

    def _selected_edge_ends(self) -> list:
        """The ends of the selected edges in the order SolidWorks numbers them for
        a variable fillet: edge by edge as selected, start before end, each once
        (verified)."""
        selmgr = binding.wrap(self._model.SelectionManager, self._mod.ISelectionMgr)
        ends = []
        for i in range(1, selmgr.GetSelectedObjectCount2(-1) + 1):
            edge = binding.wrap(selmgr.GetSelectedObject6(i, -1), self._mod.IEdge)
            vertices = [edge.GetStartVertex(), edge.GetEndVertex()]
            if None in vertices:
                raise SolidWorksError("A variable fillet needs edges with two ends; a full circle has none.")
            for vertex in vertices:
                position = self._vertex_mm(vertex)
                if position not in ends:
                    ends.append(position)
        return ends

    @classmethod
    def _vertex_radii(cls, ends_mm, radii_at_mm, default_mm) -> list:
        """The radius at each edge end: r where a point [x, y, z, r] lies on that
        end, default_mm at the others; pure, unit-tested."""
        radii = [default_mm] * len(ends_mm)
        placed = set()
        for entry in radii_at_mm:
            try:
                x, y, z, radius = (float(v) for v in entry)
            except (TypeError, ValueError):
                raise SolidWorksError(f"radii_at_mm takes [x, y, z, radius] per edge end (got {entry}).") from None
            if radius <= 0:
                raise SolidWorksError(f"A variable fillet needs a radius > 0 at every end (got {radius:g}).")
            at = next(
                (k for k, end in enumerate(ends_mm) if math.dist(end, (x, y, z)) <= cls._VERTEX_TOLERANCE_MM), None
            )
            if at is None:
                listed = ", ".join(f"({', '.join(f'{c:g}' for c in end)})" for end in ends_mm)
                raise SolidWorksError(f"No end of the edges at ({x:g}, {y:g}, {z:g}); they end at {listed}.")
            if at in placed:
                raise SolidWorksError(f"radii_at_mm gives the end at ({x:g}, {y:g}, {z:g}) a radius twice.")
            placed.add(at)
            radii[at] = radius
        return radii

    @staticmethod
    def _vertex_radius_dimension(k: int) -> str:
        """SolidWorks names the radii of a variable fillet D0, D01, D02, ... in the
        order it got them (verified up to D011)."""
        return "D0" if k == 0 else f"D0{k}"

    def _check_vertex_radii(self, feature, radius_at: dict) -> None:
        """Read back the radius SolidWorks gave each end: the radii go in as a bare
        list, so a different numbering would put them on the wrong ends unseen."""
        data = binding.wrap(feature.GetDefinition(), self._mod.IVariableFilletFeatureData2)
        if not data.AccessSelections(self._model, None):
            raise SolidWorksError("Could not read the variable fillet back.")
        try:
            for i in range(data.FilletEdgeCount):
                edge = binding.wrap(data.GetFilletEdgeAtIndex(i), self._mod.IEdge)
                for vertex in (edge.GetStartVertex(), edge.GetEndVertex()):
                    end, got = self._vertex_mm(vertex), m_to_mm(data.GetRadius(vertex))
                    if end not in radius_at or abs(got - radius_at[end]) > 1e-6:
                        raise SolidWorksError(
                            f"SolidWorks put R{got:g} at {list(end)}, not the radius asked for there."
                        )
        finally:
            data.ReleaseSelectionAccess()

    def add_full_round(self, face: str, x_mm: float, y_mm: float, z_mm: float, name: str = "FullRound") -> dict:
        """Round a rib's top off completely: a fillet tangent to the planar face
        facing `face` through the point and to the two opposite flat side faces
        along it that lie closest together. Its radius is half their distance,
        'width_mm', so it follows the rib; there is no radius dimension. Hand
        calculation: a rib w wide and L long loses L w^2 (1/2 - pi/8)."""
        model = self._require_model()
        normal, side = self._parse_face_selector(face, default_side=None)
        centre = self._select_face_through(self._solid_body(), normal, side, (x_mm, y_mm, z_mm), face)
        sides = self._side_faces(centre, normal)
        first, second, width = self._full_round_sides([(f.Normal, self._plane_point_mm(f)) for f in sides])
        selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
        model.ClearSelection2(True)
        for entity, mark in (
            (sides[first], SW_MARK_FULL_ROUND_SIDE_1),
            (centre, SW_MARK_FULL_ROUND_CENTRE),
            (sides[second], SW_MARK_FULL_ROUND_SIDE_2),
        ):
            data = binding.wrap(selmgr.CreateSelectData(), self._mod.ISelectData)
            data.Mark = mark
            if not binding.wrap(entity, self._mod.IEntity).Select4(True, data):
                raise SolidWorksError("Could not select the faces for the full round.")
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        fillet = feat_mgr.FeatureFillet3(
            0, 0.0, 0.0, 0.0, SW_FILLET_TYPE_FULL_ROUND, 0, 0, None, None, None, None, None, None, None
        )
        if fillet is None:
            raise SolidWorksError(f"SolidWorks could not round the {face} face off between its sides.")
        return self._finish_feature(fillet, name, width_mm=round(width, 4))

    def _side_faces(self, centre, normal) -> list:
        """The flat faces along the edges of `centre` that stand square to it, each once."""
        extension = binding.wrap(self._model.Extension, self._mod.IModelDocExtension)
        seen, sides = set(), []
        for edge in binding.wrap(centre, self._mod.IFace2).GetEdges() or ():
            for neighbour in binding.wrap(edge, self._mod.IEdge).GetTwoAdjacentFaces2() or ():
                neighbour = binding.wrap(neighbour, self._mod.IFace2)
                if not binding.wrap(neighbour.GetSurface(), self._mod.ISurface).IsPlane():
                    continue
                if abs(sum(a * b for a, b in zip(neighbour.Normal, normal))) > 1e-6:
                    continue  # the centre face itself, or a slanted neighbour
                key = bytes(extension.GetPersistReference3(neighbour))
                if key not in seen:
                    seen.add(key)
                    sides.append(neighbour)
        return sides

    def _plane_point_mm(self, face) -> tuple:
        """A point on a planar face's plane (PlaneParams: normal, then root point)."""
        params = binding.wrap(binding.wrap(face, self._mod.IFace2).GetSurface(), self._mod.ISurface).PlaneParams
        return tuple(m_to_mm(c) for c in params[3:6])

    @staticmethod
    def _full_round_sides(sides) -> tuple:
        """Of the side faces [(normal, point on it)], the opposite pair that lies
        closest together: (i, j, distance); pure, unit-tested."""
        pairs = []
        for i, (normal, point) in enumerate(sides):
            for j in range(i + 1, len(sides)):
                other_normal, other_point = sides[j]
                if sum(a * b for a, b in zip(normal, other_normal)) < -0.999999:
                    pairs.append((abs(sum((b - a) * n for a, b, n in zip(point, other_point, normal))), i, j))
        if not pairs:
            raise SolidWorksError(
                "A full round needs two opposite flat side faces along the face, such as a rib's sides."
            )
        pairs.sort()
        if len(pairs) > 1 and pairs[1][0] - pairs[0][0] < 1e-6:
            raise SolidWorksError(
                f"Two pairs of side faces are equally far apart ({pairs[0][0]:g} mm): the full "
                "round cannot tell which way to run."
            )
        distance, i, j = pairs[0]
        return i, j, distance
