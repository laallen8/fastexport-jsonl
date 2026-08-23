"""Streaming conversion between git fast-export streams and JSON Lines."""

from .parser import FastExportReader, ParseError
from .writer import FastExportWriter

__all__ = ["FastExportReader", "FastExportWriter", "ParseError"]
__version__ = "0.1.0"
