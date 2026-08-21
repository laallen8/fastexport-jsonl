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

Only the fast-export -> JSON Lines direction exists so far. The
parser covers `blob`, `commit`, `reset`, and `tag` commands, including
file changes (`M`/`D`/`C`/`R`/`N`/`deleteall`) with C-quoted paths.
Anything else (`feature`, `progress`, `checkpoint`, ...) is preserved
verbatim as an `"other"` record instead of being dropped.

Not done yet:

- converting JSON Lines back into a fast-export stream for `git
  fast-import`
- delimited (`data <<EOF`) data blocks are parsed but not yet
  produced by anything, since nothing writes fast-export output yet

## License

MIT, see `LICENSE`.
