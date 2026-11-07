# Verified save contract v1

This is the required phase 2 save service behavior and phase 3 UI integration.
All hashes are SHA-256 of exact bytes, including BOM, line endings, and trailing
whitespace. A timestamp/size comparison is never a substitute for a content hash.

## Prepare and verify

1. Capture an immutable save plan from the current document/model revision,
   schema identity/version/hash, original disk hashes, dirty nodes, and any
   acknowledged schema mismatch. Serialize saves in one Pixorra process per path.
2. If the ordered model equals the loaded original, return `unchanged` without
   opening a write handle, creating a temporary file, changing mtime, or updating
   history. The editor may independently display an external-change notification.
3. Build nonoverlapping byte replacement ranges. Copy every untouched byte from
   the original. New scalar tokens use valid JSON and exact decimal serialization;
   never route through binary float. Newly authored numbers use plain base-10
   notation, no exponent, strip fractional trailing zeros, and spell zero `0`.
   New strings use literal UTF-8 except JSON-required escapes; use short control
   escapes where defined, otherwise lowercase `\u00xx`. Do not escape `/`.
   Changed containers use the detected local indentation/newline style while
   retaining unchanged child tokens verbatim. For new files use two spaces, LF,
   UTF-8 without BOM, and one final newline.
4. Style detection prefers the changed container's first existing line break
   and indentation delta. Otherwise use the first nonempty nested container's
   style in source order; default to two spaces and LF. A single-line container
   stays single-line for scalar replacement; insertion may expand only that
   container. Mixed-style untouched ranges remain byte-identical. Preserve the
   file's original trailing-newline presence and spelling.
5. Reparse the entire candidate strictly. Verify exact semantic equality to the
   planned model, ordered object entries/arrays, and schema validity. Errors
   block saving (`save.invalid_content`). Semantic lint warnings/unknowns do not
   block by default; do not silently convert them into parser/type errors.
6. Verify untouched byte intervals using an original-to-output offset map. For
   sorted patches `[s_i,e_i) -> b_i`, offset shifts are the cumulative difference
   `len(b_i) - (e_i-s_i)`. Compare every complementary original interval with its
   mapped candidate interval, not at its old absolute offsets. Also compare raw
   tokens for every unchanged node inside a replaced container. Verify that the
   patch ownership is the smallest required token/container and that there are
   no unplanned reorderings. A failed check aborts with
   `save.verification_failed`; original disk bytes remain untouched.
7. Generate a unified diff over exact original/candidate text, with explicit BOM,
   CRLF and missing-final-newline metadata so the preview cannot hide byte changes.
   The preview includes the plan/model revision, schema hash, source hashes, and
   candidate hashes. No disk mutation occurs during preparation or preview.

Syntax errors, undeclared fields, invalid references required for serialization,
schema/type errors, invalid schema, and unacknowledged schema changes block
saving. A missing material reference is a semantic L-1 diagnostic and can be
saved as authored if all structural checks pass; schema validation must not
pretend that reference resolution is a JSON type assertion.

## Required diff previews

Show and require acknowledgment of a preview before the first **mutating** save
in an opened-project session, and whenever a save plan touches more than one
top-level key. Optional autosave is off by default and must pause at these gates.
No-op saves neither trigger nor satisfy the first-save preview. A successful
mutating commit satisfies it; canceled or failed commits do not. Reopening the
project starts a new session.

Count touched keys as `(relative file path, first decoded pointer segment)`
pairs, across the whole save batch. Root-array edits or replacing the whole root
use the special key `""`. Two entities under one `materials` key count as one;
`materials` and `palettes` count as two; same key name in two files counts as two.
Editor metadata does not contribute to this count, but its diff is available.
Creation/deletion of a file counts its root key. Acknowledgment applies to that
exact plan and hashes. Any model/schema/disk change invalidates it. Headless
callers receive `save.preview_required` with the same diff/plan token and must
explicitly acknowledge before committing; being headless is no bypass.

## Conflict and override

Immediately before creating the temp file, re-read the destination (including
existence) and compare its hash with the loaded hash. A missing loaded file, a
newly existing target, or different bytes is `save.conflict`. Do not mutate any
affected file. Offer current disk bytes/diff plus:

- Reload: explicitly discard or reconcile local edits, load the new bytes and
  source spans, rerun validation, prepare a new save plan.
- Explicit override: the user acknowledges replacement of a particular newly
  observed disk hash. It never means ignore all later conflicts. Rebase the
  conflict comparison on that observed hash, preserve the planned local model,
  show a mandatory fresh diff from current disk to candidate, and verify again.
  A second external change blocks again. Never silently merge/reformat bytes
  under stale source spans. The original-source minimal-span guarantee applies
  to ordinary saves; an explicit override may replace externally edited regions
  and must display every such replacement.

Recheck the expected destination hash just before atomic replacement; recheck
the selected schema hash too. Preview/override approval never authorizes a
different candidate or source revision. If edits arrive during a save, commit
the frozen plan and leave subsequent edits dirty; do not clear their dirty state.

## Atomic replacement and failures

Write the verified candidate to a uniquely named temp file in the destination's
directory on the same filesystem. Set ordinary permission bits consistently with
the destination where supported. Write all bytes, flush, fsync the temp handle,
close it, and verify its hash. After the final conflict check, atomically replace
the destination (`os.replace` on the first Python backend). Fsync the parent
directory where supported. Only then update in-memory original bytes/spans/hash
and report `saved`. Failure before replacement removes only Pixorra's own temp
file and leaves the original intact. Failed replace (including a Windows sharing
violation) is `save.replace_failed`; never fall back to delete-then-rename or
truncating the original. A directory-sync failure after replacement reports
`saved_durability_unknown`, refreshes the baseline, and must not claim rollback.

Atomic rename prevents partial file visibility, but standard filesystem APIs do
not provide cross-platform compare-and-swap against noncooperating external
writers. There is a residual race between the final hash check and replacement.
Document this limit; do not claim a hard lock against arbitrary writers. Source
and target symlink escapes are refused; re-resolve paths before commit. Stronger
OS-specific locking is a future capability, not a portable v1 guarantee.

Batch save prepares/verifies all files and checks all initial conflicts before
committing any. Commit in relative-path order; stop at the first failure. Each
file replacement is atomic independently. Return per-file status and committed
hashes, leaving uncommitted files dirty; never roll back by overwriting a file
another process may have changed. Portable atomicity of an entire batch is not
promised. New-file creation must refuse a newly appeared destination at both
checks; the same residual noncooperating-writer race applies. File deletion is
not supported by v1 save; deleting all entities saves an explicit empty array.

## Save history sidecar

`.pixorra/state.json` is a closed object `{stateVersion: 1, files: {...}}`. File
keys are project-relative paths; values are `{contentHash, schemaId,
schemaVersion, schemaHash}` from each successful commit. No timestamps or
absolute paths. Missing history is safe; corrupt history emits
`schema.history_invalid` and requires explicit reset acknowledgment before
replacing it. Do not infer last-save versions from current schema selection.

Save history using the same verified-temp/hash/replace procedure after content
commits, including successful members of a partially completed batch. Metadata
failure reports `save.history_failed` alongside actual per-file commit results;
content already committed remains saved. On reopen, a history contentHash that
differs from current bytes emits `schema.history_stale`; version history is
informational until explicitly acknowledged. Never report history and content
as a single atomic transaction.
