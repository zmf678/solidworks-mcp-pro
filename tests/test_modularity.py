"""Guardrails for the domain-module split.

These tests do not need SolidWorks and do not import the server (which would
start a COM worker). They fail if a future change silently drops a mixin from the
composed session, shadows a helper across mixins, duplicates a tool name, or
lets a mixin import another mixin (which would create cycles and freeze the MRO).
"""

import ast
import pathlib

from solidworks_mcp.session import SolidWorksSession

SESSION_DIR = pathlib.Path("src/solidworks_mcp/session")
TOOLS_DIR = pathlib.Path("src/solidworks_mcp/tools")
SERVER_FILE = pathlib.Path("src/solidworks_mcp/server.py")

EXPECTED_MIXINS = {
    "CoreMixin",
    "GeometryMixin",
    "SketchingMixin",
    "SolidsMixin",
    "SweepsMixin",
    "HolesMixin",
    "FaceFeaturesMixin",
    "CutsMixin",
    "FilletsMixin",
    "ChamfersShellsMixin",
    "MirrorsMixin",
    "PatternsPlanesMixin",
    "ParametersMixin",
    "FeatureHistoryMixin",
    "PersonSketchMixin",
    "MaterialsMixin",
    "InspectionMixin",
    "PrintabilityMixin",
    "MeshIOMixin",
    "ExportIOMixin",
    "AssemblyCoreMixin",
    "AssemblyMatesMixin",
    "AssemblyAnalysisMixin",
}


def _tool_names() -> list[str]:
    names = []
    for file in sorted(TOOLS_DIR.glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        names.extend(node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.decorator_list)
    return names


def _server_exports() -> tuple[set[str], set[str]]:
    tree = ast.parse(SERVER_FILE.read_text(encoding="utf-8"))
    all_names: set[str] = set()
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            all_names = set(ast.literal_eval(node.value))
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    return all_names, imported


def test_every_domain_mixin_is_composed():
    names = {cls.__name__ for cls in SolidWorksSession.__mro__}
    assert EXPECTED_MIXINS <= names, f"missing mixins: {sorted(EXPECTED_MIXINS - names)}"


def test_no_mixin_shadows_another_mixins_helper():
    seen = {}
    for cls in SolidWorksSession.__mro__:
        if cls is SolidWorksSession or not cls.__module__.startswith("solidworks_mcp.session."):
            continue
        for name, value in vars(cls).items():
            if name.startswith("__") or not callable(value):
                continue
            assert name not in seen, f"{name} is defined in both {seen[name]} and {cls.__name__}"
            seen[name] = cls.__name__


def test_tool_names_are_unique_across_domain_modules():
    names = _tool_names()
    assert len(names) == len(set(names)), "a tool name is declared twice"
    assert len(names) == 88, f"expected 88 tools, found {len(names)}"


def test_server_reexports_every_declared_tool():
    tools = set(_tool_names())
    all_names, imported = _server_exports()
    assert tools <= all_names, f"not in server.__all__: {sorted(tools - all_names)}"
    assert tools <= imported, f"not imported by server.py: {sorted(tools - imported)}"


def test_no_mixin_imports_another_mixin():
    stems = {path.stem for path in SESSION_DIR.glob("*.py") if path.stem not in {"__init__"}}
    allowed = {"_constants", "_decorators"}
    for file in sorted(SESSION_DIR.glob("*.py")):
        if file.name == "__init__.py":
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in stems - allowed:
                raise AssertionError(f"{file.name} imports {node.module}; use self.* instead")
