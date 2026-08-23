"""Command-line entry point.

    git fast-export --all | python -m fastexport_jsonl to-jsonl > history.jsonl
    python -m fastexport_jsonl from-jsonl < history.jsonl | git fast-import
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .parser import FastExportReader, ParseError
from .writer import FastExportWriter


def _to_jsonl() -> int:
    reader = FastExportReader(sys.stdin.buffer)
    try:
        for record in reader.records():
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="fastexport-jsonl")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "to-jsonl",
        help="read a git fast-export stream on stdin, write JSON Lines to stdout",
    )
    sub.add_parser(
        "from-jsonl",
        help="read JSON Lines on stdin, write a git fast-import stream to stdout",
    )
    args = parser.parse_args(argv)
    if args.command == "to-jsonl":
        return _to_jsonl()
    if args.command == "from-jsonl":
        return _from_jsonl()
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
