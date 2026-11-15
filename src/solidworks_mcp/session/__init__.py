"""SolidWorks operations, split into domain mixins.

The public entry point stays :class:`SolidWorksSession`. All methods must run on
the dedicated COM worker thread; the server does that through
:func:`solidworks_mcp.com_worker.ComWorker.call`.

The split is behavioural: methods were moved verbatim into domain modules. Shared
state lives on the composed class, so cross-domain helpers remain available via
``self`` exactly as before.
"""

from ._constants import SessionConstants
from .assembly_analysis import AssemblyAnalysisMixin
from .assembly_core import AssemblyCoreMixin
from .assembly_mates import AssemblyMatesMixin
from .chamfers_shells import ChamfersShellsMixin
from .core import CoreMixin
from .cuts import CutsMixin
from .export_io import ExportIOMixin
from .face_features import FaceFeaturesMixin
from .feature_history import FeatureHistoryMixin
from .fillets import FilletsMixin
from .geometry import GeometryMixin
from .holes import HolesMixin
from .inspection import InspectionMixin
from .materials import MaterialsMixin
from .mesh_io import MeshIOMixin
from .mirrors import MirrorsMixin
from .parameters import ParametersMixin
from .patterns_planes import PatternsPlanesMixin
from .person_sketch import PersonSketchMixin
from .printability import PrintabilityMixin
from .sketching import SketchingMixin
from .solids import SolidsMixin
from .sweeps import SweepsMixin

__all__ = ["SolidWorksSession"]


class SolidWorksSession(
    CoreMixin,
    GeometryMixin,
    SketchingMixin,
    SolidsMixin,
    SweepsMixin,
    HolesMixin,
    FaceFeaturesMixin,
    CutsMixin,
    FilletsMixin,
    ChamfersShellsMixin,
    MirrorsMixin,
    PatternsPlanesMixin,
    ParametersMixin,
    FeatureHistoryMixin,
    PersonSketchMixin,
    MaterialsMixin,
    InspectionMixin,
    PrintabilityMixin,
    MeshIOMixin,
    ExportIOMixin,
    AssemblyCoreMixin,
    AssemblyMatesMixin,
    AssemblyAnalysisMixin,
    SessionConstants,
):
    """Holds the SolidWorks connection and the current part or assembly document."""
