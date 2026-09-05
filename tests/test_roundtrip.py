"""Round-trip tests: fast-export bytes -> records -> JSON -> records -> bytes.

The fixture below is hand-built rather than pulled from a real `git
fast-export` run, since there's no shell access here to generate one. It
still exercises the same shapes a real export produces: both `data`
forms (exact-length and delimited), a non-UTF-8 blob, a merge commit
with every file-change op, and a tag - so it stands in for "a real repo
history" until an actual one can be piped through this by hand.
"""

from __future__ import annotations

import base64
import io
import json
import unittest

from fastexport_jsonl import FastExportReader, FastExportWriter
from fastexport_jsonl.writer import _DELIMITED_THRESHOLD


def _data(payload: bytes) -> bytes:
    return b"data " + str(len(payload)).encode("ascii") + b"\n" + payload


AUTHOR = b"Ada Lovelace <ada@example.com> 1700000000 -0500"
TAGGER = b"Ada Lovelace <ada@example.com> 1700000100 -0500"

BLOB1 = b"blob\nmark :1\n" + _data(b"hello world\n")

BLOB2 = (
    b"blob\n"
    b"mark :2\n"
    b"data <<END_OF_BLOB\n"
    b"line one\n"
    b"line two\n"
    b"END_OF_BLOB\n"
)

BINARY_PAYLOAD = bytes([0, 1, 2, 255, 254, 253, 0x80, 0x81])
BLOB3 = b"blob\nmark :3\n" + _data(BINARY_PAYLOAD)

COMMIT1_MESSAGE = b"initial commit\n\nAdds hello.txt\n"
COMMIT1 = (
    b"commit refs/heads/main\n"
    b"mark :4\n"
    b"author " + AUTHOR + b"\n"
    b"committer " + AUTHOR + b"\n"
    + _data(COMMIT1_MESSAGE)
    + b"M 100644 :1 hello.txt\n"
    b"\n"
)

COMMIT2_MESSAGE = b"add more files\n"
COMMIT2 = (
    b"commit refs/heads/main\n"
    b"mark :5\n"
    b"author " + AUTHOR + b"\n"
    b"committer " + AUTHOR + b"\n"
    + _data(COMMIT2_MESSAGE)
    + b"from :4\n"
    b"merge :2\n"
    b"deleteall\n"
    b'M 100644 :2 "dir with space/notes.txt"\n'
    b"D old.txt\n"
    b"C src.txt dst.txt\n"
    b"R oldname.txt newname.txt\n"
    b"N :3 :4\n"
    b"\n"
)

RESET = b"reset refs/heads/feature\nfrom :5\n"

TAG_MESSAGE = b"Release 1.0\n"
TAG = (
    b"tag v1.0\n"
    b"from :5\n"
    b"tagger " + TAGGER + b"\n"
    + _data(TAG_MESSAGE)
)

OTHER = b"progress done with batch 1\n"
DONE = b"done\n"

SAMPLE_STREAM = BLOB1 + BLOB2 + BLOB3 + COMMIT1 + COMMIT2 + RESET + TAG + OTHER + DONE

EXPECTED = [
    {"type": "blob", "mark": ":1", "encoding": "utf-8", "data": "hello world\n"},
    {"type": "blob", "mark": ":2", "encoding": "utf-8", "data": "line one\nline two\n"},
    {
        "type": "blob",
        "mark": ":3",
        "encoding": "base64",
        "data": base64.b64encode(BINARY_PAYLOAD).decode("ascii"),
    },
    {
        "type": "commit",
        "ref": "refs/heads/main",
        "mark": ":4",
        "author": AUTHOR.decode("ascii"),
        "committer": AUTHOR.decode("ascii"),
        "message": COMMIT1_MESSAGE.decode("ascii"),
        "message_encoding": "utf-8",
        "changes": [{"op": "M", "mode": "100644", "dataref": ":1", "path": "hello.txt"}],
    },
    {
        "type": "commit",
        "ref": "refs/heads/main",
        "mark": ":5",
        "author": AUTHOR.decode("ascii"),
        "committer": AUTHOR.decode("ascii"),
        "message": COMMIT2_MESSAGE.decode("ascii"),
        "message_encoding": "utf-8",
        "from": ":4",
        "merges": [":2"],
        "changes": [
            {"op": "deleteall"},
            {"op": "M", "mode": "100644", "dataref": ":2", "path": "dir with space/notes.txt"},
            {"op": "D", "path": "old.txt"},
            {"op": "C", "src": "src.txt", "dst": "dst.txt"},
            {"op": "R", "src": "oldname.txt", "dst": "newname.txt"},
            {"op": "N", "dataref": ":3", "committish": ":4"},
        ],
    },
    {"type": "reset", "ref": "refs/heads/feature", "from": ":5"},
    {
        "type": "tag",
        "name": "v1.0",
        "from": ":5",
        "tagger": TAGGER.decode("ascii"),
        "message": TAG_MESSAGE.decode("ascii"),
        "message_encoding": "utf-8",
    },
    {"type": "other", "line": "progress done with batch 1"},
    {"type": "done"},
]


