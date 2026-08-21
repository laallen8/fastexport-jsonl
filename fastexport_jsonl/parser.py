"""Streaming reader for the git fast-export command language.

`git fast-export` prints history as a sequence of line-based commands
(`commit`, `blob`, `reset`, `tag`, ...) mixed with raw byte payloads
whose length is given up front. It's a fine format for feeding into
`git fast-import`, but it's awkward to grep, diff, or load into a
dataframe. This module turns that stream into a sequence of plain
dicts, one per command, that are easy to serialize as JSON.

The parser only ever holds one line or one data payload in memory at
a time, so converting a stream that is gigabytes long doesn't require
gigabytes of RAM.
"""

from __future__ import annotations

import base64
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple


class ParseError(ValueError):
    """Raised when the input doesn't look like a fast-export stream."""


_CHANGE_PREFIXES = (b"M ", b"D ", b"C ", b"R ", b"N ")


class FastExportReader:
    """Reads a git fast-export stream and yields one record per command."""

    def __init__(self, stream: BinaryIO):
        self._stream = stream
        self._pushed_back: Optional[bytes] = None

    def records(self) -> Iterator[Dict]:
        while True:
            line = self._next_line()
            if line is None:
                return
            if line == b"" or line.isspace():
                continue
            if line.startswith(b"#"):
                continue
            if line.startswith(b"blob"):
                yield self._read_blob()
            elif line.startswith(b"commit "):
                yield self._read_commit(line)
            elif line.startswith(b"reset "):
                yield self._read_reset(line)
            elif line.startswith(b"tag "):
                yield self._read_tag(line)
            elif line.startswith(b"done"):
                yield {"type": "done"}
            else:
                # feature / option / progress / checkpoint / cat-blob /
                # ls / get-mark / alias -- passed through verbatim so
                # nothing from the input is silently dropped.
                yield {"type": "other", "line": _decode(line.rstrip(b"\n"))}

    # -- low-level stream handling ------------------------------------

    def _next_line(self) -> Optional[bytes]:
        if self._pushed_back is not None:
            line = self._pushed_back
            self._pushed_back = None
            return line
        line = self._stream.readline()
        return None if line == b"" else line

    def _push_back(self, line: bytes) -> None:
        if self._pushed_back is not None:
            raise ParseError("internal error: double push-back")
        self._pushed_back = line

    def _read_exact(self, size: int) -> bytes:
        parts: List[bytes] = []
        remaining = size
        while remaining:
            chunk = self._stream.read(remaining)
            if not chunk:
                raise ParseError("stream ended in the middle of a data block")
            parts.append(chunk)
            remaining -= len(chunk)
        return b"".join(parts)

    def _read_data_block(self) -> Dict:
        header = self._next_line()
        if header is None or not header.startswith(b"data"):
            raise ParseError(f"expected a data command, got {header!r}")
        rest = header[len(b"data "):].rstrip(b"\n")
        if rest.startswith(b"<<"):
            return _encode_payload(self._read_delimited_data(rest[2:]))
        try:
            length = int(rest)
        except ValueError as exc:
            raise ParseError(f"bad data length: {rest!r}") from exc
        return _encode_payload(self._read_exact(length))

    def _read_delimited_data(self, delim: bytes) -> bytes:
        marker = delim + b"\n"
        chunks: List[bytes] = []
        while True:
            line = self._next_line()
            if line is None:
                raise ParseError("stream ended before delimited data terminator")
            if line == marker:
                return b"".join(chunks)
            chunks.append(line)

    # -- command readers ------------------------------------------------

    def _read_blob(self) -> Dict:
        record: Dict = {"type": "blob"}
        line = self._next_line()
        if line is not None and line.startswith(b"mark "):
            record["mark"] = _decode(line[len(b"mark "):].rstrip(b"\n"))
            line = self._next_line()
        if line is None or not line.startswith(b"data"):
            raise ParseError("blob command without a data block")
        self._push_back(line)
        record.update(self._read_data_block())
        return record

    def _read_commit(self, first_line: bytes) -> Dict:
        record: Dict = {
            "type": "commit",
            "ref": _decode(first_line[len(b"commit "):].rstrip(b"\n")),
        }
        line = self._next_line()

        if line is not None and line.startswith(b"mark "):
            record["mark"] = _decode(line[len(b"mark "):].rstrip(b"\n"))
            line = self._next_line()

        if line is not None and line.startswith(b"author "):
            record["author"] = _decode(line[len(b"author "):].rstrip(b"\n"))
            line = self._next_line()

        if line is None or not line.startswith(b"committer "):
            raise ParseError("commit is missing a committer line")
        record["committer"] = _decode(line[len(b"committer "):].rstrip(b"\n"))

        message = self._read_data_block()
        record["message"] = message["data"]
        record["message_encoding"] = message["encoding"]

        line = self._next_line()
        if line is not None and line.startswith(b"from "):
            record["from"] = _decode(line[len(b"from "):].rstrip(b"\n"))
            line = self._next_line()

        merges: List[str] = []
        while line is not None and line.startswith(b"merge "):
            merges.append(_decode(line[len(b"merge "):].rstrip(b"\n")))
            line = self._next_line()
        if merges:
            record["merges"] = merges

        changes: List[Dict] = []
        while line is not None and (
            line.startswith(_CHANGE_PREFIXES) or line.startswith(b"deleteall")
        ):
            changes.append(_parse_change(line))
            line = self._next_line()
        record["changes"] = changes

        if line is not None and line != b"\n":
            self._push_back(line)
        return record

    def _read_reset(self, first_line: bytes) -> Dict:
        record: Dict = {
            "type": "reset",
            "ref": _decode(first_line[len(b"reset "):].rstrip(b"\n")),
        }
        line = self._next_line()
        if line is not None and line.startswith(b"from "):
            record["from"] = _decode(line[len(b"from "):].rstrip(b"\n"))
        elif line is not None and line != b"\n":
            self._push_back(line)
        return record

    def _read_tag(self, first_line: bytes) -> Dict:
        record: Dict = {
            "type": "tag",
            "name": _decode(first_line[len(b"tag "):].rstrip(b"\n")),
        }
        line = self._next_line()
        if line is None or not line.startswith(b"from "):
            raise ParseError("tag command is missing its 'from' line")
        record["from"] = _decode(line[len(b"from "):].rstrip(b"\n"))

        line = self._next_line()
        if line is not None and line.startswith(b"tagger "):
            record["tagger"] = _decode(line[len(b"tagger "):].rstrip(b"\n"))
            line = self._next_line()

        if line is None or not line.startswith(b"data"):
            raise ParseError("tag command is missing its message data block")
        self._push_back(line)
        message = self._read_data_block()
        record["message"] = message["data"]
        record["message_encoding"] = message["encoding"]
        return record


