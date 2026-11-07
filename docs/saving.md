# Headless save API

`SaveSession` implements the [verified-save contract](save-contract.md). No
server, UI or game runtime is required. Construct one session per opened project.
Treat loaded snapshots as read-only and edit copies of their ordered JSON values.
Numbers must be `int` or finite `Decimal`; binary floats are refused. Authored
values must fit the strict parser's numeric and nesting limits after serialization.

```python
from copy import deepcopy
from decimal import Decimal
from core import SaveSession, load_project

session = SaveSession(load_project("examples/falling-sand"))
path = "data/world.json"
model = deepcopy(session.project.documents[path].root.value)
model["materials"][0]["density"] = Decimal("1.75")
plan = session.prepare({path: model})
preview = plan.preview()  # Display this to the author; preparation writes nothing.
```

After the author explicitly approves `preview["token"]`, commit that exact plan:

```python
result = session.commit(plan, acknowledge_preview=plan.token)
```

An unapproved required preview raises `SaveError` with code
`save.preview_required` and `details["preview"]`. The first mutating save,
multiple `(file, top-level key)` pairs and every override require approval.
Later one-key saves can call `commit(plan)` directly. No-op plans return
`unchanged` without writes, mtime changes, sidecars or satisfying the first-save
gate. A new preparation supersedes older plans and approvals; reload and
successful commits invalidate them too. Preview data includes the session
revision, schema hash, source/candidate hashes, unified diffs, explicit BOM,
line-ending/final-newline metadata and the proposed history diff.

Models cover complete bound file roots. Supply only the files being edited;
the whole candidate project is structurally validated before writing any file.
Dict insertion order is authored key order. Entity deletion edits its containing
array; file deletion is unsupported. Missing bound files can be created by
supplying a complete valid model. Existing invalid JSON can be replaced only by
supplying a complete structurally valid root. New files use UTF-8 without BOM,
two spaces, LF and one final newline.

`edit_document(document, model)` exposes the same verified byte patcher without
filesystem mutation. Same-shape edits descend to changed tokens. Structural
insertion/deletion replaces the smallest owning container while copying
unchanged children and existing key tokens verbatim. It preserves untouched
byte intervals through offset shifts, original trailing whitespace, and local
indentation/newlines. New numeric tokens use exact plain decimal spelling;
unchanged exponents, negative zero and escape spellings remain untouched.

## Conflicts and acknowledgment

Catch `SaveError` and inspect its `code` and structured `details`. A disk conflict
includes `path`, `observedHash` (null for absence), `currentBytes`, and a fresh
disk-to-candidate diff. Hashes cover exact bytes, including BOM and whitespace.

- Reload with `session.reload()` to adopt disk content and discard the session's
  baseline/plans. Reconcile caller-owned edits explicitly and prepare again.
- After the author explicitly chooses override, call
  `session.prepare(models, override_hashes={path: observed_hash})`. This preserves
  the local candidate and generates a mandatory fresh preview against that exact
  disk revision. Approve its new token. Any later external edit blocks again.
- Schema/history warnings require `prepare(models, acknowledge_schema=True)`
  after explicit acknowledgment. This includes corrupt-history reset. A changed
  schema or project config requires reload; preview approval cannot bypass it.

Missing material IDs remain L-1 semantic errors and can be saved. Type errors,
undeclared fields and other structural errors block saves even when their lint
rule is disabled. Lint warnings and unknowns do not block saving.

## Results and failure boundaries

Preflight failures raise `SaveError` before any content commit. Failures during
the commit loop return `SaveResult(status, files, diagnostics)`. Each file has a
status and successful members include their committed hash. Remaining files have
`not_saved`; caller-owned models retain uncommitted edits. Always inspect both
per-file results and diagnostics.

Temporary files are created beside their destinations, flushed, fsynced,
verified, then replaced with `os.replace`. Destination and schema hashes are
rechecked immediately before replacement. There is no truncate/delete fallback.
Ordinary permission bits are preserved where supported. Symlink/junction save
paths are refused. Failures remove only the service's own temporary file.

A post-replace directory-sync failure yields `saved_durability_unknown`, updates
the baseline and never claims rollback. Python's Windows API has no supported
directory-fsync operation; it is skipped there. Each file is atomic independently;
a batch can return `partial`. Successful batch members update history even if a
later file fails. `save.history_failed` means content was saved but metadata was
not durably recorded; it does not undo content commits.

Only committed bytes become the new baseline. Editing a caller-owned model after
preparation leaves those edits outside the frozen plan; prepare it again to save
them. A process-wide lock serializes Pixorra saves. Portable filesystem APIs still
allow a noncooperating external writer to race between the final hash check and
replacement; no whole-batch transaction or OS-wide compare-and-swap is claimed.
