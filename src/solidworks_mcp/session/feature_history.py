"""Feature-tree history, suppression and reordering.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import pythoncom

from .. import binding
from ..constants import (
    SKETCH_STATUSES,
    SW_DELETE_ABSORBED,
    SW_DELETE_CHILDREN,
    SW_FULLY_CONSTRAINED,
    SW_MOVE_BEFORE,
    SW_SUPPRESS_FEATURE,
    SW_THIS_CONFIGURATION,
    SW_UNSUPPRESS_DEPENDENT,
)
from ..errors import SolidWorksError
from ..mesh_tools import area, extents, simplify
from ._decorators import _reads_only


class FeatureHistoryMixin:
    """Feature-tree history, suppression and reordering."""

    def _iter_features(self):
        """Yield each feature in the tree as a wrapped IFeature, in tree order."""
        feat = binding.wrap(self._model.FirstFeature(), self._mod.IFeature)
        while feat is not None:
            yield feat
            feat = binding.wrap(feat.GetNextFeature(), self._mod.IFeature)

    def _profile_feature_names(self) -> set:
        """Names of all sketches (ProfileFeature) in the tree.

        A before/after diff around drawing a sketch identifies exactly the one
        just created -- robust to pre-existing sketches and tree ordering, unlike
        a 'last ProfileFeature' assumption.
        """
        names = set()
        for feat in self._iter_features():
            try:
                if feat.GetTypeName2() == "ProfileFeature":
                    names.add(feat.Name)
            except pythoncom.com_error:
                pass
        return names

    def _sub_features(self, feat) -> list:
        subs, sub = [], binding.wrap(feat.GetFirstSubFeature(), self._mod.IFeature)
        while sub is not None:
            subs.append(sub)
            sub = binding.wrap(sub.GetNextSubFeature(), self._mod.IFeature)
        return subs

    def _under_defined_sketches(self) -> list:
        """'Sketch3 (under defined)' for every sketch in the part that is not fully defined.

        Includes sketches that exist only as sub-features, such as the position
        sketch of a Hole Wizard hole, which the feature walk does not visit.
        """
        found, seen = [], set()
        for feat in self._iter_features():
            for candidate in [feat, *self._sub_features(feat)]:
                if candidate.GetTypeName2() != "ProfileFeature" or candidate.Name in seen:
                    continue
                seen.add(candidate.Name)
                status = binding.wrap(candidate.GetSpecificFeature2(), self._mod.ISketch).GetConstrainedStatus()
                if status != SW_FULLY_CONSTRAINED:
                    found.append(f"{candidate.Name} ({SKETCH_STATUSES.get(status, f'status {status}')})")
        return found

    def _ref_planes(self) -> list:
        """All reference planes in tree order (fresh part: [Front, Top, Right, ...])."""
        self._require_part()
        planes = []
        for feat in self._iter_features():
            try:
                if feat.GetTypeName2() == "RefPlane":
                    planes.append(feat)
            except pythoncom.com_error:
                pass
        return planes

    def _last_ref_plane(self):
        """The most recently created reference plane (e.g. a fresh loft offset plane)."""
        planes = self._ref_planes()
        return planes[-1] if planes else None

    def _first_dimension_name(self, feature) -> str:
        """The feature's first dimension as set_dimension takes it, e.g. 'D1@Plane1'."""
        display = feature.GetFirstDisplayDimension()
        if display is None:
            raise SolidWorksError(f"Feature '{feature.Name}' has no dimension.")
        dim = binding.wrap(binding.wrap(display, self._mod.IDisplayDimension).GetDimension2(0), self._mod.IDimension)
        return dim.GetNameForSelection()

    def _last_feature_name(self) -> str:
        """Name of the most recent body-modifying feature (the default pattern seed).

        Skips folders, sketches, reference geometry and finishing/repeat features
        (fillet/chamfer/shell/patterns) so the default seed is a real boss/cut/
        hole/revolve. Pass feature_name explicitly to override.
        """
        feat = binding.wrap(self._model.FirstFeature(), self._mod.IFeature)
        seed = None
        while feat is not None:
            try:
                tname = feat.GetTypeName2() or ""
            except pythoncom.com_error:
                tname = ""
            if tname and not tname.endswith("Folder") and tname not in self._NON_SEED_TYPES:
                seed = feat
            feat = binding.wrap(feat.GetNextFeature(), self._mod.IFeature)
        if seed is None:
            raise SolidWorksError("No patternable feature found; pass feature_name explicitly.")
        return seed.Name

    def _history(self) -> list:
        """The part's features after the origin, in tree order: what was modelled.

        Every part starts with SolidWorks' folders, the three default planes and
        the origin; whatever follows the origin was built by someone.
        """
        self._require_part()
        history, after_origin = [], False
        for feat in self._iter_features():
            if after_origin:
                history.append(feat)
            elif feat.GetTypeName2() == "OriginProfileFeature":
                after_origin = True
        return history

    def _history_feature(self, name: str):
        history = self._history()
        for feat in history:
            if feat.Name == name:
                return feat
        listed = ", ".join(f.Name for f in history) or "none"
        raise SolidWorksError(f"No feature '{name}' in the part's history (there are: {listed}).")

    @staticmethod
    def _is_suppressed(feat) -> bool:
        return bool(feat.IsSuppressed2(SW_THIS_CONFIGURATION, None)[0])

    @_reads_only
    def list_features(self) -> dict:
        """The part's modelling history in tree order: name, type, suppressed.

        Sketches are listed in their own right; types are SolidWorks' own names
        (ProfileFeature = sketch, Extrusion, ICE = cut-extrude, Fillet, ...). A
        feature SolidWorks flags carries `error` {code, warning}: warning False
        means it fails to rebuild. `under_defined_sketches` names every sketch
        that can still move, which a part drawn by hand may have.
        """
        features = []
        for feat in self._history():
            entry = {"name": feat.Name, "type": feat.GetTypeName2(), "suppressed": self._is_suppressed(feat)}
            code, warning = feat.GetErrorCode2()
            if code:
                entry["error"] = self._error_entry(code, warning)
            features.append(entry)
        return {
            "ok": True,
            "count": len(features),
            "features": features,
            "under_defined_sketches": self._under_defined_sketches(),
        }

    def delete_feature(
        self, name: str, with_children: bool = False, with_equations: bool = False, dry_run: bool = False
    ) -> dict:
        """Delete a history feature with the sketches it absorbed; rebuild, remeasure.

        What is built on it (a fillet on its edges, a sketch on its face) would
        be left broken, so it refuses and names those, and what is built on
        them in turn, unless with_children=True deletes them too. `deleted`
        lists what went, in tree order; dry_run=True lists it as
        `would_delete` and leaves the part as it is. Equations that named its
        dimensions break: `broken_equations` lists them, unless
        with_equations=True deletes them (`deleted_equations`); global
        variables stay.
        """
        model = self._require_model()
        feature = self._history_feature(name)
        going = self._goes_along(feature, with_children=True)
        dependents = [n for n in going if n not in self._goes_along(feature, with_children=False)]
        if dependents and not with_children:
            raise SolidWorksError(
                f"'{name}' has dependents: {', '.join(dependents)}. Delete those first, suppress "
                f"'{name}' instead, or pass with_children=True to delete them too."
            )
        if dry_run:
            return {"ok": True, "would_delete": going, "mass_properties": self.get_mass_properties()["mass_properties"]}
        before = [f.Name for f in self._history()]
        broken_before = {e["equation"] for e in self._equation_entries() if e["broken"]}
        model.ClearSelection2(True)
        if not feature.Select2(False, 0):
            raise SolidWorksError(f"Could not select '{name}'.")
        options = SW_DELETE_ABSORBED | (SW_DELETE_CHILDREN if with_children else 0)
        if not binding.wrap(model.Extension, self._mod.IModelDocExtension).DeleteSelection2(options):
            raise SolidWorksError(f"SolidWorks refused to delete '{name}'.")
        rebuilt_ok = bool(model.ForceRebuild3(False))
        after = {f.Name for f in self._history()}
        result = {"ok": True, "deleted": [n for n in before if n not in after]}
        broken = [e for e in self._equation_entries() if e["broken"] and e["equation"] not in broken_before]
        if with_equations and broken:
            eqmgr = self._equation_mgr()
            for entry in sorted(broken, key=lambda e: e["index"], reverse=True):  # later indexes first
                if eqmgr.Delete(entry["index"]) < 0:
                    raise SolidWorksError(f"SolidWorks refused to delete {entry['equation']}.")
            rebuilt_ok = bool(model.ForceRebuild3(False))
            result["deleted_equations"] = [e["equation"] for e in broken]
            # one that used a variable set by a deleted equation breaks in turn
            broken = [e for e in self._equation_entries() if e["broken"] and e["equation"] not in broken_before]
        result.update(
            broken_equations=[e["equation"] for e in broken],
            rebuild_ok=rebuilt_ok,
            mass_properties=self.get_mass_properties()["mass_properties"],
        )
        return result

    def _goes_along(self, feature, with_children: bool) -> list:
        """The history features a delete of `feature` takes, in tree order: it
        and the sketches it absorbed; with_children also what is built on it,
        on what is built on that, and so on (GetChildren gives one level)."""
        names, todo = set(), [feature]
        while todo:
            feat = todo.pop()
            if feat.Name in names:
                continue
            names.add(feat.Name)
            todo += self._sub_features(feat)
            if with_children:
                todo += [binding.wrap(c, self._mod.IFeature) for c in (feat.GetChildren() or ())]
        return [f.Name for f in self._history() if f.Name in names]

    def suppress_feature(self, name: str, suppress: bool = True) -> dict:
        """Suppress a history feature or bring it back; rebuild, remeasure.

        Unlike delete_feature it keeps the feature and its dimensions, so it
        suits trying a variant. What depends on it follows both ways: SolidWorks
        suppresses the dependents along, and suppress=False brings them back
        too. `changed` lists every feature whose state changed.
        """
        model = self._require_model()
        feature = self._history_feature(name)
        before = {f.Name: self._is_suppressed(f) for f in self._history()}
        action = SW_SUPPRESS_FEATURE if suppress else SW_UNSUPPRESS_DEPENDENT
        if not feature.SetSuppression2(action, SW_THIS_CONFIGURATION, None):
            raise SolidWorksError(f"SolidWorks refused to {'suppress' if suppress else 'unsuppress'} '{name}'.")
        rebuilt_ok = bool(model.ForceRebuild3(False))
        return {
            "ok": True,
            "changed": [f.Name for f in self._history() if self._is_suppressed(f) != before[f.Name]],
            "rebuild_ok": rebuilt_ok,
            "mass_properties": self.get_mass_properties()["mass_properties"],
        }

    def reorder_feature(self, name: str, before: str) -> dict:
        """Move a history feature, with its sketch, to just before another one
        and its sketch; rebuild, remeasure.

        A boss added last fills the holes cut before it; moved before them,
        they cut through it again. Refused, the part as it was, when the
        feature is built on something at or after that place.
        """
        model = self._require_model()
        feature, target = self._history_feature(name), self._history_feature(before)
        if feature.Name == target.Name:
            raise SolidWorksError(f"'{name}' cannot move before itself.")
        names = [f.Name for f in self._history()]
        # before the target's own sketch, so the two stay together in the tree
        place = min((f.Name for f in [target, *self._sub_features(target)] if f.Name in names), key=names.index)
        extension = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        along = []
        if not extension.ReorderFeature(feature.Name, place, SW_MOVE_BEFORE):
            later = self._later_parents(feature, place)
            # reference planes and axes it stands on move along, theirs first
            along = self._reference_chain(later, place)
            if (
                not later
                or along is None
                or not all(extension.ReorderFeature(ref, place, SW_MOVE_BEFORE) for ref in along)
                or not extension.ReorderFeature(feature.Name, place, SW_MOVE_BEFORE)
            ):
                self._restore_order(extension, names)
                raise SolidWorksError(
                    f"SolidWorks did not move '{name}' before '{before}'"
                    + (f": it is built on {', '.join(later)}, which would come after it." if later else ".")
                    + " The part is as it was."
                )
        rebuilt_ok = bool(model.ForceRebuild3(False))
        return {
            "ok": True,
            "features": [f.Name for f in self._history()],
            "moved_along": along,
            "rebuild_ok": rebuilt_ok,
            "failing_features": self._failing_features(),
            "mass_properties": self.get_mass_properties()["mass_properties"],
        }

    def _later_parents(self, feature, place: str) -> list:
        """What `feature` (with what goes along with it) is built on that comes
        at or after `place`, in tree order."""
        names = [f.Name for f in self._history()]
        moved = self._goes_along(feature, with_children=False)
        parents = {
            binding.wrap(p, self._mod.IFeature).Name
            for f in self._history()
            if f.Name in moved
            for p in (f.GetParents() or ())
        }
        return [n for n in names[names.index(place) :] if n in parents and n not in moved]

    def _reference_chain(self, later: list, place: str) -> list | None:
        """The reference geometry to move before `place` so `later` comes with
        it: those planes and axes and, first, what they stand on after the
        place. None when one of them is no reference geometry (a boss, a cut),
        which must stay where it is."""
        by_name = {f.Name: f for f in self._history()}
        chain = []
        for name in later:
            if by_name[name].GetTypeName2() not in self._REFERENCE_TYPES:
                return None
            deeper = self._reference_chain(self._later_parents(by_name[name], place), place)
            if deeper is None:
                return None
            chain += [n for n in deeper + [name] if n not in chain]
        return chain

    def _restore_order(self, extension, names: list) -> None:
        """Put the history back in the order `names` after a move that failed
        halfway: each feature before the one that followed it."""
        for name, following in reversed(list(zip(names, names[1:]))):
            now = [f.Name for f in self._history()]
            if now == names:
                return
            if name in now and following in now and now.index(name) > now.index(following):
                extension.ReorderFeature(name, following, SW_MOVE_BEFORE)

    @staticmethod
    def _loop_entry(loop, with_points: bool) -> dict:
        points = simplify(loop)
        u0, u1, v0, v1 = extents(points)
        entry = {
            "area_mm2": round(area(points), 4),
            "min_mm": [round(u0, 4), round(v0, 4)],
            "max_mm": [round(u1, 4), round(v1, 4)],
            "point_count": len(points),
        }
        if with_points:
            entry["points_mm"] = [[round(u, 4), round(v, 4)] for u, v in points]
        return entry
