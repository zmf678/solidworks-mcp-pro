"""STL/3MF sectioning and part-to-mesh comparison.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import os
import tempfile
import uuid

from ..errors import SolidWorksError
from ..mesh_tools import compare_sections, load_mesh, section


class MeshIOMixin:
    """STL/3MF sectioning and part-to-mesh comparison."""

    def slice_mesh(self, path: str, axis: str, heights_mm: list, frame: str = "object") -> dict:
        """Cross-sections of an STL or 3MF mesh at the given heights along axis.

        Each section lists its closed loops, largest first (the outline, then
        holes and pockets), as polygon points (mm): (y, z) across x, (x, z)
        across y, (x, y) across z. Only exactly collinear points are dropped, so
        the loops are ready to use as profiles. frame (3MF): 'object' = the
        mesh's own modelling frame, 'build' = as placed on the slicer's plate.
        No SolidWorks needed.
        """
        triangles = load_mesh(path, frame)
        sections = [
            {"height_mm": h, "loops": [self._loop_entry(loop, True) for loop in section(triangles, axis, h)]}
            for h in heights_mm
        ]
        return {"ok": True, "axis": axis, "frame": frame, "sections": sections}

    def _part_triangles(self) -> list:
        """The current part as triangles in its own model frame (mm), via a fine STL export."""
        path = os.path.join(tempfile.gettempdir(), f"solidworks_mcp_{uuid.uuid4().hex}.stl")
        try:
            self.export(path, quality="fine")
            return load_mesh(path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def compare_with_mesh(
        self, path: str, axis: str, heights_mm: list, frame: str = "object", offset_mm: list | None = None
    ) -> dict:
        """Slice the current part and a reference mesh at the same heights; compare.

        The mesh is moved by offset_mm ([dx, dy, dz]) into the part's frame
        first. Each reference loop is paired with the nearest loop of the part:
        a different area means a misread feature, equal areas with different
        extents a shifted frame. The part is measured through a fine STL, so
        curved walls differ by up to the tessellation's chord error.
        """
        self._require_part()
        offset = [0.0, 0.0, 0.0] if offset_mm is None else [float(v) for v in offset_mm]
        if len(offset) != 3:
            raise SolidWorksError(f"offset_mm needs [dx, dy, dz] (got {offset_mm}).")
        reference = [tuple(tuple(c + o for c, o in zip(v, offset)) for v in tri) for tri in load_mesh(path, frame)]
        part = self._part_triangles()
        sections, worst_extent, worst_area = [], 0.0, 0.0
        for h in heights_mm:
            compared = compare_sections(section(reference, axis, h), section(part, axis, h))
            for pair in compared["pairs"]:
                worst_extent = max(worst_extent, pair["max_extent_diff_mm"])
                worst_area = max(worst_area, abs(pair["area_diff_mm2"]))
            sections.append({"height_mm": h, **compared})
        return {
            "ok": True,
            "axis": axis,
            "sections": sections,
            "worst_extent_diff_mm": round(worst_extent, 4),
            "worst_area_diff_mm2": round(worst_area, 4),
        }
