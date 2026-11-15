"""Sketch drawing, polygon preparation, constraints and free sketches.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math

import pythoncom
import win32com.client

from .. import binding, free_sketch
from ..constants import (
    SW_CONSTRAINED_CORNER_KEEP,
    SW_CONSTRAINT_RADIUS,
    SW_FULLY_CONSTRAINED,
    SW_RELATIONS_ALL,
    SW_SKETCH_ARC,
)
from ..errors import SolidWorksError
from ..sketch_constraints import MAX_DIMENSIONED_VERTICES, SketchDefiner
from ..units import m_to_mm, mm_to_m


class SketchingMixin:
    """Sketch drawing, polygon preparation, constraints and free sketches."""

    @staticmethod
    def _clean_polygon(points_mm) -> list:
        """Distinct polygon vertices as tuples, [x, y] or [x, y, z]; pure (no COM), unit-testable.

        Drops coincident consecutive points and a trailing point equal to the
        first (so open and explicitly-closed rings both work). Raises if fewer
        than 3 distinct vertices remain.
        """

        def same(a, b):
            return all(abs(p - q) < 1e-9 for p, q in zip(a, b))

        cleaned = []
        for point in points_mm:
            p = tuple(float(c) for c in point)
            if not cleaned or not same(p, cleaned[-1]):
                cleaned.append(p)
        if len(cleaned) >= 2 and same(cleaned[0], cleaned[-1]):
            cleaned.pop()  # drop an explicit closing point
        if len(cleaned) < 3:
            raise SolidWorksError(f"A profile needs at least 3 distinct points (got {len(cleaned)}).")
        return cleaned

    def _loft_section(self, section):
        """A loft profile: a cleaned polygon, or a checked round section
        {"center_mm": [x, y], "diameter_mm": d}; pure, unit-tested."""
        if not isinstance(section, dict):
            return self._clean_polygon(section)
        try:
            (cx, cy), diameter = section["center_mm"], float(section["diameter_mm"])
            centre = (float(cx), float(cy))
        except (KeyError, TypeError, ValueError):
            raise SolidWorksError(
                f'A round section is {{"center_mm": [x, y], "diameter_mm": d}} (got {section}).'
            ) from None
        if diameter <= 0:
            raise SolidWorksError(f"A round section needs a diameter > 0 (got {diameter}).")
        return {"center_mm": centre, "diameter_mm": diameter}

    @staticmethod
    def _loft_start(section) -> tuple:
        """Where a loft profile starts: +x on a round section, else the first
        vertex; pure, unit-tested."""
        if isinstance(section, dict):
            (cx, cy), diameter = section["center_mm"], section["diameter_mm"]
            return cx + diameter / 2, cy
        return tuple(section[0])

    @staticmethod
    def _check_draft(draft_deg) -> None:
        if not -90.0 < draft_deg < 90.0:
            raise SolidWorksError(f"draft_deg must be between -90 and 90 (got {draft_deg}).")

    @staticmethod
    def _turned_points(points_mm, rotate_deg, about_mm) -> list:
        """[x, y] points turned rotate_deg counterclockwise about about_mm (the
        origin when None); pure, unit-tested."""
        if not rotate_deg:
            return points_mm
        try:
            cx, cy = (0.0, 0.0) if about_mm is None else (float(about_mm[0]), float(about_mm[1]))
            pts = [(float(p[0]), float(p[1])) for p in points_mm]
        except (TypeError, ValueError, IndexError):
            raise SolidWorksError(f"rotate_deg turns [x, y] points about [x, y] (got about_mm={about_mm}).") from None
        c, s = math.cos(math.radians(rotate_deg)), math.sin(math.radians(rotate_deg))
        return [[cx + c * (x - cx) - s * (y - cy), cy + s * (x - cx) + c * (y - cy)] for x, y in pts]

    @staticmethod
    def _corner_groups(corner_radii_mm, count: int) -> list:
        """[(radius_mm, [corner indices]), ...] in corner order; pure (no COM), unit-tested.

        corner_radii_mm is None, one radius for every corner, or one per vertex
        (0 = sharp). Corners with the same radius share one dimension, the way
        vertices at the same x share one, so they form one group.
        """
        if corner_radii_mm is None:
            return []
        radii = (
            [float(corner_radii_mm)] * count
            if isinstance(corner_radii_mm, (int, float))
            else [float(r) for r in corner_radii_mm]
        )
        if len(radii) != count:
            raise SolidWorksError(
                f"corner_radii_mm has {len(radii)} values for {count} corners: give one radius for all "
                "corners, or one per vertex (0 = sharp)."
            )
        if any(r < 0 for r in radii):
            raise SolidWorksError(f"Corner radii must be >= 0 (got {radii}).")
        groups = {}
        for i, radius in enumerate(radii):
            if radius > 0:
                groups.setdefault(radius, []).append(i)
        if groups and count > MAX_DIMENSIONED_VERTICES:
            raise SolidWorksError(
                f"Corner radii need a profile of at most {MAX_DIMENSIONED_VERTICES} points (this one has "
                f"{count}): larger profiles are fixed, not dimensioned."
            )
        return sorted(groups.items(), key=lambda group: group[1][0])

    @staticmethod
    def _check_corner_radii(points, groups) -> None:
        """Fail before SolidWorks does; pure (no COM), unit-tested.

        A rounded corner sets its arc back r / tan(angle / 2) along both edges,
        so each needs a real corner and each edge room for the arcs at both its
        ends. Lengths and angles hold in 2D sketch and 3D model points alike.
        """
        n = len(points)
        setback = {}
        for radius, corners in groups:
            for i in corners:
                here = points[i]
                u = [p - h for p, h in zip(points[i - 1], here)]
                w = [p - h for p, h in zip(points[(i + 1) % n], here)]
                cos = sum(a * b for a, b in zip(u, w)) / (math.hypot(*u) * math.hypot(*w))
                angle = math.acos(max(-1.0, min(1.0, cos)))
                if angle < 1e-6 or angle > math.pi - 1e-6:
                    raise SolidWorksError(f"Corner {i} cannot be rounded: its edges are in line.")
                setback[i] = radius / math.tan(angle / 2)
        for i in range(n):
            j = (i + 1) % n
            need = setback.get(i, 0.0) + setback.get(j, 0.0)
            length = math.dist(points[i], points[j])
            if need and need > length - 1e-6:
                raise SolidWorksError(
                    f"Edge {i}-{j} is {length:g} mm long, but the corner radii at its ends need "
                    f"{need:g} mm of it. Use smaller radii."
                    + (
                        " Arcs that would meet merge into one, which the corners cannot keep: for a "
                        "circle use add_disc, for round ends add_extruded_slot, for any outline add_sketch with "
                        "tangent arcs."
                        if need < length + 1e-6
                        else ""
                    )
                )

    @staticmethod
    def _round_polyline(points_mm, radius_mm) -> list:
        """Open polyline with filleted interior corners; pure (no COM), unit-testable.

        Returns drawable segments in mm: ("line", (x1,y1), (x2,y2)) or
        ("arc", (cx,cy), (sx,sy), (ex,ey), direction) where direction is +1 (CCW)
        or -1 (CW). Each interior corner is replaced by a tangent arc of radius
        radius_mm. A straight 2-point path needs no radius; a path with corners
        requires radius_mm > 0. Raises if the radius does not fit a segment.
        """
        clean = []
        for p in points_mm:
            q = (float(p[0]), float(p[1]))
            if not clean or abs(q[0] - clean[-1][0]) > 1e-9 or abs(q[1] - clean[-1][1]) > 1e-9:
                clean.append(q)
        if len(clean) < 2:
            raise SolidWorksError(f"A path needs at least 2 distinct points (got {len(clean)}).")
        if len(clean) == 2:
            return [("line", clean[0], clean[1])]
        if radius_mm <= 0:
            raise SolidWorksError("bend_radius must be > 0 for a path with corners.")

        # Pass 1: fillet geometry per interior corner that genuinely turns.
        corners = []
        for i in range(1, len(clean) - 1):
            a, v, b = clean[i - 1], clean[i], clean[i + 1]
            ax, ay = a[0] - v[0], a[1] - v[1]
            bx, by = b[0] - v[0], b[1] - v[1]
            la, lb = math.hypot(ax, ay), math.hypot(bx, by)
            ax, ay, bx, by = ax / la, ay / la, bx / lb, by / lb
            theta = math.acos(max(-1.0, min(1.0, ax * bx + ay * by)))
            if abs(theta - math.pi) < 1e-6:
                continue  # collinear straight-through: no corner to round
            if theta < 1e-6:
                raise SolidWorksError(
                    f"The path doubles back on itself at point {i}; a sweep path cannot fold back 180 degrees."
                )
            setback = radius_mm / math.tan(theta / 2.0)
            if setback > la - 1e-9 or setback > lb - 1e-9:
                raise SolidWorksError(f"bend_radius {radius_mm} is too large for the segment at point {i}.")
            t_in = (v[0] + ax * setback, v[1] + ay * setback)
            t_out = (v[0] + bx * setback, v[1] + by * setback)
            bisx, bisy = ax + bx, ay + by
            lbis = math.hypot(bisx, bisy)
            dist_c = radius_mm / math.sin(theta / 2.0)
            c = (v[0] + bisx / lbis * dist_c, v[1] + bisy / lbis * dist_c)
            cross = (t_in[0] - c[0]) * (t_out[1] - c[1]) - (t_in[1] - c[1]) * (t_out[0] - c[0])
            corners.append(
                {"i": i, "setback": setback, "t_in": t_in, "t_out": t_out, "c": c, "dir": 1 if cross > 0 else -1}
            )

        # Pass 2: two corners sharing a segment must not both eat past its length.
        # Use the distance between corner VERTICES (collinear points between them
        # were skipped and consume no setback).
        for prev, nxt in zip(corners, corners[1:]):
            shared = math.dist(clean[prev["i"]], clean[nxt["i"]])
            if prev["setback"] + nxt["setback"] > shared - 1e-9:
                raise SolidWorksError(
                    f"bend_radius {radius_mm} is too large: the bends at points {prev['i']} and {nxt['i']} "
                    "overlap on the segment between them."
                )

        # Pass 3: emit segments, skipping any zero-length connecting line.
        segs = []
        cur = clean[0]
        for corner in corners:
            if math.dist(cur, corner["t_in"]) > 1e-9:
                segs.append(("line", cur, corner["t_in"]))
            segs.append(("arc", corner["c"], corner["t_in"], corner["t_out"], corner["dir"]))
            cur = corner["t_out"]
        segs.append(("line", cur, clean[-1]))
        return segs

    @staticmethod
    def _draw_polyline(sk, pts_m, closed: bool = True) -> list:
        """Draw CreateLine segments through 2D points in METRES; return the lines.

        The sketch must already be open; segment i runs from point i to i+1,
        and the last back to the first when closed. Shared by the +Z polygon
        path and the any-face path (which supplies transformed sketch
        coordinates). Drawn with AddToDB: otherwise SolidWorks' automatic
        relations snap a nearly horizontal/vertical segment, which silently
        moves a point and makes a closing segment fail outright. That leaves
        every relation to _define_sketch.
        """
        n = len(pts_m)
        lines = []
        sk.AddToDB = True
        try:
            for i in range(n if closed else n - 1):
                x1, y1 = pts_m[i]
                x2, y2 = pts_m[(i + 1) % n]
                line = sk.CreateLine(x1, y1, 0.0, x2, y2, 0.0)
                if not line:
                    raise SolidWorksError(f"Could not create line segment {i}.")
                lines.append(line)
        finally:
            sk.AddToDB = False
        return lines

    @staticmethod
    def _draw_circle(sk, u_m, v_m, radius_m):
        """A circle in the open sketch, drawn with AddToDB: else SolidWorks'
        inference snaps a centre near an axis or another sketch onto it (a hole
        0.75 mm below the x axis landed on it, verified)."""
        sk.AddToDB = True
        try:
            circle = sk.CreateCircleByRadius(u_m, v_m, 0.0, radius_m)
        finally:
            sk.AddToDB = False
        if not circle:
            raise SolidWorksError("Circle sketch failed: CreateCircleByRadius returned nothing.")
        return circle

    @staticmethod
    def _draw_centerline(sk, x1_m, y1_m, x2_m, y2_m):
        """A revolve axis, drawn like _draw_polyline so no automatic relation lands on it."""
        sk.AddToDB = True
        try:
            axis = sk.CreateCenterLine(x1_m, y1_m, 0.0, x2_m, y2_m, 0.0)
        finally:
            sk.AddToDB = False
        if not axis:
            raise SolidWorksError("Could not create the revolve axis (centerline).")
        return axis

    def _origin_point(self):
        """The model origin as a sketch point, found via the tree (language-independent)."""
        for feat in self._iter_features():
            if feat.GetTypeName2() == "OriginProfileFeature":
                points = binding.wrap(feat.GetSpecificFeature2(), self._mod.ISketch).GetSketchPoints2()
                if points:
                    return binding.wrap(points[0], self._mod.ISketchPoint)
        raise SolidWorksError("The part has no origin point to dimension the sketch from.")

    def _open_sketch_definer(self, sk):
        sketch = binding.wrap(sk.ActiveSketch, self._mod.ISketch)
        if sketch is None:
            raise SolidWorksError("No open sketch to define.")
        return sketch, SketchDefiner(self._model, self._mod, sk, sketch, self._origin_point())

    def _define_sketch(self, sk, lines=(), circles=(), names=None) -> dict:
        """Fully define the open sketch (see sketch_constraints).

        Returns {'dimensions': {role: 'name@Sketch3'}, 'fully_defined': bool},
        ready to merge into a tool result.
        """
        sketch, definer = self._open_sketch_definer(sk)
        u0, v0, _ = self._sketch_coords(sketch, 0.0, 0.0, 0.0)  # the origin, projected
        dims = definer.define(lines, circles, names, (m_to_mm(u0), m_to_mm(v0)))
        return {"dimensions": dims, "fully_defined": definer.fully_defined()}

    def _fix_sketch(self, sk, segments) -> dict:
        """Freeze the open sketch's segments: for paths and splines, which have no
        dimensions worth editing. Same result shape as _define_sketch."""
        _, definer = self._open_sketch_definer(sk)
        definer.fix(segments)
        return {"dimensions": {}, "fully_defined": definer.fully_defined()}

    def _sketch_closed_polygon(self, sk, points_mm, corner_radii_mm=None) -> dict:
        """Open a sketch, draw a closed polygon from [x, y] points (mm) and define it.

        Tolerant of open and explicitly-closed rings (see _clean_polygon);
        corner_radii_mm rounds its corners (see _round_corners). Returns the
        _define_sketch result.
        """
        points = self._clean_polygon(points_mm)
        corners = self._profile_corners(points, corner_radii_mm)
        sk.InsertSketch(True)
        try:
            return self._draw_defined_polygon(sk, [(mm_to_m(x), mm_to_m(y)) for x, y in points], corners)
        finally:
            self._model.ClearSelection2(True)
            sk.InsertSketch(True)  # close the sketch, also when drawing failed

    def _profile_corners(self, points_mm, corner_radii_mm) -> tuple:
        """Check a profile's corner radii before any sketch opens, so a refused
        radius leaves nothing behind. Returns (vertex count, corner groups)."""
        points = self._clean_polygon(points_mm)
        groups = self._corner_groups(corner_radii_mm, len(points))
        self._check_corner_radii(points, groups)
        return len(points), groups

    def _draw_defined_polygon(self, sk, polygon_m, corners) -> dict:
        """Draw the cleaned polygon (sketch coordinates, metres) in the open
        sketch, fully define it and round its corners."""
        count, groups = corners
        if groups and len(polygon_m) != count:
            raise SolidWorksError(
                "Two profile points lie within a micrometre of each other: remove one, so each corner "
                "radius lands on its own corner."
            )
        lines = self._draw_polyline(sk, polygon_m)
        return self._round_corners(sk, lines, groups, self._define_sketch(sk, lines))

    def _round_corners(self, sk, lines, groups, defined: dict) -> dict:
        """Round corners of the open, fully defined polygon with sketch fillets.

        Each corner keeps its dimensions as a virtual sharp. One fillet call per
        group of equal radii: SolidWorks gives it one radius dimension and ties
        the group with equal relations. Returns `defined` plus that dimension,
        named 'radius' when every rounded corner shares it, else 'r<i>' after
        the group's first corner.
        """
        if not groups:
            return defined
        sketch = binding.wrap(sk.ActiveSketch, self._mod.ISketch)
        corners = [
            binding.wrap(binding.wrap(line, self._mod.ISketchLine).GetStartPoint2(), self._mod.ISketchPoint)
            for line in lines
        ]
        dimensions = dict(defined["dimensions"])
        for radius, indices in groups:
            radii_before = {d.GetNameForSelection() for d in self._radius_dimensions(sketch)}
            arcs_before = self._arc_count(sketch)
            self._model.ClearSelection2(True)
            if not all(corners[i].Select4(k > 0, None) for k, i in enumerate(indices)):
                raise SolidWorksError(f"Could not select corner(s) {indices} to round.")
            if sk.CreateFillet(mm_to_m(radius), SW_CONSTRAINED_CORNER_KEEP) is None:
                raise SolidWorksError(f"SolidWorks could not round corner(s) {indices} with R{radius:g}.")
            rounded = self._arc_count(sketch) - arcs_before
            new = [d for d in self._radius_dimensions(sketch) if d.GetNameForSelection() not in radii_before]
            if rounded != len(indices) or len(new) != 1:
                raise SolidWorksError(
                    f"Rounding corner(s) {indices} with R{radius:g} gave {rounded} arc(s) and {len(new)} "
                    "radius dimension(s); expected one arc per corner and one dimension."
                )
            role = "radius" if len(groups) == 1 else f"r{indices[0]}"
            new[0].Name = role
            dimensions[role] = new[0].GetNameForSelection()
        self._model.ClearSelection2(True)
        return {"dimensions": dimensions, "fully_defined": sketch.GetConstrainedStatus() == SW_FULLY_CONSTRAINED}

    def _radius_dimensions(self, sketch) -> list:
        """The sketch's radius dimensions (IDimension), found through their relations."""
        relations = binding.wrap(sketch.RelationManager, self._mod.ISketchRelationManager)
        found = []
        for relation_dispatch in relations.GetRelations(SW_RELATIONS_ALL) or ():
            relation = binding.wrap(relation_dispatch, self._mod.ISketchRelation)
            if relation.GetRelationType() == SW_CONSTRAINT_RADIUS:
                display = binding.wrap(relation.GetDisplayDimension(), self._mod.IDisplayDimension)
                found.append(binding.wrap(display.GetDimension2(0), self._mod.IDimension))
        return found

    def _arc_count(self, sketch) -> int:
        return sum(
            1
            for segment in sketch.GetSketchSegments() or ()
            if binding.wrap(segment, self._mod.ISketchSegment).GetType() == SW_SKETCH_ARC
        )

    def _open_face_sketch(self, sk, face: str):
        """Open a sketch on the already-selected face and return it (never None).

        Callers must close it in a `finally`: a sketch left open after a rejected
        point makes the NEXT InsertSketch close it instead of opening a new one,
        so one loud failure would break the following operation too.
        """
        sk.InsertSketch(True)
        sketch = binding.wrap(sk.ActiveSketch, self._mod.ISketch)
        if sketch is None:
            raise SolidWorksError(
                f"Could not open a sketch on the {face} face (InsertSketch gave no active sketch). "
                "Was a sketch left open by an earlier failed operation?"
            )
        return sketch

    def _select_planar_face(self, body, normal, label: str, side: str = "outer"):
        """Select the outermost (default) or innermost planar face facing `normal`."""
        face = self._planar_face_by_normal(body, normal, side)
        if face is None:
            raise SolidWorksError(f"No planar {label} face found.")
        self._model.ClearSelection2(True)
        if not binding.wrap(face, self._mod.IEntity).Select4(False, None):
            raise SolidWorksError(f"Could not select the {label} face.")
        return face

    def add_sketch(self, plane: str, start_mm: list, segments: list, name: str | None = None) -> dict:
        """Draw a chain of lines, arcs and splines on a plane, fully defined (see
        free_sketch): smooth joints get tangent relations, the rest dimensions
        from the origin. Returns the sketch's name for extrude_sketch / cut_sketch,
        its dimensions, the points given (x<i>/y<i> number them) and the plane's
        frame: [u, v] lies at origin_mm + u x_axis + v y_axis."""
        model = self._require_model()
        self._require_part()
        chain = free_sketch.build_chain(start_mm, segments)
        plan = free_sketch.plan_chain(chain)
        if not plan.fully_defined:
            raise SolidWorksError("Could not work out the relations and dimensions for this sketch.")
        ref, label = self._named_plane(plane)
        frame = self._plane_frame(ref)
        model.ClearSelection2(True)
        if not ref.Select2(False, 0):
            raise SolidWorksError(f"Could not select the {label}.")
        before = self._profile_feature_names()
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sk.InsertSketch(True)
        try:
            drawn = self._draw_chain(sk, chain)
            sketch, definer = self._open_sketch_definer(sk)
            dimensions = definer.define_chain(plan, drawn, self._chain_sketch_points(drawn, chain))
            fully_defined = definer.fully_defined()
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)
        new_names = self._profile_feature_names() - before
        if len(new_names) != 1:
            raise SolidWorksError(f"Could not identify the sketch just drawn (found {len(new_names)} new sketches).")
        sketch_name = new_names.pop()
        if name:
            feature = self._history_feature(sketch_name)
            feature.Name = name
            sketch_name = feature.Name
            dimensions = {role: f"{dim.split('@')[0]}@{sketch_name}" for role, dim in dimensions.items()}
        if not fully_defined:
            raise SolidWorksError(f"{sketch_name} came out under- or over-defined; this is a bug, please report it.")
        return {
            "ok": True,
            "sketch": sketch_name,
            "closed": chain.closed,
            "points_mm": [[round(c, 6) for c in chain.points[i]] for i in chain.user_points],
            "dimensions": dimensions,
            "fully_defined": True,
            "origin_mm": frame["origin_mm"],
            "x_axis": frame["x_axis"],
            "y_axis": frame["y_axis"],
        }

    @staticmethod
    def _draw_chain(sk, chain) -> list:
        """Draw the chain's segments in the open sketch, with AddToDB so that no
        automatic relation moves them; consecutive segments share their points."""
        drawn = []
        sk.AddToDB = True
        try:
            for k, entity in enumerate(chain.entities):
                if entity[0] == "line":
                    (u1, v1), (u2, v2) = chain.points[entity[1]], chain.points[entity[2]]
                    segment = sk.CreateLine(mm_to_m(u1), mm_to_m(v1), 0.0, mm_to_m(u2), mm_to_m(v2), 0.0)
                elif entity[0] == "arc":
                    (su, sv), (eu, ev), (cu, cv) = (chain.points[i] for i in entity[1:4])
                    segment = sk.CreateArc(
                        mm_to_m(cu),
                        mm_to_m(cv),
                        0.0,
                        mm_to_m(su),
                        mm_to_m(sv),
                        0.0,
                        mm_to_m(eu),
                        mm_to_m(ev),
                        0.0,
                        entity[4],
                    )
                else:
                    coords = [mm_to_m(c) for i in entity[1] for c in (*chain.points[i], 0.0)]
                    segment = sk.CreateSpline2(
                        win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, coords), False
                    )
                if not segment:
                    raise SolidWorksError(f"SolidWorks could not draw segment {k} ({entity[0]}).")
                drawn.append(segment)
        finally:
            sk.AddToDB = False
        return drawn

    def _chain_sketch_points(self, drawn, chain) -> dict:
        """chain point -> the sketch points SolidWorks made there, matched by position."""
        found = {}
        for entity, segment in zip(chain.entities, drawn):
            if entity[0] == "line":
                line = binding.wrap(segment, self._mod.ISketchLine)
                candidates = [line.GetStartPoint2(), line.GetEndPoint2()]
            elif entity[0] == "arc":
                arc = binding.wrap(segment, self._mod.ISketchArc)
                candidates = [arc.GetStartPoint2(), arc.GetEndPoint2(), arc.GetCenterPoint2()]
            else:
                candidates = list(binding.wrap(segment, self._mod.ISketchSpline).GetPoints2() or ())
            for candidate in candidates:
                point = binding.wrap(candidate, self._mod.ISketchPoint)
                at = (m_to_mm(point.X), m_to_mm(point.Y))
                index = next((i for i, p in enumerate(chain.points) if math.dist(p, at) <= 1e-6), None)
                if index is None:
                    raise SolidWorksError(
                        f"SolidWorks drew a point at ({at[0]:g}, {at[1]:g}) that the sketch does not have."
                    )
                twins = found.setdefault(index, [])
                if all(tuple(t.GetID()) != tuple(point.GetID()) for t in twins):
                    twins.append(point)
        missing = [chain.points[i] for i in range(len(chain.points)) if i not in found]
        if missing:
            raise SolidWorksError(f"SolidWorks did not draw the points {missing}.")
        return found

    def _plane_frame(self, plane) -> dict:
        """How a sketch on `plane` lies in the model: origin (mm), normal and the
        sketch's x and y axes as unit vectors."""
        model = self._model
        model.ClearSelection2(True)
        if not plane.Select2(False, 0):
            raise SolidWorksError(f"Could not select '{plane.Name}'.")
        sk = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        sketch = self._open_face_sketch(sk, plane.Name)
        try:
            to_model = binding.wrap(
                binding.wrap(sketch.ModelToSketchTransform, self._mod.IMathTransform).Inverse(),
                self._mod.IMathTransform,
            )
            origin = self._to_model_mm(to_model, 0.0, 0.0, 0.0)
            # a metre along each sketch axis keeps the rounded millimetres precise
            axes = [
                [round((c - o) / 1000.0, 6) + 0.0 for c, o in zip(self._to_model_mm(to_model, *unit), origin)]
                for unit in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            ]
        finally:
            model.ClearSelection2(True)
            sk.InsertSketch(True)  # an empty sketch is dropped again
        return {"origin_mm": origin, "x_axis": axes[0], "y_axis": axes[1], "normal": axes[2]}
