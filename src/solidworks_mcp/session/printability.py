"""Overhang, island, unsupported-edge and thin-wall analysis.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math
import time

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    RAY_HIT_WIDTH,
    SW_RAY_HIT_EXIT,
    SW_RAY_NORMALS_ENTRY_EXIT,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m
from ._decorators import _reads_only


class PrintabilityMixin:
    """Overhang, island, unsupported-edge and thin-wall analysis."""

    @_reads_only
    def check_printability(self, up: str = "+z", overhang_deg: float = 45.0, min_wall_mm: float | None = None) -> dict:
        """Check the current part for 3D printing, built along `up`.

        Overhangs: downward faces leaning more than overhang_deg from vertical
        (90 = a flat ceiling) need support; faces resting on the bed do not
        count. Islands: where the print starts in the air (a downward edge or
        point with nothing beneath), even between faces too steep to overhang.
        Unsupported edges: stretches of an edge the material rises from with
        air right below, such as the ends of a chamfer's edge that only rests
        on material in the middle.
        With min_wall_mm, also the walls thinner than that, measured
        straight through the material from points spread over every face; a
        spot right beside a sharp edge reads as thin as the wedge there is.
        Faces are list_faces indexes, so a finding can be selected and fixed.
        """
        direction = self._parse_direction(up)
        if not 0.0 < overhang_deg < 90.0:
            raise SolidWorksError(f"overhang_deg must be between 0 and 90 (got {overhang_deg}).")
        if min_wall_mm is not None and min_wall_mm <= 0:
            raise SolidWorksError(f"min_wall_mm must be > 0 (got {min_wall_mm}).")
        self._require_model()
        body = self._solid_body()
        triangles = [
            (index, *tri)
            for index, face in enumerate(self._body_faces(body))
            for tri in self._face_triangles(binding.wrap(face, self._mod.IFace2))
        ]
        result = {
            "ok": True,
            "up": up,
            **self._overhangs(triangles, direction, overhang_deg),
            "islands": self._islands(triangles, direction),
            "unsupported_edges": self._unsupported_edges(body, triangles, direction, overhang_deg),
        }
        if min_wall_mm is not None:
            result["thin_walls"] = self._thin_walls(body, triangles, min_wall_mm)
        return result

    @staticmethod
    def _face_triangles(face) -> list:
        """The face's display tessellation as (a, b, c, unit outward normal) in mm."""
        corners, normals = face.GetTessTriangles(True) or (), face.GetTessNorms() or ()
        triangles = []
        for t in range(len(corners) // 9):
            a, b, c = ([m_to_mm(v) for v in corners[9 * t + 3 * k : 9 * t + 3 * k + 3]] for k in range(3))
            normal = [sum(normals[9 * t + 3 * k + i] for k in range(3)) for i in range(3)]
            length = math.hypot(*normal)
            if length:
                triangles.append((a, b, c, [n / length for n in normal]))
        return triangles

    @staticmethod
    def _triangle_area(a, b, c) -> float:
        ab, ac = [q - p for p, q in zip(a, b)], [q - p for p, q in zip(a, c)]
        return (
            math.hypot(ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]) / 2
        )

    def _overhangs(self, triangles, up, limit_deg) -> dict:
        """Overhanging area per face, and the area resting on the bed."""

        def height(p):
            return sum(c * u for c, u in zip(p, up))

        bed = min(height(p) for _, *corners, _ in triangles for p in corners)
        faces, bed_area = {}, 0.0
        for index, a, b, c, normal in triangles:
            area = self._triangle_area(a, b, c)
            if all(abs(height(p) - bed) < 1e-4 for p in (a, b, c)):
                bed_area += area
                continue
            lean = math.degrees(math.asin(max(0.0, min(1.0, -sum(n * u for n, u in zip(normal, up))))))
            if lean > limit_deg + 1e-6:
                entry = faces.setdefault(index, {"index": index, "area_mm2": 0.0, "worst_deg": 0.0, "sum": [0.0] * 3})
                entry["area_mm2"] += area
                entry["worst_deg"] = max(entry["worst_deg"], lean)
                entry["sum"] = [s + area * (p + q + r) / 3 for s, p, q, r in zip(entry["sum"], a, b, c)]
        found = []
        for entry in sorted(faces.values(), key=lambda e: -e["area_mm2"]):
            centre = [s / entry["area_mm2"] for s in entry.pop("sum")]
            found.append(
                {
                    **entry,
                    "area_mm2": round(entry["area_mm2"], 3),
                    "worst_deg": round(entry["worst_deg"], 2),
                    "center_mm": [round(c, 3) for c in centre],
                }
            )
        heights = [height(p) for _, *corners, _ in triangles for p in corners]
        return {
            "height_mm": round(max(heights) - bed, 4),
            "bed_contact_mm2": round(bed_area, 3),
            "overhang": {
                "limit_deg": limit_deg,
                "area_mm2": round(sum(f["area_mm2"] for f in found), 3),
                "faces": found,
            },
        }

    @staticmethod
    def _islands(triangles, up) -> list:
        """Where the print starts in the air: a point, edge or flat patch of
        the surface lower than all around it, with material above it, not on
        the bed. A slicer starts a new island there, with nothing beneath; the
        faces beside it may lean too little to count as overhang. Pure,
        unit-tested."""

        def height(p):
            return sum(c * u for c, u in zip(p, up))

        def key(p):
            return tuple(round(c, 3) for c in p)  # faces meshed apart share their edge points

        points, neighbours, below, faces = {}, {}, {}, {}
        for index, a, b, c, normal in triangles:
            downward = sum(n * u for n, u in zip(normal, up)) < -1e-6
            corners = [key(p) for p in (a, b, c)]
            for k, corner in enumerate(corners):
                points[corner] = height(corner)
                neighbours.setdefault(corner, set()).update(corners[:k] + corners[k + 1 :])
                below[corner] = below.get(corner, False) or downward
                faces.setdefault(corner, set()).update([index] if downward else [])  # the faces that hang there
        bed, seen, found = min(points.values()), set(), []
        for start in sorted(points, key=points.get):
            level = points[start]
            if start in seen or level - bed < 1e-3:
                continue
            patch, todo = {start}, [start]
            while todo:  # the points around at the same height
                for n in neighbours[todo.pop()]:
                    if n not in patch and abs(points[n] - level) < 1e-3:
                        patch.add(n)
                        todo.append(n)
            seen |= patch
            lower = any(points[n] < level - 1e-3 for p in patch for n in neighbours[p])
            if not lower and any(below[p] for p in patch):
                found.append(
                    {
                        "height_mm": round(level - bed, 3),
                        "at_mm": [round(sum(p[i] for p in patch) / len(patch), 3) for i in range(3)],
                        "faces": sorted(set().union(*(faces[p] for p in patch))),
                    }
                )
        return found

    @staticmethod
    def _lower_edges(triangles, up, overhang_deg) -> list:
        """The edges the material rises from, (a, b, faces): flatter than the
        overhang limit, both faces beside them above them, and not both facing
        up (that is a groove, with the material below). Such an edge must rest
        on material along its length. Pure, unit-tested."""

        def height(p):
            return sum(c * u for c, u in zip(p, up))

        def key(p):
            return tuple(round(c, 3) for c in p)

        sides = {}
        for index, a, b, c, normal in triangles:
            corners = [key(p) for p in (a, b, c)]
            facing = sum(n * u for n, u in zip(normal, up))
            for k in range(3):
                edge = tuple(sorted((corners[k], corners[(k + 1) % 3])))
                sides.setdefault(edge, []).append((corners[(k + 2) % 3], facing, index))
        steepest = math.cos(math.radians(overhang_deg))
        found = []
        for (a, b), beside in sides.items():
            length = math.dist(a, b)
            if len(beside) != 2 or not length or abs(height(b) - height(a)) / length >= steepest:
                continue
            along = [(q - p) / length for p, q in zip(a, b)]

            def above(point):  # higher than the edge right beside it
                t = max(0.0, min(length, sum((c - p) * e for c, p, e in zip(point, a, along))))
                return height(point) > height(a) + t / length * (height(b) - height(a)) + 1e-3

            if all(above(third) for third, _, _ in beside) and min(f for _, f, _ in beside) < 1e-6:
                found.append((a, b, sorted({index for _, _, index in beside})))
        return found

    def _unsupported_edges(self, body, triangles, up, overhang_deg) -> list:
        """Stretches of the lower edges with air right below them: probed just
        under the edge, a ray that first leaves the material starts inside it."""

        def height(p):
            return sum(c * u for c, u in zip(p, up))

        bed = min(height(p) for _, *corners, _ in triangles for p in corners)
        probes = []
        for a, b, faces in self._lower_edges(triangles, up, overhang_deg):
            if min(height(a), height(b)) - bed < self._EDGE_PROBE_MM:
                continue  # on the bed
            count = max(1, math.ceil(math.dist(a, b) / self._EDGE_SAMPLE_MM))
            for k in range(count):
                point = [p + (k + 0.5) / count * (q - p) for p, q in zip(a, b)]
                probes.append((point, math.dist(a, b) / count, faces))
        if not probes:
            return []
        skew = [0.267, 0.535, 0.802]  # along no model axis, so no ray grazes a face
        starts = [mm_to_m(c - self._EDGE_PROBE_MM * u) for point, _, _ in probes for c, u in zip(point, up)]
        first = {}
        for ray, distance, leaving in self._ray_hits(body, starts, skew * len(probes)):
            if distance < first.get(ray, (math.inf,))[0]:
                first[ray] = (distance, leaving)
        loose = [probes[ray] for ray in range(len(probes)) if not first.get(ray, (0, False))[1]]
        return self._stretches(loose, height, bed)

    def _stretches(self, loose, height, bed) -> list:
        """Unsupported probes joined into stretches where they touch, each with
        its length, height above the bed, middle and faces; the short ones left out."""
        groups = []
        for point, length, faces in loose:
            near = [g for g in groups if min(math.dist(point, p) for p, _, _ in g) <= 2 * self._EDGE_SAMPLE_MM]
            merged = [(point, length, faces)] + [probe for g in near for probe in g]
            groups = [g for g in groups if g not in near] + [merged]
        found = []
        for group in groups:
            middle = [sum(p[i] for p, _, _ in group) / len(group) for i in range(3)]
            found.append(
                {
                    "length_mm": round(sum(length for _, length, _ in group), 2),
                    "height_mm": round(min(height(p) for p, _, _ in group) - bed, 3),
                    "at_mm": [round(c, 3) for c in middle],
                    "faces": sorted(set().union(*(faces for _, _, faces in group))),
                }
            )
        return sorted((s for s in found if s["length_mm"] >= self._EDGE_MIN_STRETCH_MM), key=lambda s: -s["length_mm"])

    @staticmethod
    def _triangle_samples(a, b, c, spacing) -> list:
        """Points inside triangle abc such that every spot of it lies within
        `spacing` of one: columns across its longest edge, each filled up to the
        triangle's height there. As many as its size needs, so a long sliver of
        a curved face gets one row, not a grid of its length squared (7225
        points for a 67.6 x 0.2 mm sliver). Pure, unit-tested."""
        a, b, c = max(((a, b, c), (b, c, a), (c, a, b)), key=lambda t: math.dist(t[0], t[1]))  # a-b longest
        length = math.dist(a, b)
        along = [(q - p) / length for p, q in zip(a, b)] if length else None
        foot = sum((r - p) * e for p, r, e in zip(a, c, along)) if along else 0.0  # within a-b: it is the longest
        up = [r - p - foot * e for p, r, e in zip(a, c, along)] if along else [0.0] * 3
        height = math.hypot(*up)
        if not height:
            return [[(p + q + r) / 3 for p, q, r in zip(a, b, c)]]
        up = [u / height for u in up]
        columns = math.ceil(length / spacing)
        points = []
        for j in range(columns):
            x = (j + 0.5) * length / columns
            top = height * (x / foot if x <= foot else (length - x) / (length - foot))
            rows = max(1, math.ceil(top / spacing))
            for k in range(rows):
                y = (k + 0.5) * top / rows
                points.append([p + x * e + y * u for p, e, u in zip(a, along, up)])
        return points

    @classmethod
    def _wall_samples(cls, triangles, min_wall_mm) -> tuple:
        """(index, point, normal) spread over every face about min_wall_mm apart,
        at most _MAX_WALL_SAMPLES of them, and the spacing they keep: one batch
        of over a million rays hung SolidWorks. Pure, unit-tested."""
        area = sum(cls._triangle_area(a, b, c) for _, a, b, c, _ in triangles)
        spacing = max(min_wall_mm, math.sqrt(2 * area / cls._MAX_WALL_SAMPLES))
        samples = [
            (index, point, normal)
            for index, a, b, c, normal in triangles
            for point in cls._triangle_samples(a, b, c, spacing)
        ]
        stride = math.ceil(len(samples) / cls._MAX_WALL_SAMPLES)  # every stride-th: still spread over all faces
        return samples[::stride], spacing * math.sqrt(stride)

    def _thin_walls(self, body, triangles, min_wall_mm) -> dict:
        """Wall thickness straight through the material from sample points on
        every face, and the faces thinner than min_wall_mm. The rays go in
        batches that each spread over all faces, until _WALL_TIME_S has
        passed; `rays` says how many were measured of how many planned."""
        samples, spacing = self._wall_samples(triangles, min_wall_mm)
        batches = max(1, math.ceil(len(samples) / self._WALL_BATCH_RAYS))
        began, through, measured = time.monotonic(), {}, 0
        for batch in range(batches):
            if batch and time.monotonic() - began > self._WALL_TIME_S:
                break
            chosen = samples[batch::batches]
            starts = [
                mm_to_m(p - 1e-4 * n) for _, point, normal in chosen for p, n in zip(point, normal)
            ]  # just inside the material
            directions = [-n for _, _, normal in chosen for n in normal]
            for ray, depth, leaving in self._ray_hits(body, starts, directions):
                if not leaving:
                    continue  # a sample on a hollow face's facet starts in the air and enters first
                index, point, _ = chosen[ray]
                if 1e-3 < depth < through.get(index, (math.inf,))[0]:
                    through[index] = (depth, point)
            measured += len(chosen)
        if not through:
            raise SolidWorksError("No ray came out of the part: the wall thickness could not be measured.")
        thin = [
            {"index": index, "thinnest_mm": round(depth, 3), "at_mm": [round(c, 3) for c in point]}
            for index, (depth, point) in sorted(through.items())
            if depth < min_wall_mm - 1e-6
        ]
        rays = {"measured": measured, "planned": len(samples)}
        if measured < len(samples):
            rays["note"] = (
                f"Stopped after {self._WALL_TIME_S:g} s, with {measured} of {len(samples)} "
                "rays spread over all faces: a thin spot between them may be missed. A larger "
                "min_wall_mm plans fewer rays."
            )
        return {
            "min_wall_mm": min_wall_mm,
            "thinnest_mm": round(min(d for d, _ in through.values()), 3),
            "sample_spacing_mm": round(spacing * math.sqrt(len(samples) / measured), 3),
            "rays": rays,
            "faces": thin,
        }

    def _ray_hits(self, body, starts, directions) -> list:
        """Cast rays (starts in m, unit directions) at the body in one call:
        (ray, distance in mm, whether it leaves the material there) per hit."""
        model = self._model
        hits = model.RayIntersections(
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [body._oleobj_]),
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, starts),
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, directions),
            SW_RAY_NORMALS_ENTRY_EXIT,
            0.0,
            0.0,
        )
        points = model.GetRayIntersectionsPoints() if hits else ()
        found = []
        for h in range(hits):
            row = points[h * RAY_HIT_WIDTH : (h + 1) * RAY_HIT_WIDTH]
            ray = int(row[1])
            found.append(
                (ray, m_to_mm(math.dist(row[3:6], starts[3 * ray : 3 * ray + 3])), bool(int(row[2]) & SW_RAY_HIT_EXIT))
            )
        return found
