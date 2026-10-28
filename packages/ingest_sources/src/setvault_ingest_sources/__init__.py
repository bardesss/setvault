from importlib.metadata import PackageNotFoundError, version

from setvault_ingest_sources.base import Candidate, IngestSource, SourceError

try:
    __version__ = version("setvault-ingest-sources")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["Candidate", "IngestSource", "SourceError", "__version__"]
