"""Command-line entry point.

    git fast-export --all | python -m fastexport_jsonl to-jsonl > history.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .parser import FastExportReader, ParseError


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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="fastexport-jsonl")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "to-jsonl",
        help="read a git fast-export stream on stdin, write JSON Lines to stdout",
    )
    args = parser.parse_args(argv)
    if args.command == "to-jsonl":
        return _to_jsonl()
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
