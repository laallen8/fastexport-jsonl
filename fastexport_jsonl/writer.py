"""Writer that turns JSON Lines records back into a fast-export stream.

This is the mirror of `FastExportReader`: given the same dicts the
reader produces, it writes bytes that `git fast-import` (or the reader
itself) can consume. It only emits the exact-length `data <n>` form,
never the `data <<DELIM` form, so every payload is written with a
single length prefix and no scanning for a delimiter is needed.
"""

from __future__ import annotations

import base64
from typing import BinaryIO, Dict, Iterable

from .parser import ParseError

_QUOTE_CHARS = (" ", '"', "\\")


class FastExportWriter:
    """Writes one fast-export command per record to a binary stream."""

    def __init__(self, stream: BinaryIO):
        self._stream = stream

    def write(self, records: Iterable[Dict]) -> None:
        for record in records:
            self.write_record(record)

    def write_record(self, record: Dict) -> None:
        kind = record.get("type")
        if kind == "blob":
            self._write_blob(record)
        elif kind == "commit":
            self._write_commit(record)
        elif kind == "reset":
            self._write_reset(record)
        elif kind == "tag":
            self._write_tag(record)
        elif kind == "done":
            self._write_line(b"done")
        elif kind == "other":
            self._write_line(_encode(_require(record, "line")))
        else:
            raise ParseError(f"unrecognized record type: {kind!r}")

    # -- low-level stream handling ------------------------------------

    def _write_line(self, line: bytes) -> None:
        self._stream.write(line)
        self._stream.write(b"\n")

    def _write_data(self, record: Dict, encoding_key: str, data_key: str) -> None:
        payload = _decode_payload(_require(record, encoding_key), _require(record, data_key))
        # No trailing newline beyond the payload itself: the exact-length
        # `data <n>` form is byte-counted, and the reader advances straight
        # to the next line once it has consumed those `n` bytes.
        self._write_line(b"data " + str(len(payload)).encode("ascii"))
        self._stream.write(payload)

    # -- command writers ------------------------------------------------

    def _write_blob(self, record: Dict) -> None:
        self._write_line(b"blob")
        if "mark" in record:
            self._write_line(b"mark " + _encode(record["mark"]))
        self._write_data(record, "encoding", "data")

    def _write_commit(self, record: Dict) -> None:
        self._write_line(b"commit " + _encode(_require(record, "ref")))
        if "mark" in record:
            self._write_line(b"mark " + _encode(record["mark"]))
        if "author" in record:
            self._write_line(b"author " + _encode(record["author"]))
        self._write_line(b"committer " + _encode(_require(record, "committer")))
        self._write_data(record, "message_encoding", "message")
        if "from" in record:
            self._write_line(b"from " + _encode(record["from"]))
        for merge in record.get("merges", []):
            self._write_line(b"merge " + _encode(merge))
        for change in record.get("changes", []):
            self._write_line(_format_change(change))

    def _write_reset(self, record: Dict) -> None:
        self._write_line(b"reset " + _encode(_require(record, "ref")))
        if "from" in record:
            self._write_line(b"from " + _encode(record["from"]))

    def _write_tag(self, record: Dict) -> None:
        self._write_line(b"tag " + _encode(_require(record, "name")))
        self._write_line(b"from " + _encode(_require(record, "from")))
        if "tagger" in record:
            self._write_line(b"tagger " + _encode(record["tagger"]))
        self._write_data(record, "message_encoding", "message")


def _require(record: Dict, key: str):
    try:
        return record[key]
    except KeyError:
        raise ParseError(f"{record.get('type')!r} record is missing {key!r}") from None


def _encode(text: str) -> bytes:
    return text.encode("utf-8", errors="surrogateescape")


def _decode_payload(encoding: str, data: str) -> bytes:
    if encoding == "utf-8":
        return data.encode("utf-8")
    if encoding == "base64":
        return base64.b64decode(data)
    raise ParseError(f"unrecognized payload encoding: {encoding!r}")


def _format_change(change: Dict) -> bytes:
    op = _require(change, "op")
    if op == "deleteall":
        return b"deleteall"
    if op == "M":
        return b"M %s %s %s" % (
            _encode(_require(change, "mode")),
            _encode(_require(change, "dataref")),
            _encode(_quote(_require(change, "path"))),
        )
    if op == "D":
        return b"D " + _encode(_quote(_require(change, "path")))
    if op in ("C", "R"):
        return b"%s %s %s" % (
            op.encode("ascii"),
            _encode(_quote(_require(change, "src"))),
            _encode(_quote(_require(change, "dst"))),
        )
    if op == "N":
        return b"N %s %s" % (
            _encode(_require(change, "dataref")),
            _encode(_require(change, "committish")),
        )
    raise ParseError(f"unrecognized file change op: {op!r}")


def _quote(path: str) -> str:
    """Quote a path the way fast-import expects, only when it's ambiguous
    otherwise: unquoted paths are split on the first space when there are
    two of them on a line (`C`/`R`), so any space, quote, or backslash has
    to be escaped and wrapped in quotes."""
    if not any(c in path for c in _QUOTE_CHARS):
        return path
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