class RoundTripTests(unittest.TestCase):
    def test_parses_sample_stream_into_expected_records(self):
        reader = FastExportReader(io.BytesIO(SAMPLE_STREAM))
        self.assertEqual(list(reader.records()), EXPECTED)

    def test_records_survive_a_json_lines_hop(self):
        # This is the point of the whole tool: dicts have to come out the
        # other side of json.dumps/json.loads unchanged, not just be
        # "close enough" (e.g. int marks silently becoming strings).
        for record in EXPECTED:
            with self.subTest(record=record):
                self.assertEqual(json.loads(json.dumps(record)), record)

    def test_writer_output_reparses_to_the_same_records(self):
        buf = io.BytesIO()
        FastExportWriter(buf).write(EXPECTED)
        buf.seek(0)
        reparsed = list(FastExportReader(buf).records())
        self.assertEqual(reparsed, EXPECTED)

    def test_full_round_trip_through_json_and_back(self):
        # bytes -> records -> jsonl text -> records -> bytes -> records
        reader = FastExportReader(io.BytesIO(SAMPLE_STREAM))
        records = list(reader.records())

        jsonl = "\n".join(json.dumps(r) for r in records)
        reloaded = [json.loads(line) for line in jsonl.splitlines()]

        buf = io.BytesIO()
        FastExportWriter(buf).write(reloaded)
        buf.seek(0)
        final = list(FastExportReader(buf).records())

        self.assertEqual(final, EXPECTED)

    def test_reset_without_from(self):
        stream = io.BytesIO(b"reset refs/heads/orphan\ndone\n")
        records = list(FastExportReader(stream).records())
        self.assertEqual(
            records,
            [{"type": "reset", "ref": "refs/heads/orphan"}, {"type": "done"}],
        )

    def test_large_payload_written_as_delimited_block(self):
        big_line = b"x" * 79 + b"\n"
        payload = big_line * (_DELIMITED_THRESHOLD // len(big_line) + 1)
        self.assertGreaterEqual(len(payload), _DELIMITED_THRESHOLD)
        record = {
            "type": "blob",
            "mark": ":9",
            "encoding": "utf-8",
            "data": payload.decode("ascii"),
        }

        buf = io.BytesIO()
        FastExportWriter(buf).write_record(record)
        written = buf.getvalue()
        self.assertIn(b"data <<END_", written)

        buf.seek(0)
        self.assertEqual(list(FastExportReader(buf).records()), [record])

    def test_large_payload_without_trailing_newline_stays_exact_length(self):
        # Our delimited reader can't tell "payload ended right before the
        # delimiter line" apart from "the last line happened to be blank",
        # so a payload not ending in "\n" must fall back to the exact-length
        # form even past the size threshold.
        payload = b"x" * (_DELIMITED_THRESHOLD + 1)
        record = {
            "type": "blob",
            "mark": ":9",
            "encoding": "utf-8",
            "data": payload.decode("ascii"),
        }

        buf = io.BytesIO()
        FastExportWriter(buf).write_record(record)
        written = buf.getvalue()
        self.assertTrue(written.startswith(b"blob\nmark :9\ndata " + str(len(payload)).encode("ascii") + b"\n"))

        buf.seek(0)
        self.assertEqual(list(FastExportReader(buf).records()), [record])

    def test_tag_without_tagger(self):
        stream = io.BytesIO(
            b"tag v0.1\nfrom :1\n" + _data(b"early release\n")
        )
        records = list(FastExportReader(stream).records())
        self.assertEqual(
            records,
            [
                {
                    "type": "tag",
                    "name": "v0.1",
                    "from": ":1",
                    "message": "early release\n",
                    "message_encoding": "utf-8",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
