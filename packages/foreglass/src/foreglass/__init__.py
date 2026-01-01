"""ForeGlass: optional reader for public ForeGlass artifacts, built on comuvia.

Reads the published artifacts explicitly and within bounds, retains their exact bytes,
keeps an accepted snapshot that incomplete intake can never replace, and normalizes only
the semantics those artifacts declare into comuvia records. Importing or constructing
anything makes no network request.
"""

__version__ = "0.1.0"

from .capabilities import capabilities
from .catalog import FIELD_MEANINGS, Lane, LaneCatalog, Reading, read_reading
from .client import ARTIFACTS, Artifact, HttpsTransport, PublicClient
from .intake import Finding, IntakeResult, Snapshot, SnapshotArchive, replay_bundle
from .normalize import NormalizationError, NormalizationResult, NotMapped, encode_identifier, normalize

__all__ = [
    "ARTIFACTS",
    "Artifact",
    "FIELD_MEANINGS",
    "Finding",
    "HttpsTransport",
    "IntakeResult",
    "Lane",
    "LaneCatalog",
    "NormalizationError",
    "NormalizationResult",
    "NotMapped",
    "PublicClient",
    "Reading",
    "Snapshot",
    "SnapshotArchive",
    "capabilities",
    "encode_identifier",
    "normalize",
    "read_reading",
    "replay_bundle",
]
