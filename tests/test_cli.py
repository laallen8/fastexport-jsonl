"""Tests for the to-jsonl/from-jsonl CLI, in particular the --type filter."""

from __future__ import annotations

import io
import json
import sys
import unittest

from fastexport_jsonl.__main__ import main

STREAM = (
    b"blob\nmark :1\ndata 12\nhello world\n"
    b"commit refs/heads/main\n"
    b"mark :2\n"
    b"committer Ada <ada@example.com> 1700000000 -0500\n"
    b"data 15\ninitial commit\n"
    b"M 100644 :1 hello.txt\n"
    b"\n"
    b"reset refs/heads/main\nfrom :2\n"
)


class _FakeStdin:
    """Stands in for sys.stdin; to-jsonl only ever reads sys.stdin.buffer."""

    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


class CLITests(unittest.TestCase):
    def _run(self, argv, stdin_bytes):
        old_stdin, old_stdout = sys.stdin, sys.stdout
        sys.stdin = _FakeStdin(stdin_bytes)
        sys.stdout = io.StringIO()
        try:
            code = main(argv)
            return code, sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout

    def test_to_jsonl_without_filter_emits_every_record(self):
        code, text = self._run(["to-jsonl"], STREAM)
        self.assertEqual(code, 0)
        types = [json.loads(line)["type"] for line in text.splitlines()]
        self.assertEqual(types, ["blob", "commit", "reset"])

    def test_to_jsonl_type_filter_keeps_only_matching_records(self):
        code, text = self._run(["to-jsonl", "--type", "commit"], STREAM)
        self.assertEqual(code, 0)
        records = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "commit")
        self.assertEqual(records[0]["ref"], "refs/heads/main")

    def test_to_jsonl_type_filter_can_be_repeated(self):
        code, text = self._run(["to-jsonl", "--type", "blob", "--type", "reset"], STREAM)
        self.assertEqual(code, 0)
        types = [json.loads(line)["type"] for line in text.splitlines()]
        self.assertEqual(types, ["blob", "reset"])

    def test_to_jsonl_unknown_type_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            main(["to-jsonl", "--type", "nope"])


if __name__ == "__main__":
    unittest.main()