def _decode(raw: bytes) -> str:
    # ref names and marks are meant to be ASCII, but surrogateescape
    # keeps us from blowing up on a stray non-UTF-8 byte instead of
    # aborting an otherwise good conversion.
    return raw.decode("utf-8", errors="surrogateescape")


def _encode_payload(payload: bytes) -> Dict:
    try:
        return {"encoding": "utf-8", "data": payload.decode("utf-8")}
    except UnicodeDecodeError:
        return {"encoding": "base64", "data": base64.b64encode(payload).decode("ascii")}


def _parse_change(line: bytes) -> Dict:
    text = _decode(line.rstrip(b"\n"))
    if text == "deleteall":
        return {"op": "deleteall"}
    op, rest = text[0], text[2:]
    if op == "M":
        mode, dataref, path = rest.split(" ", 2)
        return {"op": "M", "mode": mode, "dataref": dataref, "path": _unquote(path)}
    if op == "D":
        return {"op": "D", "path": _unquote(rest)}
    if op in ("C", "R"):
        src, dst = _split_two_paths(rest)
        return {"op": op, "src": src, "dst": dst}
    if op == "N":
        dataref, committish = rest.split(" ", 1)
        return {"op": "N", "dataref": dataref, "committish": committish}
    raise ParseError(f"unrecognized file change line: {text!r}")


def _split_two_paths(rest: str) -> Tuple[str, str]:
    src, remainder = _take_path(rest)
    dst, _ = _take_path(remainder)
    return src, dst


def _take_path(text: str) -> Tuple[str, str]:
    """Split one (possibly C-quoted) path off the front of `text`."""
    if text.startswith('"'):
        i = 1
        while i < len(text):
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == '"':
                i += 1
                break
            i += 1
        token, remainder = text[:i], text[i:]
        if remainder.startswith(" "):
            remainder = remainder[1:]
        return _unquote(token), remainder
    if " " in text:
        path, remainder = text.split(" ", 1)
        return path, remainder
    return text, ""


def _unquote(token: str) -> str:
    if token.startswith('"') and token.endswith('"') and len(token) >= 2:
        body = token[1:-1]
        out: List[str] = []
        i = 0
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body):
                out.append(body[i + 1])
                i += 2
            else:
                out.append(body[i])
                i += 1
        return "".join(out)
    return token
