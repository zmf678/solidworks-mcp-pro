"""Body and feature mirrors.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

from .. import binding
from ..constants import (
    SW_FEATURE_SCOPE_ALL_BODIES,
    SW_MARK_MIRROR_BODY,
    SW_MARK_MIRROR_FEATURE,
    SW_MARK_MIRROR_PLANE,
)
from ..errors import SolidWorksError


class MirrorsMixin:
    """Body and feature mirrors."""

    def add_mirror(
        self, plane: str, offset_mm: float = 0.0, features: list | None = None, name: str = "Mirror"
    ) -> dict:
        """Mirror features, or the whole body, about a plane moved offset_mm.

        plane 'front' / 'top' / 'right' mirrors about z / y / x = offset_mm; the
        name of another plane in the part (e.g. 'Plane1') mirrors about that
        plane moved offset_mm along its normal.
        features are list_features names; their copies follow them, so changing
        a seed's dimension changes its copy too. Without features the body is
        mirrored and merged: model half of a symmetric part and mirror it about
        the face where the halves meet. The plane's position comes back as the
        dimension `plane_offset`. SolidWorks quietly builds a mirror whose copy
        lands outside the part or on its seed; that fails here instead, and the
        part stays as it was.
        """
        if features is not None and not features:
            raise SolidWorksError("features is empty: name the features to mirror, or leave it out to mirror the body.")
        model = self._require_model()
        _, label = self._named_plane(plane)
        key = str(plane).lower()
        where = (
            f"{self._MIRROR_AXES[key]} = {offset_mm:g}" if key in self._MIRROR_AXES else f"{label} + {offset_mm:g} mm"
        )
        seeds = [self._history_feature(n) for n in features or ()]
        mirror_plane, created = self._plane_at(plane, offset_mm)
        model.ClearSelection2(True)
        if seeds:
            for seed in seeds:
                if not seed.Select2(True, SW_MARK_MIRROR_FEATURE):
                    raise SolidWorksError(f"Could not select '{seed.Name}'.")
        else:
            select_data = binding.wrap(
                binding.wrap(model.SelectionManager, self._mod.ISelectionMgr).CreateSelectData(), self._mod.ISelectData
            )
            select_data.Mark = SW_MARK_MIRROR_BODY
            if not self._solid_body().Select2(False, select_data):
                raise SolidWorksError("Could not select the body.")
        if not mirror_plane.Select2(True, SW_MARK_MIRROR_PLANE):
            raise SolidWorksError(f"Could not select the mirror plane at {where}.")
        feat_mgr = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        mirror = binding.wrap(
            feat_mgr.InsertMirrorFeature2(not seeds, False, not seeds, False, SW_FEATURE_SCOPE_ALL_BODIES),
            self._mod.IFeature,
        )
        model.ForceRebuild3(False)
        problem = self._mirror_problem(mirror, bool(seeds), where)
        if problem:
            raise SolidWorksError(problem)  # run_guarded removes the mirror and its plane
        if created and mirror_plane.Select2(False, 0):
            model.BlankRefGeom()  # construction geometry; keep screenshots clean
        model.ClearSelection2(True)
        dimensions = {"plane_offset": self._first_dimension_name(mirror_plane)} if created else {}
        return self._finish_feature(mirror, name, dimensions=dimensions, fully_defined=True)

    @staticmethod
    def _mirror_problem(mirror, of_features: bool, where: str) -> str | None:
        """Why the mirror just built is no good, or None."""
        if mirror is None:
            if of_features:
                return f"SolidWorks built no mirror about {where}: mirror features, not sketches."
            return (
                f"SolidWorks built no mirror about {where}: the mirrored body must touch the original. "
                "Put the plane on the face where the halves meet."
            )
        code, warning = mirror.GetErrorCode2()
        if code:
            return (
                f"SolidWorks flags the mirror about {where} ({'warning' if warning else 'error'} {code}): "
                "a copy lands outside the part, or on top of its seed (a seed on the plane). "
                "Put the plane where every copy lands in material."
            )
        return None
