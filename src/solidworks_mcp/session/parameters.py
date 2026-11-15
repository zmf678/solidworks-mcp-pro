"""Dimensions, equations, global variables and dimension listings.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import math
import re

from .. import binding
from ..constants import (
    FEATURE_ERRORS,
    SW_ANGULAR_DIMENSION,
    SW_DIMENSION_DRIVING,
    SW_DIMENSION_PARAM_ANGULAR,
    SW_DOC_PART,
    SW_HOR_LINEAR_DIMENSION,
    SW_SEL_EXT_SKETCH_POINTS,
    SW_SEL_SKETCH_POINTS,
    SW_VERT_LINEAR_DIMENSION,
)
from ..errors import SolidWorksError
from ..units import m_to_mm, mm_to_m
from ._decorators import _reads_only


class ParametersMixin:
    """Dimensions, equations, global variables and dimension listings."""

    def set_dimension(self, dimension_name: str, value_mm: float) -> dict:
        """Set a named driving dimension (e.g. 'D1@BlockExtrude'), rebuild, remeasure.

        value_mm is in degrees for an angle (a revolve, an angle mate); the
        result's keys then end in _deg. A point's coordinate (a sketch's 'x3'
        or 'y2', from the origin) takes a sign, -5 being the other side of
        the origin; any other dimension is a size and cannot be negative.
        A value SolidWorks does not take is refused, the part left as it was.
        `broken_features` names the features that fail since the change (a
        later cut whose sketch now lies off the part, a split whose bodies
        changed), with their error; fix or undo before going on.
        """
        self._require_model()
        dim = self._dimension(dimension_name)
        failing_before = {f["name"] for f in self._failing_features()}
        unit, to_system, from_system = self._dimension_unit(dim)
        coordinate = self._coordinate_of(dimension_name)
        if coordinate is None and unit == "mm" and value_mm < 0:
            raise SolidWorksError(
                f"'{dimension_name}' is a size and cannot be negative (got {value_mm:g}); only a "
                "point's coordinate from the origin takes a sign. The part is as it was."
            )

        def current() -> float:
            return from_system(dim.SystemValue) if coordinate is None else self._coordinate_of(dimension_name)()

        old, original = current(), dim.SystemValue
        target = self._joint_angle(dim, unit, value_mm) if coordinate is None else value_mm
        # A coordinate is a distance to SolidWorks: a negative value puts the
        # point on the other side, a positive one keeps the side it is on.
        crosses = coordinate is not None and (value_mm < 0) != (old < 0)
        rebuilt_ok = self._write_dimension(
            dim, to_system(-abs(value_mm) if crosses else abs(value_mm) if coordinate else target)
        )
        # A driven or equation-controlled dimension, or a value SolidWorks keeps
        # out (a width of 0), ignores the write without a word, yet a width of 0
        # left its sketch 'invalid solution': write the old value back.
        applied = current()
        if abs(applied - target) >= 1e-6:
            self._write_dimension(dim, original)
            if abs(current() - old) >= 1e-6:
                raise SolidWorksError(
                    f"'{dimension_name}' did not take {value_mm:g} {unit}, and putting back "
                    f"{old:g} failed: it reads {current():g}. Check the part."
                )
            raise SolidWorksError(
                f"'{dimension_name}' stays at {old:g} {unit}: SolidWorks did not take "
                f"{value_mm:g}, as {self._why_not_taken(dimension_name, dim)}. The part is as it was."
            )
        return {
            "ok": True,
            "dimension": dimension_name,
            f"old_value_{unit}": round(old, 6),
            f"requested_value_{unit}": value_mm,
            f"new_value_{unit}": round(applied + value_mm - target, 6),  # -30, not the 330 SolidWorks holds
            "applied": True,
            "rebuild_ok": rebuilt_ok,
            "broken_features": [f for f in self._failing_features() if f["name"] not in failing_before],
            "mass_properties": self.get_mass_properties()["mass_properties"],
        }

    def _write_dimension(self, dim, system_value: float) -> bool:
        """Write a dimension's SystemValue and rebuild; returns rebuild_ok.

        SolidWorks now and then ignores a write at random (3 in 80 on a fresh
        box, measured): the old value reads back, and the same write once more
        takes. A value it refuses stays refused, for the caller to report. A
        coordinate written negative reads back positive, so sizes are compared.
        """
        for _ in range(2):
            dim.SystemValue = system_value
            rebuilt_ok = bool(self._model.ForceRebuild3(False))
            if abs(abs(dim.SystemValue) - abs(system_value)) < 1e-9:
                break
        return rebuilt_ok

    def _joint_angle(self, dim, unit: str, value: float) -> float:
        """The value to write for `value`: an angle mate's dimension turns its
        joint the whole way round, and SolidWorks takes 0..360 for it, so -30
        is written as 330 (the same turn); any other dimension as it is."""
        if unit != "deg":
            return value
        owner = binding.wrap(dim.GetFeatureOwner(), self._mod.IFeature)
        return value % 360 if owner is not None and owner.GetTypeName2().startswith("Mate") else value

    def _why_not_taken(self, dimension_name: str, dim) -> str:
        """Why SolidWorks kept a dimension at its value."""
        equation = next(
            (e["equation"] for e in self._equation_entries() if (e["name"] or "").lower() == dimension_name.lower()),
            None,
        )
        if equation:
            return f"it follows the equation {equation}: change that with set_equation, or delete_equation"
        if dim.DrivenState != SW_DIMENSION_DRIVING:
            return "it is a reference (driven) dimension, which follows the geometry"
        return "it refuses such a value (a size of 0, a negative angle)"

    def _coordinate_of(self, dimension_name: str):
        """For a sketch point's horizontal or vertical distance from the origin
        (an external sketch point), a function giving the point's coordinate
        along it in mm, with its sign; None for any other dimension."""
        dim_name, _, rest = dimension_name.partition("@")
        if not rest or int(self._model.GetType()) != SW_DOC_PART:
            return None
        sketch_name = rest.split("@")[0]
        feature = next(
            (
                candidate
                for feat in self._iter_features()
                for candidate in [feat, *self._sub_features(feat)]
                if candidate.Name == sketch_name and candidate.GetTypeName2() == "ProfileFeature"
            ),
            None,
        )
        if feature is None:
            return None
        display = binding.wrap(feature.GetFirstDisplayDimension(), self._mod.IDisplayDimension)
        while display is not None and binding.wrap(display.GetDimension2(0), self._mod.IDimension).Name != dim_name:
            display = binding.wrap(feature.GetNextDisplayDimension(display), self._mod.IDisplayDimension)
        if display is None or display.Type2 not in (SW_HOR_LINEAR_DIMENSION, SW_VERT_LINEAR_DIMENSION):
            return None
        annotation = binding.wrap(display.GetAnnotation(), self._mod.IAnnotation)
        attached = list(zip(annotation.GetAttachedEntities3() or (), annotation.GetAttachedEntityTypes() or ()))
        points = [binding.wrap(e, self._mod.ISketchPoint) for e, t in attached if t == SW_SEL_SKETCH_POINTS]
        origins = [binding.wrap(e, self._mod.ISketchPoint) for e, t in attached if t == SW_SEL_EXT_SKETCH_POINTS]
        if len(points) != 1 or len(origins) != 1:
            return None
        axis = "X" if display.Type2 == SW_HOR_LINEAR_DIMENSION else "Y"
        return lambda: m_to_mm(getattr(points[0], axis) - getattr(origins[0], axis))

    def _dimension(self, dimension_name: str):
        dim = binding.wrap(self._require_model().Parameter(dimension_name), self._mod.IDimension)
        if dim is None:
            raise SolidWorksError(f"Dimension '{dimension_name}' not found. Use the 'D1@<feature>' notation.")
        return dim

    @staticmethod
    def _dimension_unit(dim):
        """('deg', to radians, from radians) for an angle, else ('mm', to m, from m).
        An angle written as millimetres would land as a thousandth of a radian."""
        if dim.GetType() == SW_DIMENSION_PARAM_ANGULAR:
            return "deg", math.radians, math.degrees
        return "mm", mm_to_m, m_to_mm

    def set_equation(self, equation: str) -> dict:
        """Add an equation, or replace the one that sets the same name, then
        rebuild and remeasure (see set_equations).

        equation is a SolidWorks equation string, e.g.
        '"D1@BlockExtrude" = 25' or '"D1@BlockExtrude" = 2 * "D1@Sketch1"'.
        Unlike set_dimension (a one-off value), this persists a relation in the
        model. Returns the resulting mass properties.
        """
        result = self.set_equations([equation])
        [done] = result.pop("equations")
        return {"ok": True, **done, **result}

    def set_equations(self, equations: list) -> dict:
        """Add or replace equations, then rebuild once. One that sets a name
        already set (a global variable in any case, or a dimension) replaces it
        in place. A refused equation undoes the whole list. SolidWorks solves
        them in the order they need, not as listed: a variable added below the
        equations that use it would otherwise take two rebuilds and warn.
        Returns per equation its index and whether it replaced one, the features
        that fail to rebuild, and the mass properties."""
        model = self._require_model()
        if isinstance(equations, str) or not equations:
            raise SolidWorksError("set_equations takes a list of equations, such as ['\"L\" = 85'].")
        names = [self._equation_lhs(text) for text in equations]  # every one checked before any change
        eqmgr = self._equation_mgr()
        eqmgr.AutomaticSolveOrder = True
        journal, done = [], []
        try:
            for text, name in zip(equations, names):
                index = self._equation_index(eqmgr, name)
                if index is None:
                    index = eqmgr.Add2(eqmgr.GetCount(), text, False)  # solved by the rebuild below
                    if index < 0:
                        raise SolidWorksError(f"SolidWorks refused {text}: check the expression and the names in it.")
                    journal.append((index, None))
                else:
                    before = eqmgr.Equation(index)
                    eqmgr.SetEquation(index, text)
                    if not self._same_equation(eqmgr.Equation(index), text):  # a refusal keeps the old text, silently
                        raise SolidWorksError(f"SolidWorks refused {text}: check the expression and the names in it.")
                    journal.append((index, before))
                done.append({"equation": text, "index": index, "replaced": journal[-1][1] is not None})
        except SolidWorksError:
            for index, before in reversed(journal):
                if before is None:
                    eqmgr.Delete(index)
                else:
                    eqmgr.SetEquation(index, before)
            model.ForceRebuild3(False)
            raise
        rebuilt_ok = bool(model.ForceRebuild3(False))
        return {
            "ok": True,
            "equations": done,
            "rebuild_ok": rebuilt_ok,
            "failing_features": self._failing_features(),
            "mass_properties": self.get_mass_properties()["mass_properties"],
        }

    @_reads_only
    def list_equations(self) -> dict:
        """The equations and global variables in order: index, equation, the name
        it sets, its value and whether it is a global variable. `broken` marks
        one that names a dimension or variable that is gone, as one left behind
        by delete_feature. automatic_solve_order False: SolidWorks solves them
        as listed, so one above the line that sets its variable warns and lags
        a rebuild; any set_equation turns it on."""
        out = self._equation_entries()
        return {
            "ok": True,
            "count": len(out),
            "equations": out,
            "automatic_solve_order": bool(self._equation_mgr().AutomaticSolveOrder),
        }

    def _equation_entries(self) -> list:
        model = self._require_model()
        eqmgr = self._equation_mgr()
        texts = [eqmgr.Equation(i) for i in range(eqmgr.GetCount())]
        variables = {
            self._equation_names(t)[0].lower()
            for i, t in enumerate(texts)
            if eqmgr.GlobalVariable(i) and self._equation_names(t)
        }
        out = []
        for i, text in enumerate(texts):
            names = self._equation_names(text)
            out.append(
                {
                    "index": i,
                    "equation": text,
                    "name": names[0] if names else None,
                    "value": round(eqmgr.Value(i), 6),
                    "global": bool(eqmgr.GlobalVariable(i)),
                    "broken": any(n.lower() not in variables and model.Parameter(n) is None for n in names),
                }
            )
        return out

    def delete_equation(self, equation) -> dict:
        """Delete an equation by the name it sets ('L_thigh', 'D1@Boss') or by its
        list_equations index, then rebuild and remeasure."""
        model = self._require_model()
        eqmgr = self._equation_mgr()
        count = eqmgr.GetCount()
        key = str(equation).strip()
        if key.isdigit():
            index = int(key)
            if index >= count:
                raise SolidWorksError(f"No equation {index}: there are {count} (0..{count - 1}).")
        else:
            index = self._equation_index(eqmgr, key.strip('"'))
            if index is None:
                listed = ", ".join(eqmgr.Equation(i) for i in range(count)) or "none"
                raise SolidWorksError(f"No equation sets '{key}' (there are: {listed}).")
        text = eqmgr.Equation(index)
        if eqmgr.Delete(index) < 0:
            raise SolidWorksError(f"SolidWorks refused to delete {text}.")
        rebuilt_ok = bool(model.ForceRebuild3(False))
        return {
            "ok": True,
            "deleted": text,
            "count": eqmgr.GetCount(),
            "rebuild_ok": rebuilt_ok,
            "failing_features": self._failing_features(),
            "mass_properties": self.get_mass_properties()["mass_properties"],
        }

    def _equation_mgr(self):
        eqmgr = binding.wrap(self._require_model().GetEquationMgr(), self._mod.IEquationMgr)
        if eqmgr is None:
            raise SolidWorksError("No EquationManager available.")
        return eqmgr

    def _equation_index(self, eqmgr, name: str):
        """The index of the equation that sets `name` (any case), or None."""
        for i in range(eqmgr.GetCount()):
            names = self._equation_names(eqmgr.Equation(i))
            if names and names[0].lower() == name.lower():
                return i
        return None

    @staticmethod
    def _equation_lhs(equation) -> str:
        """The name an equation sets: '"L" = 85' -> 'L'; pure, unit-tested."""
        match = re.match(r'\s*"([^"]+)"\s*=', str(equation))
        if not match:
            raise SolidWorksError(f'An equation is "name" = expression, the name in double quotes (got {equation!r}).')
        return match.group(1)

    @staticmethod
    def _equation_names(equation: str) -> list:
        """Every quoted name in an equation, the one it sets first; pure, unit-tested."""
        return re.findall(r'"([^"]+)"', str(equation))

    @staticmethod
    def _same_equation(a: str, b: str) -> bool:
        return re.sub(r"\s+", "", a).lower() == re.sub(r"\s+", "", b).lower()

    @staticmethod
    def _error_entry(code, warning) -> dict:
        """A feature's error code with what it means, where known; pure."""
        return {"code": code, "warning": bool(warning), "cause": FEATURE_ERRORS.get(code, f"SolidWorks error {code}")}

    def _failing_features(self) -> list:
        """The features that fail to rebuild (errors, not warnings), in tree order."""
        failing = []
        for feat in self._iter_features():
            code, warning = feat.GetErrorCode2()
            if code and not warning:
                failing.append({"name": feat.Name, "type": feat.GetTypeName2(), **self._error_entry(code, warning)})
        return failing

    @_reads_only
    def list_dimensions(self, contains: str | None = None) -> dict:
        """Every dimension in the part, feature by feature, as set_dimension takes it.

        For a part opened from disk, or after the tool results that named them
        are gone. Values are mm, angles degrees; `driving` is False for a
        reference (driven) dimension, which set_dimension cannot change.
        contains keeps those whose name or feature holds that text (any case):
        a part of hundreds of features lists too much to read back.
        """
        self._require_part()
        needle = (contains or "").lower()
        dims, seen = [], set()
        for feat in self._iter_features():
            for entry in self._dimension_entries(feat):
                if needle not in entry["name"].lower() and needle not in entry["feature"].lower():
                    continue
                if entry["name"] not in seen:
                    seen.add(entry["name"])
                    dims.append(entry)
        return {"ok": True, "count": len(dims), "dimensions": dims}

    def _dimension_entries(self, feat) -> list:
        """The feature's dimensions: name (as set_dimension takes it), value in
        mm or degrees, and whether it is driving."""
        entries = []
        display = feat.GetFirstDisplayDimension()
        while display is not None:
            shown = binding.wrap(display, self._mod.IDisplayDimension)
            dim = binding.wrap(shown.GetDimension2(0), self._mod.IDimension)
            angular = shown.GetType() == SW_ANGULAR_DIMENSION
            value = dim.SystemValue
            entries.append(
                {
                    "name": dim.GetNameForSelection(),
                    "feature": feat.Name,
                    "value": round(math.degrees(value) if angular else m_to_mm(value), 6),
                    "unit": "deg" if angular else "mm",
                    "driving": dim.DrivenState == SW_DIMENSION_DRIVING,
                }
            )
            display = feat.GetNextDisplayDimension(display)
        return entries
