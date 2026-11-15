"""STEP/STL/3MF export, screenshots and drawings.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import itertools
import math
import os

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    DRAWING_FORMATS,
    EXPORT_FORMATS,
    SW_DOC_ASSEMBLY,
    SW_DWG_PAPER_A4,
    SW_IMPORT_ENTIRE_MODEL,
    SW_INSERT_DIMENSIONS,
    SW_PREF_DEFAULT_TEMPLATE_DRAWING,
    SW_SAVE_AS_CURRENT_VERSION,
    SW_SAVE_AS_OPTIONS_SILENT,
    SW_STL_ANGLE_TOLERANCE,
    SW_STL_DEVIATION,
    SW_STL_QUALITY,
    SW_STL_QUALITY_COARSE,
    SW_STL_QUALITY_CUSTOM,
    SW_STL_QUALITY_FINE,
    SW_TOGGLE_DISPLAY_AXES,
    SW_TOGGLE_DISPLAY_PLANES,
    SW_TOGGLE_STL_DONT_TRANSLATE,
    SW_TOGGLE_STL_ONE_FILE,
    VIEWS,
)
from ..errors import SolidWorksError
from ..units import deg_to_rad, mm_to_m


class ExportIOMixin:
    """STEP/STL/3MF export, screenshots and drawings."""

    def _apply_stl_resolution(self, quality: str, deviation_mm, angle_deg) -> dict:
        """Set the global STL/3MF tessellation prefs; return the prior values.

        quality 'coarse'|'fine'; or pass deviation_mm (+ optional angle_deg) for a
        reproducible Custom resolution (overrides quality). Caller MUST restore the
        returned values afterwards -- these are application-wide preferences.
        """
        if deviation_mm is not None and deviation_mm <= 0:
            raise SolidWorksError(f"deviation_mm must be > 0 (got {deviation_mm}).")
        if angle_deg is not None and angle_deg <= 0:
            raise SolidWorksError(f"angle_deg must be > 0 (got {angle_deg}).")
        levels = {"coarse": SW_STL_QUALITY_COARSE, "fine": SW_STL_QUALITY_FINE}
        if deviation_mm is None and quality not in levels:
            raise SolidWorksError(f"quality must be 'coarse' or 'fine' (got '{quality}').")

        sw = self._sw
        old = {
            "quality": sw.GetUserPreferenceIntegerValue(SW_STL_QUALITY),
            "deviation": sw.GetUserPreferenceDoubleValue(SW_STL_DEVIATION),
            "angle": sw.GetUserPreferenceDoubleValue(SW_STL_ANGLE_TOLERANCE),
        }
        if deviation_mm is not None:
            sw.SetUserPreferenceIntegerValue(SW_STL_QUALITY, SW_STL_QUALITY_CUSTOM)
            sw.SetUserPreferenceDoubleValue(SW_STL_DEVIATION, mm_to_m(deviation_mm))
            if angle_deg is not None:
                sw.SetUserPreferenceDoubleValue(SW_STL_ANGLE_TOLERANCE, deg_to_rad(angle_deg))
        else:
            sw.SetUserPreferenceIntegerValue(SW_STL_QUALITY, levels[quality])
        return old

    def _restore_stl_resolution(self, old: dict) -> None:
        """Restore STL prefs saved by _apply_stl_resolution (no lasting side effect)."""
        sw = self._sw
        sw.SetUserPreferenceIntegerValue(SW_STL_QUALITY, old["quality"])
        sw.SetUserPreferenceDoubleValue(SW_STL_DEVIATION, old["deviation"])
        sw.SetUserPreferenceDoubleValue(SW_STL_ANGLE_TOLERANCE, old["angle"])

    def export(
        self,
        path: str,
        file_format: str | None = None,
        quality: str = "fine",
        deviation_mm: float | None = None,
        angle_deg: float | None = None,
        per_component: bool = False,
    ) -> dict:
        """Export the current part (STEP/STL/IGES/Parasolid/3MF/image) via SaveAs3.

        Silent (no overwrite prompt). Success is verified by checking the file
        actually appears on disk, because SaveAs3's return code is unreliable.

        For STL/3MF, tessellation resolution is applied first (and restored after):
        quality 'coarse'|'fine' (default 'fine' for print quality), or pass
        deviation_mm (+ optional angle_deg) for a reproducible Custom resolution
        (overrides quality). Ignored for STEP/IGES/Parasolid/images. An
        assembly goes to STL as one file, or with per_component=True as one file
        per component next to `path`; `files` lists what was written. A mesh
        keeps the document's coordinates (`frame`: 'part' or 'assembly', also
        per component), where SolidWorks would move an STL to positive space.
        """
        model = self._require_model()
        fmt = (file_format or os.path.splitext(path)[1].lstrip(".")).lower()
        if fmt not in EXPORT_FORMATS:
            raise SolidWorksError(f"Unknown export format '{fmt}'. Allowed: {sorted(EXPORT_FORMATS)}.")
        assembly_stl = fmt == "stl" and int(model.GetType()) == SW_DOC_ASSEMBLY
        if per_component and not assembly_stl:
            raise SolidWorksError("per_component is for an assembly exported to STL.")
        abs_path = os.path.abspath(path)
        result = {"ok": True, "path": abs_path, "format": fmt}
        files = [abs_path]
        if fmt in self._MESH_EXPORT_FORMATS:
            old = self._apply_stl_resolution(quality, deviation_mm, angle_deg)
            together = self._sw.GetUserPreferenceToggle(SW_TOGGLE_STL_ONE_FILE)
            in_place = self._sw.GetUserPreferenceToggle(SW_TOGGLE_STL_DONT_TRANSLATE)
            try:
                # a mesh measured back, or files per component, must line up with the model
                self._sw.SetUserPreferenceToggle(SW_TOGGLE_STL_DONT_TRANSLATE, True)
                if assembly_stl:  # SolidWorks' own setting would decide, and the user's may be per part
                    self._sw.SetUserPreferenceToggle(SW_TOGGLE_STL_ONE_FILE, not per_component)
                if per_component:
                    files = self._write_stl_per_component(abs_path)
                else:
                    self._write_via_saveas3(abs_path)
            finally:
                self._sw.SetUserPreferenceToggle(SW_TOGGLE_STL_DONT_TRANSLATE, in_place)
                self._sw.SetUserPreferenceToggle(SW_TOGGLE_STL_ONE_FILE, together)
                self._restore_stl_resolution(old)
            result["resolution"] = "custom" if deviation_mm is not None else quality
            result["frame"] = "assembly" if int(model.GetType()) == SW_DOC_ASSEMBLY else "part"
        else:
            self._write_via_saveas3(abs_path)
        result["files"] = files
        result["bytes"] = sum(os.path.getsize(f) for f in files)
        return result

    def _write_stl_per_component(self, abs_path: str) -> list:
        """SaveAs3 the assembly to STL one file per component; return the files
        that appeared or changed in the folder (SolidWorks names them itself)."""
        folder = os.path.dirname(abs_path)
        os.makedirs(folder, exist_ok=True)

        def stl_files():
            return {
                os.path.join(folder, f): os.path.getmtime(os.path.join(folder, f))
                for f in os.listdir(folder)
                if f.lower().endswith(".stl")
            }

        before = stl_files()
        self._model.SaveAs3(abs_path, SW_SAVE_AS_CURRENT_VERSION, SW_SAVE_AS_OPTIONS_SILENT)
        written = sorted(f for f, mtime in stl_files().items() if before.get(f) != mtime)
        if not written:
            raise SolidWorksError(f"SolidWorks wrote no STL files into {folder}.")
        return written

    def screenshot(
        self,
        path: str,
        view: str = "iso",
        zoom_mm: list | None = None,
        show_planes: bool = False,
        from_dir: list | None = None,
    ) -> dict:
        """Screenshot of the current part or assembly to PNG/JPG/TIF.

        view: 'iso' (default), 'front', 'back', 'left', 'right', 'top' or
        'bottom'; or from_dir = [x, y, z], the direction to look from (model
        axes), e.g. [-1, 1, -1] for an iso view from behind and below, with the
        model's +y kept up. Zoomed to fit, or onto the box zoom_mm = [[x1, y1, z1],
        [x2, y2, z2]] (model mm) to judge a detail. Reference planes and axes
        are left out unless show_planes=True; the part's own setting comes back
        afterwards. Writes via the same SaveAs3 path as `export`, so the return
        shape matches: {"ok", "path", "format", "bytes"} where "format" is the
        image extension.
        """
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if ext not in {"png", "jpg", "tif"}:  # SaveAs3 to .bmp wrote nothing (returned 256)
            raise SolidWorksError(f"Screenshot extension '{ext}' is not supported (png/jpg/tif).")
        key = str(view).lower()
        if key not in VIEWS:
            raise SolidWorksError(f"Unknown view '{view}'. Use {', '.join(VIEWS)}.")
        if zoom_mm is not None and (len(zoom_mm) != 2 or any(len(corner) != 3 for corner in zoom_mm)):
            raise SolidWorksError(f"zoom_mm needs two corners [[x1, y1, z1], [x2, y2, z2]] (got {zoom_mm}).")
        rotation = None if from_dir is None else self._view_rotation(from_dir)
        # The view must draw for the picture. Kept still, as _require_model does
        # inside a tool call (here and again in export), SOLIDWORKS saved a
        # blank, all-white image: wake what is still and keep it awake.
        depth, self._quiet_depth = self._quiet_depth, 0
        self._wake_all()
        busy = self._command_in_progress(False)
        shown = {}
        try:
            model = self._require_model()
            extension = binding.wrap(model.Extension, self._mod.IModelDocExtension)
            if not show_planes:  # planes and axes run through the part and hide its shape
                for toggle in (SW_TOGGLE_DISPLAY_PLANES, SW_TOGGLE_DISPLAY_AXES):
                    shown[toggle] = bool(extension.GetUserPreferenceToggle(toggle, 0))
                    extension.SetUserPreferenceToggle(toggle, 0, False)
                model.GraphicsRedraw2()
            return self._take_screenshot(model, path, ext, key, zoom_mm, rotation)
        finally:
            for toggle, value in shown.items():
                extension.SetUserPreferenceToggle(toggle, 0, value)
            if shown:
                model.GraphicsRedraw2()
            self._command_in_progress(busy)
            self._quiet_depth = depth

    def _take_screenshot(self, model, path, ext, key, zoom_mm, rotation=None) -> dict:
        if rotation is None:
            model.ShowNamedView2("", VIEWS[key])
        else:
            mathutil = binding.wrap(self._sw.GetMathUtility(), self._mod.IMathUtility)
            data = win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_R8, [*rotation, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
            )  # no shift, scale 1
            view = binding.wrap(model.ActiveView, self._mod.IModelView)
            view.Orientation3 = binding.wrap(mathutil.CreateTransform(data), self._mod.IMathTransform)
        if zoom_mm is None:
            model.ViewZoomtofit2()
        else:
            # ViewZoomTo2 reads its corners along the screen's axes, which are
            # x, y, z only in the front view: turn the region's box first
            rotation = binding.wrap(model.ActiveView, self._mod.IModelView).Orientation3.ArrayData[:9]
            low, high = self._box_along_screen(zoom_mm, rotation)
            model.ViewZoomTo2(*(mm_to_m(c) for c in low), *(mm_to_m(c) for c in high))
        return self.export(path, ext)

    @staticmethod
    def _view_rotation(from_dir) -> tuple:
        """The Orientation3 rotation of a view looking from from_dir: its columns
        are the screen's x, y and z in model axes, z towards the viewer and the
        model's +y up; looking along y, -z or +z is up, as in SolidWorks' top
        and bottom views. Pure, unit-tested."""
        if len(from_dir) != 3 or not math.hypot(*from_dir):
            raise SolidWorksError(f"from_dir needs a direction [x, y, z] that is not zero (got {from_dir}).")
        length = math.hypot(*from_dir)
        z = [c / length for c in from_dir]
        up = [0.0, 1.0, 0.0] if abs(z[1]) < 1 - 1e-9 else [0.0, 0.0, -1.0 if z[1] > 0 else 1.0]
        along = sum(u * c for u, c in zip(up, z))
        y = [u - along * c for u, c in zip(up, z)]
        y = [c / math.hypot(*y) for c in y]
        x = [y[1] * z[2] - y[2] * z[1], y[2] * z[0] - y[0] * z[2], y[0] * z[1] - y[1] * z[0]]
        return tuple(axis[row] for row in range(3) for axis in (x, y, z))

    @staticmethod
    def _box_along_screen(corners_mm, rotation) -> tuple:
        """The box around a model-space box once turned into a view: (low, high)
        along the screen's x, y and z. rotation is the view's Orientation3, whose
        columns are the screen axes in model space; pure, unit-tested."""
        axes = [rotation[col::3] for col in range(3)]
        turned = [
            [sum(p * a for p, a in zip(corner, axis)) for axis in axes]
            for corner in itertools.product(*zip(*corners_mm))
        ]
        return [min(t[i] for t in turned) for i in range(3)], [max(t[i] for t in turned) for i in range(3)]

    def _isometric_view_name(self) -> str:
        """The part's standard isometric view by its name in SolidWorks' own
        language ('*Isometric', '*Isométrique'): the standard view that looks
        the way the isometric view does."""
        model = self._model
        screen = binding.wrap(model.ActiveView, self._mod.IModelView)

        def orientation(name=""):
            model.ShowNamedView2(name, VIEWS["iso"] if not name else -1)
            return binding.wrap(screen.Orientation3, self._mod.IMathTransform).ArrayData[:9]

        target = orientation()
        return self._standard_view_like(list(model.GetModelViewNames() or ()), orientation, target)

    @staticmethod
    def _standard_view_like(names, orientation_of, target) -> str:
        """The first standard view (its name starts with '*') whose rotation is
        `target`; pure, unit-tested."""
        for name in names:
            if name.startswith("*") and all(abs(a - b) < 1e-3 for a, b in zip(orientation_of(name), target)):
                return name
        raise SolidWorksError(f"The part has no standard isometric view among {', '.join(names)}.")

    def make_drawing(self, path: str) -> dict:
        """A 2D drawing of the current part, saved as PDF or as an editable .slddrw.

        Front, top and right views in European (first angle) projection plus an
        isometric view, on an A4 sheet at the scale SolidWorks picks, with the
        model's own dimensions, each shown once. The drawing refers to the part's
        file, so the part must have been saved; unsaved changes show in a PDF
        but not when a saved drawing is opened later.
        """
        fmt = os.path.splitext(path)[1].lstrip(".").lower()
        if fmt not in DRAWING_FORMATS:
            raise SolidWorksError(f"A drawing is saved as {' or '.join(sorted(DRAWING_FORMATS))} (got '{fmt}').")
        self._require_part()
        part_path = self._model.GetPathName()
        if not part_path:
            raise SolidWorksError("Save the part first (save_part): the drawing refers to its file.")
        template = self._sw.GetUserPreferenceStringValue(SW_PREF_DEFAULT_TEMPLATE_DRAWING)
        drawing = binding.wrap(self._sw.NewDocument(template, SW_DWG_PAPER_A4, 0.0, 0.0), self._mod.IModelDoc2)
        if drawing is None:
            raise SolidWorksError(f"SolidWorks could not start a drawing from the template '{template}'.")
        try:
            sheets = binding.wrap(drawing, self._mod.IDrawingDoc)
            if not sheets.Create1stAngleViews2(part_path):
                raise SolidWorksError("SolidWorks could not place the front, top and right views.")
            iso = binding.wrap(
                sheets.CreateDrawViewFromModelView3(part_path, self._isometric_view_name(), 0.24, 0.16, 0.0),
                self._mod.IView,
            )
            if iso is None:
                raise SolidWorksError("SolidWorks could not place the isometric view.")
            iso.UseSheetScale = True
            # DuplicateDims True leaves out repeats: each dimension in one view
            dimensions = (
                sheets.InsertModelAnnotations3(SW_IMPORT_ENTIRE_MODEL, SW_INSERT_DIMENSIONS, True, True, False, False)
                or ()
            )
            views = []
            view = binding.wrap(sheets.GetFirstView(), self._mod.IView)  # the sheet itself comes first
            view = binding.wrap(view.GetNextView(), self._mod.IView)
            while view is not None:
                views.append(view.GetName2())
                view = binding.wrap(view.GetNextView(), self._mod.IView)
            scale = binding.wrap(sheets.GetCurrentSheet(), self._mod.ISheet).GetProperties2()[2:4]
            abs_path = os.path.abspath(path)
            self._write_via_saveas3(abs_path, drawing)
        finally:
            # saved, the drawing is named after the part ('holed_box - Sheet1'),
            # so the title it started with no longer closes it (verified)
            self._sw.CloseDoc(drawing.GetTitle())
        return {
            "ok": True,
            "path": abs_path,
            "bytes": os.path.getsize(abs_path),
            "views": views,
            "dimensions": len(dimensions),
            "scale": f"{scale[0]:g}:{scale[1]:g}",
        }
