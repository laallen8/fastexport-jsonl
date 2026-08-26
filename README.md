# fastexport-jsonl

`git fast-export` dumps repository history as a stream of custom
commands (`commit`, `blob`, `reset`, `tag`, file changes) with raw
byte payloads whose length is given up front. It's built to be piped
straight into `git fast-import`, which is great for moving history
around, but it's a pain to do anything else with: no `jq`, no `grep
-c` on individual fields, no loading a slice of it into pandas.

This converts that stream into JSON Lines - one JSON object per
command, in the same order they appeared - so ordinary tools that
already speak JSON can be pointed at git history.

## Usage

No install needed, it's plain standard library:

```sh
git fast-export --all | python -m fastexport_jsonl to-jsonl > history.jsonl
```

Each line is one record. A commit looks like:

```json
{"type": "commit", "ref": "refs/heads/main", "mark": ":3", "author": "Jane Doe <jane@example.com> 1700000000 -0500", "committer": "Jane Doe <jane@example.com> 1700000000 -0500", "message": "fix off-by-one in the paginator\n", "message_encoding": "utf-8", "from": ":2", "changes": [{"op": "M", "mode": "100644", "dataref": ":4", "path": "paginator.py"}]}
```

and a blob looks like:

```json
{"type": "blob", "mark": ":4", "encoding": "utf-8", "data": "def paginate(...):\n    ...\n"}
```

Binary blob content that isn't valid UTF-8 comes through as
`{"encoding": "base64", "data": "..."}` instead, so nothing is lost.

From there it's just JSON:

```sh
jq 'select(.type == "commit") | .message' history.jsonl
jq 'select(.type == "commit" and (.merges // []) != [])' history.jsonl | wc -l
```

To go back the other way, feed edited (or untouched) JSON Lines to
`from-jsonl` and pipe the result into `git fast-import`:

```sh
python -m fastexport_jsonl from-jsonl < history.jsonl | git fast-import
```

`FastExportWriter` is the mirror of `FastExportReader`: it takes the
same dicts and writes the fast-import command language back out, one
record at a time.

## Why streaming matters

`git fast-export --all` on a repository with any real history can
produce a multi-gigabyte stream. `FastExportReader` reads it one line
or one length-prefixed data block at a time; it never buffers the
whole input, so `to-jsonl` runs in roughly constant memory regardless
of how large the export is:

```python
import sys
from fastexport_jsonl import FastExportReader

for record in FastExportReader(sys.stdin.buffer).records():
    ...  # handle one record, then let it go
```

## Current scope

Both directions exist now. The parser and writer both cover `blob`,
`commit`, `reset`, and `tag` commands, including file changes
(`M`/`D`/`C`/`R`/`N`/`deleteall`) with C-quoted paths. Anything else
(`feature`, `progress`, `checkpoint`, ...) round-trips verbatim as an
`"other"` record instead of being dropped.

`tests/test_roundtrip.py` covers both directions against a hand-built
fast-export stream (exact-length and delimited `data` blocks, a binary
blob, a merge commit exercising every file-change op, a tag) and
checks that records survive a `json.dumps`/`json.loads` hop unchanged.
It hasn't been run against an actual `git fast-export --all` dump yet.

Not done yet:

- `FastExportWriter` only emits the exact-length `data <n>` form;
  delimited (`data <<EOF`) blocks are parsed on the way in but never
  produced on the way out, so very large payloads are still fully
  materialized as one `bytes` object before being written
- no round-trip test against an actual repository's `fast-export`
  output, only the synthetic fixture above
- no CLI flag to filter records by type

## License

MIT, see `LICENSE`.
