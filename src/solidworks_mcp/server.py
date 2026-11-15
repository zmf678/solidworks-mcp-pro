"""MCP server entry point.

The FastMCP application lives in :mod:`solidworks_mcp.app`; the 88 tool
declarations live in :mod:`solidworks_mcp.tools`. This module keeps the public
``python -m solidworks_mcp.server`` / ``solidworks-mcp`` entry point and
re-exports the tool functions for scripts that import them from here.
"""

import argparse
import sys

from .app import (
    _call,
    _call_without_solidworks,
    _failure,
    _session,
    _worker,
    guide,
    mcp,
)
from .selftest import main as run_selftest
from .tools.assembly import (
    add_mate,
    check_interference,
    check_motion,
    delete_component,
    delete_mate,
    get_assembly_bounding_box,
    insert_component,
    list_components,
    measure_distance,
    new_assembly,
    open_assembly,
    replace_component,
    save_assembly,
    set_component_transform,
    suppress_mate,
    swept_region,
)
from .tools.core import get_status, new_part
from .tools.features import (
    add_boss_on_face,
    add_chamfer,
    add_circular_pattern,
    add_counterbore_hole,
    add_extruded_profile_on_face,
    add_extruded_slot,
    add_fillet,
    add_full_round,
    add_hole,
    add_hole_on_face,
    add_hole_wizard,
    add_linear_pattern,
    add_mirror,
    add_shell,
    add_text_on_face,
    add_thread,
    cut_offset_pocket,
    cut_profile,
    cut_profile_on_face,
    cut_slot,
)
from .tools.inspection import (
    check_printability,
    combine_bodies,
    compare_with_mesh,
    delete_equation,
    delete_feature,
    get_bounding_box,
    get_mass_properties,
    list_bodies,
    list_dimensions,
    list_edges,
    list_equations,
    list_faces,
    list_features,
    rebuild,
    reorder_feature,
    set_appearance,
    set_dimension,
    set_equation,
    set_equations,
    set_material,
    slice_mesh,
    split_body,
    suppress_feature,
)
from .tools.io import (
    activate_document,
    close_part,
    export,
    list_documents,
    make_drawing,
    open_part,
    save_part,
    screenshot,
)
from .tools.sketch import add_sketch, cut_sketch, extrude_sketch, read_sketch
from .tools.solids import (
    add_box,
    add_cone,
    add_cylinder,
    add_disc,
    add_extruded_profile,
    add_extruded_profile_on_plane,
    add_extruded_spline,
    add_lofted_solid,
    add_plane,
    add_revolved_profile,
    add_rib,
    add_swept_pipe,
    add_swept_profile,
    cut_profile_through_plane,
    loft_sketches,
)

__all__ = [
    "_call",
    "_call_without_solidworks",
    "_failure",
    "_session",
    "_worker",
    "activate_document",
    "add_boss_on_face",
    "add_box",
    "add_chamfer",
    "add_circular_pattern",
    "add_cone",
    "add_counterbore_hole",
    "add_cylinder",
    "add_disc",
    "add_extruded_profile",
    "add_extruded_profile_on_face",
    "add_extruded_profile_on_plane",
    "add_extruded_slot",
    "add_extruded_spline",
    "add_fillet",
    "add_full_round",
    "add_hole",
    "add_hole_on_face",
    "add_hole_wizard",
    "add_linear_pattern",
    "add_lofted_solid",
    "add_mate",
    "add_mirror",
    "add_plane",
    "add_revolved_profile",
    "add_rib",
    "add_shell",
    "add_sketch",
    "add_swept_pipe",
    "add_swept_profile",
    "add_text_on_face",
    "add_thread",
    "check_interference",
    "check_motion",
    "check_printability",
    "close_part",
    "combine_bodies",
    "compare_with_mesh",
    "cut_offset_pocket",
    "cut_profile",
    "cut_profile_on_face",
    "cut_profile_through_plane",
    "cut_sketch",
    "cut_slot",
    "delete_component",
    "delete_equation",
    "delete_feature",
    "delete_mate",
    "export",
    "extrude_sketch",
    "get_assembly_bounding_box",
    "get_bounding_box",
    "get_mass_properties",
    "get_status",
    "guide",
    "insert_component",
    "list_bodies",
    "list_components",
    "list_dimensions",
    "list_documents",
    "list_edges",
    "list_equations",
    "list_faces",
    "list_features",
    "loft_sketches",
    "main",
    "make_drawing",
    "mcp",
    "measure_distance",
    "new_assembly",
    "new_part",
    "open_assembly",
    "open_part",
    "read_sketch",
    "rebuild",
    "reorder_feature",
    "replace_component",
    "run_selftest",
    "save_assembly",
    "save_part",
    "screenshot",
    "set_appearance",
    "set_component_transform",
    "set_dimension",
    "set_equation",
    "set_equations",
    "set_material",
    "slice_mesh",
    "split_body",
    "suppress_feature",
    "suppress_mate",
    "swept_region",
]


def main() -> None:
    """Entry point: run the MCP server over stdio, or the selftest with --selftest."""
    parser = argparse.ArgumentParser(prog="solidworks-mcp", description="MCP server for a running SolidWorks.")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="check this machine's SolidWorks with a few small parts, print a report and exit",
    )
    selftest = parser.parse_args().selftest
    try:
        if not selftest:
            mcp.run()
        elif _worker is None:
            sys.exit(run_selftest(_session))
        else:
            sys.exit(_worker.submit(lambda: run_selftest(_session)).result())
    finally:
        if _worker is not None:
            _worker.shutdown()
