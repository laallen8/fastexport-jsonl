"""Command-line entry point.

    git fast-export --all | python -m fastexport_jsonl to-jsonl > history.jsonl
    git fast-export --all | python -m fastexport_jsonl to-jsonl --type commit > commits.jsonl
    python -m fastexport_jsonl from-jsonl < history.jsonl | git fast-import
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional, Set

from .parser import FastExportReader, ParseError
from .writer import FastExportWriter


def _to_jsonl(types: Optional[Set[str]]) -> int:
    reader = FastExportReader(sys.stdin.buffer)
    try:
        for record in reader.records():
            if types is not None and record.get("type") not in types:
                continue
            sys.stdout.write(json.dumps(record))
            sys.stdout.write("\n")
    except ParseError as exc:
        print(f"fastexport-jsonl: {exc}", file=sys.stderr)
        return 1
    return 0


def _from_jsonl() -> int:
    writer = FastExportWriter(sys.stdout.buffer)
    for lineno, line in enumerate(sys.stdin, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"fastexport-jsonl: line {lineno}: invalid JSON: {exc}", file=sys.stderr)
            return 1
        try:
            writer.write_record(record)
        except ParseError as exc:
            print(f"fastexport-jsonl: line {lineno}: {exc}", file=sys.stderr)
            return 1
    return 0


_RECORD_TYPES = ("blob", "commit", "reset", "tag", "done", "other")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="fastexport-jsonl")
    sub = parser.add_subparsers(dest="command", required=True)
    to_jsonl = sub.add_parser(
        "to-jsonl",
        help="read a git fast-export stream on stdin, write JSON Lines to stdout",
    )
    to_jsonl.add_argument(
        "--type",
        dest="types",
        action="append",
        choices=_RECORD_TYPES,
        help="only emit records of this type; repeat to allow several (default: all)",
    )
    sub.add_parser(
        "from-jsonl",
        help="read JSON Lines on stdin, write a git fast-import stream to stdout",
    )
    args = parser.parse_args(argv)
    if args.command == "to-jsonl":
        types = set(args.types) if args.types else None
        return _to_jsonl(types)
    if args.command == "from-jsonl":
        return _from_jsonl()
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
