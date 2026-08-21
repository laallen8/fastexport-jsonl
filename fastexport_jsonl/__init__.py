"""Streaming conversion between git fast-export streams and JSON Lines."""

from .parser import FastExportReader, ParseError

__all__ = ["FastExportReader", "ParseError"]
__version__ = "0.1.0"
