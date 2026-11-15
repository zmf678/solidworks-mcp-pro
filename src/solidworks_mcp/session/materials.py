"""Appearance, SolidWorks materials and localized material lookup.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import difflib
import html
import json
import os
import re
import shutil
import tempfile
from importlib import resources
from xml.sax.saxutils import quoteattr

import pythoncom
import win32com.client

from .. import binding
from ..constants import (
    MCP_MATERIAL_DATABASE,
    SW_DOC_ASSEMBLY,
    SW_FILE_LOCATIONS_MATERIALS,
    SW_THIS_CONFIGURATION,
)
from ..errors import SolidWorksError


class MaterialsMixin:
    """Appearance, SolidWorks materials and localized material lookup."""

    def set_appearance(
        self, rgb: list | None = None, transparency: float | None = None, component: str | None = None
    ) -> dict:
        """Colour (rgb, 0..255 each) and transparency (0 solid .. 1 clear) of the
        current part, or in an assembly of one component ('Leg-1/Thigh-1' inside
        a sub-assembly); what is left out stays as it was. A component's colour
        is the assembly's, the part keeps its own."""
        if rgb is None and transparency is None:
            raise SolidWorksError("Give rgb, transparency or both.")
        model = self._require_model()
        if int(model.GetType()) == SW_DOC_ASSEMBLY:
            if component is None:
                raise SolidWorksError("In an assembly, name the component to colour (list_components).")
            comp = self._component_by_name(binding.wrap(model, self._mod.IAssemblyDoc), component)
            current = comp.GetMaterialPropertyValues2(SW_THIS_CONFIGURATION, None)
            if current[0] < 0:  # no colour of its own in the assembly yet: start from the part's
                part = binding.wrap(comp.GetModelDoc2(), self._mod.IModelDoc2)
                current = part.MaterialPropertyValues if part is not None else self._DEFAULT_APPEARANCE
            values = self._appearance_values(current, rgb, transparency)
            comp.SetMaterialPropertyValues2(self._doubles(values), SW_THIS_CONFIGURATION, None)
            stored = comp.GetMaterialPropertyValues2(SW_THIS_CONFIGURATION, None)
        else:
            if component is not None:
                raise SolidWorksError("component is for an assembly; a part is coloured as a whole.")
            values = self._appearance_values(model.MaterialPropertyValues, rgb, transparency)
            model.MaterialPropertyValues = self._doubles(values)
            stored = model.MaterialPropertyValues
        model.GraphicsRedraw2()
        # SolidWorks keeps colours in steps of 1/255
        if any(abs(a - b) > 1 / 255 for a, b in zip(stored, values)):
            raise SolidWorksError(f"SolidWorks did not take the appearance: it reads {list(stored)}.")
        return {
            "ok": True,
            "rgb": [round(c * 255) for c in stored[:3]],
            "transparency": round(stored[7], 3),
            **({"component": comp.Name2} if component is not None else {}),
        }

    @staticmethod
    def _appearance_values(current, rgb, transparency) -> list:
        """The nine material property values with the colour and/or transparency
        replaced; pure, unit-tested."""
        values = [float(v) for v in current]
        if rgb is not None:
            if len(rgb) != 3 or any(not 0 <= c <= 255 for c in rgb):
                raise SolidWorksError(f"rgb is three numbers 0..255 (got {rgb}).")
            values[:3] = [c / 255 for c in rgb]
        if transparency is not None:
            if not 0 <= transparency <= 1:
                raise SolidWorksError(f"transparency runs from 0 (solid) to 1 (clear) (got {transparency}).")
            values[7] = float(transparency)
        return values

    @staticmethod
    def _doubles(values) -> object:
        """A VARIANT array of doubles: a plain list is passed as variants and the
        material values are ignored without a word."""
        return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(v) for v in values])

    def set_material(self, name: str, database: str = "", density_kg_m3: float | None = None) -> dict:
        """Assign a material by name so mass/density reflect a real material.

        name: a material in the SolidWorks database, e.g. '6061 Alloy',
        'AISI 1020', 'ABS', 'Plain Carbon Steel'. database: path to a .sldmat, or
        '' for the default databases. density_kg_m3 makes a material of its own
        under that name instead (say TPU at 1210) that carries only its density;
        the part keeps it, also where the material is unknown. On a SolidWorks
        in another language an English name is found by its material id.
        Returns mass properties (with density).
        """
        if density_kg_m3 is not None and database:
            raise SolidWorksError("Give a database or a density_kg_m3, not both.")
        if density_kg_m3 is not None and density_kg_m3 <= 0:
            raise SolidWorksError(f"density_kg_m3 must be > 0 (got {density_kg_m3}).")
        model = self._require_model()
        part = self._require_part()
        if density_kg_m3 is None:
            part.SetMaterialPropertyName2("", database, name)
        else:
            self._assign_own_material(part, name, density_kg_m3)
        applied_name = self._material_name(part)
        if density_kg_m3 is None and not database and not self._same_name(applied_name, name):
            # SolidWorks in another language names its materials in that
            # language: find the English name's material there by its id
            local_by_id = self._local_materials()
            local = self._localized_material(name, local_by_id)
            if local is None:
                close = difflib.get_close_matches(name, [*self._english_material_ids(), *local_by_id.values()], 5)
                raise SolidWorksError(
                    f"Material '{name}' was not applied (active: '{applied_name}'): it is not in "
                    f"SolidWorks' database. Close names: {', '.join(close) or 'none'}."
                )
            part.SetMaterialPropertyName2("", "", local)
            applied_name, name = self._material_name(part), local
        rebuilt_ok = bool(model.ForceRebuild3(False))
        # Verify by reading the applied name back (robust to re-assignment and to
        # materials near 1000 kg/m^3, where a density heuristic would lie).
        if not self._same_name(applied_name, name):
            raise SolidWorksError(
                f"Material '{name}' was not applied (active: '{applied_name}'). "
                "Check the exact name, e.g. '6061 Alloy', 'AISI 1020', 'ABS'."
            )
        return {
            "ok": True,
            "material": applied_name,
            "rebuild_ok": rebuilt_ok,
            "mass_properties": self.get_mass_properties()["mass_properties"],
        }

    @staticmethod
    def _material_name(part) -> str:
        applied = part.GetMaterialPropertyName2("")
        return (applied[0] if isinstance(applied, (list, tuple)) else applied) or ""

    @staticmethod
    def _same_name(a: str, b: str) -> bool:
        return a.strip().lower() == b.strip().lower()

    @staticmethod
    def _english_material_ids() -> dict:
        """{English name: matid} of SolidWorks' default material database, read
        from an English install (material_ids.json). A material keeps its matid
        in every language; its name is translated."""
        text = resources.files("solidworks_mcp").joinpath("material_ids.json").read_text(encoding="utf-8")
        return json.loads(text)

    @staticmethod
    def _materials_by_id(xml_text: str) -> dict:
        """{matid: name} of a .sldmat's materials; pure, unit-tested."""
        return {
            int(matid): html.unescape(name)
            for name, matid in re.findall(r'<material name="([^"]*)" matid="(\d+)"', xml_text)
        }

    @classmethod
    def _localized_material(cls, english: str, local_by_id: dict) -> str | None:
        """The name of the English-named material in a database of another
        language, matched by matid; None when either lacks it."""
        ids = {n.lower(): i for n, i in cls._english_material_ids().items()}
        matid = ids.get(english.strip().lower())
        return None if matid is None else local_by_id.get(matid)

    def _local_materials(self) -> dict:
        """{matid: name} of the default material database in SolidWorks' own
        language; {} when it is not where an install keeps it."""
        folder = os.path.join(self._sw.GetExecutablePath(), "lang", self._sw.GetCurrentLanguage(), "sldmaterials")
        found = [
            f
            for f in (os.listdir(folder) if os.path.isdir(folder) else [])
            if f.lower() == "solidworks materials.sldmat"
        ]
        if not found:
            return {}
        with open(os.path.join(folder, found[0]), encoding="utf-16") as f:
            return self._materials_by_id(f.read())

    def _assign_own_material(self, part, name: str, density_kg_m3: float) -> None:
        """SolidWorks reads a .sldmat only from its material folders, so one is
        written to a temporary folder that joins them while the material is
        assigned. The part keeps the material's properties once it is gone."""
        folder = tempfile.mkdtemp(prefix="solidworks_mcp_")
        path = os.path.join(folder, f"{MCP_MATERIAL_DATABASE}.sldmat")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._material_xml(name, density_kg_m3))
        folders = self._sw.GetUserPreferenceStringValue(SW_FILE_LOCATIONS_MATERIALS)
        try:
            self._sw.SetUserPreferenceStringValue(
                SW_FILE_LOCATIONS_MATERIALS, f"{folders};{folder}" if folders else folder
            )
            part.SetMaterialPropertyName2("", path, name)
        finally:
            self._sw.SetUserPreferenceStringValue(SW_FILE_LOCATIONS_MATERIALS, folders)
            shutil.rmtree(folder, ignore_errors=True)

    @staticmethod
    def _material_xml(name: str, density_kg_m3: float) -> str:
        """A .sldmat with one material that carries only a density; pure, unit-tested."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<mstns:materials xmlns:mstns="http://www.solidworks.com/sldmaterials" version="2008.03">\n'
            f'  <classification name="{MCP_MATERIAL_DATABASE}">\n'
            f"    <material name={quoteattr(name)}>\n"
            "      <physicalproperties>\n"
            f'        <DENS displayname="Density" value="{float(density_kg_m3)!r}"/>\n'
            "      </physicalproperties>\n"
            "    </material>\n"
            "  </classification>\n"
            "</mstns:materials>\n"
        )
