"""Small content-defined deduplication experiment, not an encrypted backup system."""

from .chunker import Config, chunks, spans
from .archive import pack, unpack, inspect_archive

__all__ = ["Config", "chunks", "spans", "pack", "unpack", "inspect_archive"]
