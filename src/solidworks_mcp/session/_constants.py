"""Class-level constants shared by the session mixins."""

from ..constants import (
    SW_DOC_ASSEMBLY,
    SW_DOC_DRAWING,
    SW_DOC_PART,
    SW_ISO_SCREW_CLEARANCES,
    SW_ISO_SOCKET_COUNTERSUNK,
    SW_ISO_SOCKET_HEAD_CAP,
    SW_ISO_TAPPED_HOLE,
    SW_WZD_COUNTERBORE,
    SW_WZD_COUNTERSINK,
    SW_WZD_HOLE,
    SW_WZD_TAP,
)


class SessionConstants:
    """Constants that used to live on the monolithic SolidWorksSession class."""

    _DOC_TYPES = {SW_DOC_PART: "part", SW_DOC_ASSEMBLY: "assembly", SW_DOC_DRAWING: "drawing"}

    _IMPORT_LIMIT_MB = 30  # a 77 MB STEP ran past the 120 s call limit

    _DEFAULT_PLANE_AXES = {
        "front": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        "top": ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
        "right": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    }

    _Z_UP_FRONT_AXES = ((0, 1, 0), (0, 0, 1), (1, 0, 0))

    _FACE_SIDES = ("outer", "inner")

    _DIRECTIONS = {
        "+x": (1.0, 0.0, 0.0),
        "-x": (-1.0, 0.0, 0.0),
        "+y": (0.0, 1.0, 0.0),
        "-y": (0.0, -1.0, 0.0),
        "+z": (0.0, 0.0, 1.0),
        "-z": (0.0, 0.0, -1.0),
    }

    _EDGE_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}

    _ON_FACE_TOLERANCE_MM = 1e-3

    _PICK_ABOVE_MM = 0.01

    _EDGE_POINT_TOLERANCE_MM = 0.01

    _THREAD_DIAMETER_TOLERANCE_MM = 0.01

    _WIZARD_KINDS = {
        "clearance": (SW_WZD_HOLE, SW_ISO_SCREW_CLEARANCES),
        "counterbore": (SW_WZD_COUNTERBORE, SW_ISO_SOCKET_HEAD_CAP),
        "countersink": (SW_WZD_COUNTERSINK, SW_ISO_SOCKET_COUNTERSUNK),
        "tapped": (SW_WZD_TAP, SW_ISO_TAPPED_HOLE),
    }

    _WIZARD_THREADS = ("cosmetic", "modeled")

    _MAX_FILLET_TRIALS = 200

    _RADIUS_STEPS = 8

    _MAX_RADIUS_SEARCHES = 6

    _VERTEX_TOLERANCE_MM = 0.01

    _CHAMFER_ANGLE_TOLERANCE_DEG = 0.5

    _NON_SEED_TYPES = {
        "DetailCabinet",
        "Fillet",
        "Chamfer",
        "Shell",
        "LPattern",
        "CircPattern",
        "LocalLPattern",
        "LocalCirPattern",
        "MirrorSolid",
        "MirrorPattern",
        "RefPlane",
        "RefAxis",
        "ProfileFeature",
        "OriginProfileFeature",
    }

    _CYL_AXIS_TOLERANCE_MM = 1.0

    _AXIS_PLANES = {"x": ("front", "top"), "y": ("front", "right"), "z": ("top", "right")}

    _PLANE_NORMALS = {"front": (0.0, 0.0, 1.0), "top": (0.0, 1.0, 0.0), "right": (1.0, 0.0, 0.0)}

    _GONE_HRESULTS = {-2147023174, -2147023170, -2147417848}

    _MIRROR_AXES = {"front": "z", "top": "y", "right": "x"}

    _REFERENCE_TYPES = ("RefPlane", "RefAxis", "RefPoint")

    _DEFAULT_APPEARANCE = (0.8, 0.8, 0.8, 1.0, 1.0, 0.5, 0.4, 0.0, 0.0)

    _CURVE_TYPES = {3001: "line", 3002: "circle"}  # ICurve.Identity

    _BODY_OPERATIONS = {"add": 15903, "subtract": 15902, "common": 15901}  # swBodyOperationType_e

    _MAX_WALL_SAMPLES = 100_000  # rays per check; beyond that the samples spread out

    _EDGE_PROBE_MM = 0.4  # how far below an edge its support must be: two layers

    _EDGE_SAMPLE_MM = 0.5  # spacing of the probes along an edge

    _EDGE_MIN_STRETCH_MM = 1.0  # shorter loose bits a slicer bridges: on curved parts they were noise

    _WALL_BATCH_RAYS = 2000  # rays per call to SolidWorks

    _WALL_TIME_S = 60.0  # a call may take 120 s: 24064 rays on a small cap took 151

    _MESH_EXPORT_FORMATS = {"stl", "3mf"}

    _TRANSFORM_TOLERANCE_MM = 1e-6

    _ROTATION_TOLERANCE = 1e-9

    _ON_COMPONENT_FACE_MM = 0.01

    _MATE_DISTANCE_TOLERANCE_MM = 1e-3

    _MATE_ANGLE_TOLERANCE_DEG = 0.01

    _MATE_EXPECTED_ANGLE_DEG = {"parallel": 0.0, "perpendicular": 90.0}
