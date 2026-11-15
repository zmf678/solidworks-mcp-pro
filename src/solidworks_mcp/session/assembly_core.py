"""Assembly documents, components, transforms and placement.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math
import os

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    SW_ADD_COMPONENT_CURRENT_CONFIG,
    SW_BODY_SOLID,
    SW_COMPONENT_LIGHTWEIGHT_STATES,
    SW_COMPONENT_SUPPRESSED,
    SW_DELETE_ABSORBED,
    SW_DOC_ASSEMBLY,
    SW_DOC_PART,
    SW_OPEN_DOC_SILENT,
    SW_PREF_DEFAULT_TEMPLATE_ASSEMBLY,
)
from ..errors import SolidWorksError
from ..units import deg_to_rad, m_to_mm, mm_to_m
from ._decorators import _reads_only


class AssemblyCoreMixin:
    """Assembly documents, components, transforms and placement."""

    def new_assembly(self) -> dict:
        """Create a new empty assembly; it becomes the current document."""
        sw = self._ensure()
        template = sw.GetUserPreferenceStringValue(SW_PREF_DEFAULT_TEMPLATE_ASSEMBLY)
        model = None
        if template and os.path.isfile(template):
            model = binding.wrap(sw.NewDocument(template, 0, 0, 0), self._mod.IModelDoc2)
        if model is None:
            # Fallback avoids a "template not found" modal dialog, as new_part does.
            model = binding.wrap(sw.NewAssembly(), self._mod.IModelDoc2)
        if model is None:
            raise SolidWorksError("Could not create a new assembly (template and NewAssembly both failed).")
        self._model = model
        return {"ok": True, "title": model.GetTitle()}

    def open_assembly(self, path: str, allow_large: bool = False) -> dict:
        """Open an existing .sldasm, or import a STEP, IGES or Parasolid assembly;
        it becomes the current document. An import reports its component count;
        one over _IMPORT_LIMIT_MB is refused unless allow_large."""
        abs_path, imported = self._native_or_neutral(path, "sldasm", "an assembly", allow_large)
        sw = self._ensure()
        if imported:
            self._model = self._import_document(sw, abs_path, SW_DOC_ASSEMBLY)
            return {
                "ok": True,
                "title": self._model.GetTitle(),
                "path": abs_path,
                "imported": True,
                "components": len(self._components(self._require_assembly())),
            }
        result = sw.OpenDoc6(abs_path, SW_DOC_ASSEMBLY, SW_OPEN_DOC_SILENT, "", 0, 0)
        doc = result[0] if isinstance(result, tuple) else result
        model = binding.wrap(doc, self._mod.IModelDoc2)
        if model is None:
            raise SolidWorksError(f"Could not open the assembly: {abs_path}")
        self._model = model
        return {"ok": True, "title": model.GetTitle(), "path": abs_path}

    def save_assembly(self, path: str) -> dict:
        """Save the current assembly to a native .sldasm file (silent)."""
        self._require_assembly()
        abs_path = os.path.abspath(path)
        if not abs_path.lower().endswith(".sldasm"):
            abs_path += ".sldasm"
        self._write_via_saveas3(abs_path)
        return {"ok": True, "path": abs_path, "bytes": os.path.getsize(abs_path)}

    @staticmethod
    def _rotation_columns(rx_deg: float, ry_deg: float, rz_deg: float) -> list:
        """R = Rz*Ry*Rx as SolidWorks' COLUMN-major 9-float array; pure (no COM).

        Rotations are applied X first, then Y, then Z, about the assembly axes,
        and act on the component's own origin (p_assembly = R * p_part + t).
        """
        a, b, c = deg_to_rad(rx_deg), deg_to_rad(ry_deg), deg_to_rad(rz_deg)
        ca, sa = math.cos(a), math.sin(a)
        cb, sb = math.cos(b), math.sin(b)
        cc, sc = math.cos(c), math.sin(c)
        rows = [
            [cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa],
            [sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa],
            [-sb, cb * sa, cb * ca],
        ]
        return [rows[row][col] for col in range(3) for row in range(3)]

    @staticmethod
    def _euler_from_columns(columns) -> tuple:
        """Inverse of _rotation_columns -> (rx, ry, rz) in degrees; pure (no COM).

        At ry = +/-90 degrees the X and Z rotations become the same motion
        (gimbal lock); there we report rz = 0 and fold the whole rotation into
        rx, which still reproduces the matrix.
        """
        r = [[columns[col * 3 + row] for col in range(3)] for row in range(3)]
        ry = math.asin(max(-1.0, min(1.0, -r[2][0])))
        if abs(r[2][0]) > 1.0 - 1e-9:  # cos(ry) ~ 0: gimbal lock
            rx, rz = math.atan2(-r[1][2], r[1][1]), 0.0
        else:
            rx, rz = math.atan2(r[2][1], r[2][2]), math.atan2(r[1][0], r[0][0])
        return tuple(round(math.degrees(v), 6) for v in (rx, ry, rz))

    def _make_transform(self, x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg):
        """Build an IMathTransform from a position (mm) and XYZ rotations (deg)."""
        data = self._rotation_columns(rx_deg, ry_deg, rz_deg) + [
            mm_to_m(x_mm),
            mm_to_m(y_mm),
            mm_to_m(z_mm),
            1.0,  # uniform scale
            0.0,
            0.0,
            0.0,  # unused
        ]
        mathutil = binding.wrap(self._sw.GetMathUtility(), self._mod.IMathUtility)
        coords = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, data)
        xform = binding.wrap(mathutil.CreateTransform(coords), self._mod.IMathTransform)
        if xform is None:
            raise SolidWorksError("CreateTransform returned None; could not build a transform.")
        return xform

    def _transform_data(self, comp) -> list:
        """The component's transform as the raw 16-float ArrayData."""
        xform = binding.wrap(comp.Transform2, self._mod.IMathTransform)
        if xform is None:
            raise SolidWorksError(f"Component '{comp.Name2}' has no readable transform.")
        return list(xform.ArrayData)

    def _placement(self, comp) -> dict:
        """Where a component sits: position (mm) + XYZ rotation (deg)."""
        data = self._transform_data(comp)
        rx, ry, rz = self._euler_from_columns(data[:9])
        return {
            "position_mm": [round(m_to_mm(v), 4) for v in data[9:12]],
            "rotation_deg": [rx, ry, rz],
        }

    def _apply_transform(self, comp, x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg) -> dict:
        """Write a component transform, then read it back and verify it stuck.

        A silently ignored transform is exactly the failure this repo refuses to
        pass on, so the written matrix is compared element by element with what
        SolidWorks reports afterwards.
        """
        wanted = self._rotation_columns(rx_deg, ry_deg, rz_deg) + [mm_to_m(x_mm), mm_to_m(y_mm), mm_to_m(z_mm)]
        comp.Transform2 = self._make_transform(x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg)
        got = self._transform_data(comp)[:12]
        for i, (want, have) in enumerate(zip(wanted, got)):
            tol = self._ROTATION_TOLERANCE if i < 9 else mm_to_m(self._TRANSFORM_TOLERANCE_MM)
            if abs(want - have) > tol:
                raise SolidWorksError(
                    f"The transform of '{comp.Name2}' was not applied: requested position "
                    f"({x_mm:g}, {y_mm:g}, {z_mm:g}) mm, rotation ({rx_deg:g}, {ry_deg:g}, "
                    f"{rz_deg:g}) degrees; read-back position "
                    f"{[round(m_to_mm(v), 4) for v in got[9:12]]} mm. Element {i} is off by "
                    f"{abs(want - have):.3e}. Does an existing mate already constrain this component?"
                )
        return self._placement(comp)

    def _component_dispatches(self, asm) -> list:
        """Top-level components of the assembly, as raw dispatches (never None)."""
        comps = asm.GetComponents(True)
        if not comps:
            return []
        return list(comps) if isinstance(comps, (list, tuple)) else [comps]

    def _components(self, asm) -> list:
        """Top-level components as early-bound IComponent2, in tree order."""
        return [binding.wrap(c, self._mod.IComponent2) for c in self._component_dispatches(asm)]

    def _component_by_name(self, asm, name: str):
        """Resolve a component by instance name ('Bed-1') or part name ('Bed'),
        or one inside a sub-assembly by its path ('Leg-1/Thigh-1').

        The short form is accepted only while it is unambiguous; with two copies
        inserted it raises and lists the instance names instead of guessing.
        """
        key = (name or "").strip().lower()
        if not key:
            raise SolidWorksError("Give a component name.")
        if "/" in key:  # SolidWorks names a component inside a sub-assembly by its path
            inside = self._nested_components(self._components(asm))
            found = [c for c in inside if c.Name2.lower() == key]
            if len(found) == 1:
                return found[0]
            raise SolidWorksError(
                f"Component '{name}' not found. Inside the sub-assemblies: "
                f"{[c.Name2 for c in inside if '/' in c.Name2]}."
            )
        comps = self._components(asm)
        exact = [c for c in comps if c.Name2.lower() == key]
        if len(exact) == 1:
            return exact[0]
        prefixed = [c for c in comps if c.Name2.lower().startswith(key + "-")]
        if len(prefixed) == 1:
            return prefixed[0]
        if len(prefixed) > 1:
            raise SolidWorksError(
                f"Component name '{name}' is not unique; candidates: {sorted(c.Name2 for c in prefixed)}."
            )
        raise SolidWorksError(f"Component '{name}' not found. Present: {[c.Name2 for c in comps]}.")

    def _component_box(self, comp) -> dict | None:
        """The component's tight bounding box in ASSEMBLY coordinates (mm), or
        None when it holds no solid material (suppressed, or surfaces only).

        IComponent2.GetBox boxes the component's own box, turned with it: too
        big for a rotated round or slanted part (an arm was reported reaching
        y = 0 while it ended at -4.7). So each solid body's extreme points along
        the assembly axes are found in its part's frame and mapped through that
        part's transform; a sub-assembly joins the boxes of its parts.
        """
        return self._joined_box([self._part_box(part) for part in self._solid_parts(comp)])

    def _part_box(self, part) -> dict | None:
        bodies = self._solid_bodies(part)
        if not bodies:
            return None
        rotation, shift, scale = self._frame(part)
        low, high = [math.inf] * 3, [-math.inf] * 3
        for body in bodies:
            for axis in range(3):
                for sign in (1.0, -1.0):
                    # the assembly axis seen from the part: row `axis` of R (R transposed)
                    point = self._extreme_point(body, [sign * c for c in rotation[axis]])
                    coordinate = scale * sum(r * p for r, p in zip(rotation[axis], point)) + shift[axis]
                    low[axis], high[axis] = min(low[axis], coordinate), max(high[axis], coordinate)
        return self._joined_box(
            [{"min_mm": [round(m_to_mm(v), 4) for v in low], "max_mm": [round(m_to_mm(v), 4) for v in high]}]
        )

    @staticmethod
    def _joined_box(boxes) -> dict | None:
        """The box around `boxes` (min_mm / max_mm); None entries hold nothing."""
        boxes = [box for box in boxes if box]
        if not boxes:
            return None
        low = [min(box["min_mm"][axis] for box in boxes) for axis in range(3)]
        high = [max(box["max_mm"][axis] for box in boxes) for axis in range(3)]
        return {
            "min_mm": low,
            "max_mm": high,
            "size_mm": [round(high_value - low_value, 4) for low_value, high_value in zip(low, high)],
        }

    def _nested_components(self, comps) -> list:
        """The components and everything inside them, at any depth."""
        out = []
        for comp in comps:
            out.append(comp)
            out += self._nested_components([binding.wrap(c, self._mod.IComponent2) for c in comp.GetChildren() or ()])
        return out

    def _part_components(self, comp) -> list:
        """comp itself when it is a part, else the parts inside it at any depth.
        A part's transform is relative to the top assembly (verified), so each
        maps straight to assembly coordinates."""
        children = comp.GetChildren() or ()
        if not children:
            return [comp]
        return [
            part for child in children for part in self._part_components(binding.wrap(child, self._mod.IComponent2))
        ]

    def _solid_parts(self, comp) -> list:
        """The parts holding comp's material. A suppressed part holds none; a
        lightweight one cannot be measured, as its geometry is not loaded."""
        parts = []
        for part in self._part_components(comp):
            state = part.GetSuppression2()
            if state in SW_COMPONENT_LIGHTWEIGHT_STATES:
                raise SolidWorksError(
                    f"Component '{part.Name2}' is lightweight: SolidWorks has not loaded its "
                    "geometry, so it cannot be measured. Set it to resolved."
                )
            if state != SW_COMPONENT_SUPPRESSED:
                parts.append(part)
        return parts

    def _solid_bodies(self, part) -> list:
        """The part component's solid bodies (part coordinates)."""
        bodies = part.GetBodies2(SW_BODY_SOLID) or ()
        if not isinstance(bodies, (list, tuple)):
            bodies = [bodies]
        return [binding.wrap(body, self._mod.IBody2) for body in bodies]

    def _frame(self, comp):
        """(rotation rows, shift in m, scale) of the component's transform, whose
        ArrayData holds the rotation column-major."""
        data = self._transform_data(comp)
        return [[data[col * 3 + row] for col in range(3)] for row in range(3)], data[9:12], data[12]

    @staticmethod
    def _extreme_point(body, direction) -> tuple:
        """The body's point furthest along `direction` (its own coordinates, m)."""
        result = body.GetExtremePoint(*direction)
        if not isinstance(result, tuple) or len(result) < 3 or (len(result) == 4 and not result[0]):
            raise SolidWorksError(f"SolidWorks found no extreme point of a body (got {result!r}).")
        return result[-3:]

    def _component_entry(self, comp) -> dict:
        entry = {
            "name": comp.Name2,
            "path": comp.GetPathName(),
            "fixed": bool(comp.IsFixed()),
            **self._placement(comp),
            "bounding_box_mm": self._component_box(comp),
        }
        if entry["bounding_box_mm"] is None:
            # a part made anew and saved under the same path showed nothing in
            # its assembly: SolidWorks no longer took the file for that component
            entry["problem"] = (
                "shows no geometry: its file may be missing or made anew under the same name; "
                "replace_component puts the file back in its place"
            )
        return entry

    def replace_component(self, name: str, path: str, reattach_mates: bool = True) -> dict:
        """Put the model at `path` in the place of component `name`, keeping its
        position and, with reattach_mates, its mates where they still find
        their faces. Returns the new component's entry."""
        if not os.path.isfile(path):
            raise SolidWorksError(f"No such file: {path}")
        asm = self._require_assembly()
        comp = self._component_by_name(asm, name)
        before = {c.Name2 for c in self._components(asm)}
        model = self._model
        model.ClearSelection2(True)
        selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
        if not comp.Select4(False, selmgr.CreateSelectData(), False):
            raise SolidWorksError(f"Could not select component '{comp.Name2}'.")
        done = asm.ReplaceComponents2(os.path.abspath(path), "", False, 0, bool(reattach_mates))
        model.ClearSelection2(True)
        model.ForceRebuild3(False)
        target = os.path.normcase(os.path.abspath(path))
        new = [
            c
            for c in self._components(asm)
            if os.path.normcase(c.GetPathName()) == target and (c.Name2 not in before or c.Name2 == comp.Name2)
        ]
        if not done or not new:
            raise SolidWorksError(f"SolidWorks did not replace '{name}' with {path}.")
        return {
            "ok": True,
            "replaced": name,
            "component": self._component_entry(new[0]),
            "mate_errors": [entry for mate in self._mates() if "error" in (entry := self._mate_entry(mate))],
        }

    def _fix_component(self, asm, comp) -> None:
        """Pin a component in place (FixComponent acts on the selection), and verify."""
        model = self._require_model()
        model.ClearSelection2(True)
        selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
        if not comp.Select4(False, selmgr.CreateSelectData(), False):
            raise SolidWorksError(f"Could not select component '{comp.Name2}'.")
        asm.FixComponent()
        model.ClearSelection2(True)
        if not comp.IsFixed():
            raise SolidWorksError(f"Component '{comp.Name2}' could not be fixed.")

    def insert_component(
        self, path: str, x_mm: float = 0.0, y_mm: float = 0.0, z_mm: float = 0.0, fixed: bool | None = None
    ) -> dict:
        """Insert a part (.sldprt) or a sub-assembly (.sldasm) into the current
        assembly with its ORIGIN at (x, y, z) mm.

        The part's own origin lands on the given point (AddComponent5's own X/Y/Z
        would centre the bounding box there instead, so the position is applied
        as a transform and verified by reading it back).

        fixed: True pins the component in place, False leaves it free to be moved
        by mates. The default (None) fixes only the FIRST component, which is the
        ground the rest of the assembly is positioned against.
        """
        abs_path = os.path.abspath(path)
        doc_type = {".sldprt": SW_DOC_PART, ".sldasm": SW_DOC_ASSEMBLY}.get(os.path.splitext(abs_path)[1].lower())
        if doc_type is None:
            raise SolidWorksError(f"insert_component takes a .sldprt or a .sldasm (got '{path}').")
        asm = self._require_assembly()
        if not os.path.isfile(abs_path):
            raise SolidWorksError(f"Part not found: {abs_path}")
        if fixed is None:
            fixed = not self._component_dispatches(asm)

        # AddComponent5 gives None for a part that is not loaded, so open it
        # silently first and switch back to the assembly before inserting.
        title = self._model.GetTitle()
        self._sw.OpenDoc6(abs_path, doc_type, SW_OPEN_DOC_SILENT, "", 0, 0)
        self._sw.ActivateDoc3(title, True, 0, 0)

        comp = binding.wrap(
            asm.AddComponent5(abs_path, SW_ADD_COMPONENT_CURRENT_CONFIG, "", False, "", 0.0, 0.0, 0.0),
            self._mod.IComponent2,
        )
        if comp is None:
            raise SolidWorksError(
                f"AddComponent5 returned None for '{abs_path}'. Is it a valid "
                "SolidWorks part, and could SolidWorks load it?"
            )
        self._apply_transform(comp, x_mm, y_mm, z_mm, 0.0, 0.0, 0.0)
        if fixed:
            self._fix_component(asm, comp)
        return {"ok": True, "component": self._component_entry(comp)}

    @_reads_only
    def list_components(self) -> dict:
        """List the components (name, path, fixed, placement, bounding box) and
        the mates: name, SolidWorks type, the dimension of a distance or angle
        mate, and the error of a mate SolidWorks flags."""
        asm = self._require_assembly()
        comps = [self._component_entry(c) for c in self._components(asm)]
        return {
            "ok": True,
            "count": len(comps),
            "components": comps,
            "mates": [self._mate_entry(mate) for mate in self._mates()],
        }

    def delete_component(self, component: str) -> dict:
        """Remove a component from the current assembly, with the mates that
        hold it. Returns the mates that went with it, the components left and the
        assembly's mass properties."""
        model = self._require_model()
        asm = self._require_assembly()
        comp = self._component_by_name(asm, component)
        name = comp.Name2
        mates_before = [m.Name for m in self._mates()]
        model.ClearSelection2(True)
        selmgr = binding.wrap(model.SelectionManager, self._mod.ISelectionMgr)
        if not comp.Select4(False, selmgr.CreateSelectData(), False):
            raise SolidWorksError(f"Could not select component '{name}'.")
        if not binding.wrap(model.Extension, self._mod.IModelDocExtension).DeleteSelection2(SW_DELETE_ABSORBED):
            raise SolidWorksError(f"SolidWorks refused to delete component '{name}'.")
        model.ClearSelection2(True)
        mates_after = {m.Name for m in self._mates()}
        return {
            "ok": True,
            "deleted": name,
            "mates_deleted": [m for m in mates_before if m not in mates_after],
            "components": [c.Name2 for c in self._components(asm)],
            "mass_properties": self.get_mass_properties()["mass_properties"],
        }

    def set_component_transform(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        z_mm: float,
        rx_deg: float = 0.0,
        ry_deg: float = 0.0,
        rz_deg: float = 0.0,
    ) -> dict:
        """Move/rotate a component: origin to (x, y, z) mm, rotated rx/ry/rz degrees.

        Rotations are applied X, then Y, then Z about the assembly axes, and work
        on a fixed component too (it simply becomes fixed at the new spot). The
        transform is read back and compared, so a write SolidWorks ignored fails
        loudly. Note that mates re-solve on the next rebuild and will override a
        manual move.
        """
        asm = self._require_assembly()
        comp = self._component_by_name(asm, name)
        placement = self._apply_transform(comp, x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg)
        return {"ok": True, "component": comp.Name2, **placement, "bounding_box_mm": self._component_box(comp)}
