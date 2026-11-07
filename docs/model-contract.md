# Ordered content and diagnostic contract v1

## Lossless documents and edits

`ProjectSnapshot` contains schema identity/version/hash, immutable ordered
documents, the reference index, and diagnostics. Documents are sorted by relative
path using Unicode scalar order. Each `SourceDocument` contains relative path,
original bytes, SHA-256 of those exact bytes, root node, and detected style.

Every `ContentNode` has a session-stable node ID, kind (`object`, `array`,
`string`, `number`, `boolean`, `null`), parent ID, current file JSON pointer,
original span or null for newly inserted nodes, semantic value, and dirty flag.
Object children are ordered entries, not an unordered dictionary. Each entry
retains key token and colon/comma/trivia ranges; arrays retain element separators.
Container spans include delimiters. Scalar spans include the complete token.
The UTF-8 BOM and whitespace before/after the root belong to document trivia.
Number nodes retain literal text and exact decimal value separately. String
nodes retain decoded text and original escape spelling separately.

Spans are half-open UTF-8 **byte** offsets `[start, end)` into original bytes,
including BOM bytes in offsets. An edit range replaces bytes from start through
end minus one. Locations also expose 1-based line and Unicode-scalar column;
CRLF is one newline, tabs count as one column. Pointers escape `~` as `~0`, `/`
as `~1`. Root pointer is `""`. API numeric byte offsets must be nonnegative exact
integers. A frontend must never substitute UTF-16 indices for these offsets.

Scalar replacement touches only its token; container insert/delete/reorder touches
the smallest enclosing container needed to own its punctuation. Unchanged child
tokens inside a changed container are copied verbatim. Structural whitespace may
change only within that container. Do not format neighboring entities. A rename
updates just the ID token unless the user explicitly chooses to update references;
those updates are independent edits and participate in previews and undo.

No-op detection compares ordered structure and exact semantic scalars. Numerically
equal replacement (`1e0` to model value `1.0`) creates no edit and retains `1e0`.
Explicit lexical reformatting is outside v1. Object order is not JSON semantic
equality, but intentional order edits are still real authoring changes and are
verified separately. Undo back to the original model clears dirty state.

Node IDs live only in editor state and remain stable through moves/ID edits in a
session. They are not persisted into game JSON. Reports use a portable focus
target `{path, pointer, entity: {kind, id}|null}`; the UI maps this to current
session IDs. Reload invalidates old node IDs and recomputes pointers/locations.

## References

`ReferenceTarget` is `(kind, exact ID)` plus file pointer and node ID. IDs are
case-sensitive Unicode scalar strings without normalization. Duplicate IDs across
the same kind are `content.duplicate_id` errors and make lookup ambiguous.
Cross-kind identical IDs are valid. Quest stage references include the owning
quest ID. Palette indices are zero based. Negative or fractional indices fail
field constraints before L-3; missing/ambiguous palettes do not invent lengths.

`ReferenceUse` records source location, target kind, raw value, and resolution:
`resolved`, `missing`, or `ambiguous`. Unknown material IDs always trigger L-1
even if the material category allows external use; `external` describes known
materials referenced from game code, not permission for misspelled IDs. L-2
adds a warning for edit distance <= 2 using ordinary Levenshtein distance on
Unicode scalar values (no transpositions); suggestions sort by distance, then ID.
Dependent checks skip invalid inputs rather than issuing speculative cascades.

Index all categories before resolving uses; file enumeration and object-map
iteration order must not affect resolution. Retain all uses for incoming-edge
navigation and schema-driven picker choices.

## Diagnostics and lint reports

Every diagnostic is a closed object with these fields:

| Field | Meaning |
|---|---|
| `rule` | L-1–L-14 or null for infrastructure/schema diagnostics. |
| `code` | Stable machine code, e.g. `reference.material_missing`. |
| `severity` | `error`, `warning`, `hint`, or `info`. Unknown keeps the rule's declared severity. |
| `outcome` | `fail` or `unknown`. Passes produce no diagnostic. |
| `message` | Stable English fixture text with no absolute paths. |
| `location` | `{path, pointer, span}`; span is `{start, end}` or null if no source exists. |
| `entity` | `{kind, id}` or null, used for graph focus. |
| `related` | Ordered array of other locations, possibly empty. |
| `details` | Structured object; rule-specific keys only, never exceptions or timestamps. |

Sort by path, pointer, numeric rule ID (null sorts first), code, then message,
all string comparisons by Unicode scalar order. Related locations sort by path,
pointer. Deduplicate only identical rule/code/location/outcome/details, not just
messages. Cycles emit one diagnostic per strongly connected component, located
at the lexically first reaction ID, with sorted reaction IDs in details.

A lint report is `{reportVersion: 1, schema: {id, version, hash}, disabledRules,
counts, diagnostics}`. Hash is lowercase SHA-256 hex. `disabledRules` is the
sorted numeric union of schema-disabled and project-disabled IDs. Disabled rules
emit no outcomes, but structural validation cannot be disabled. `counts` has
`errors`, `warnings`, `hints`, `infos`, and `unknowns`; fail outcomes increment
their severity counter, unknown outcomes increment only `unknowns`. An unknown
warning must not also increment warnings. CLI policy is separate from these
counts and must not recast unknown as pass/fail.

L-14 covers incorrect JSON types (`type.mismatch`). Other schema constraints use
infrastructure codes such as `content.undeclared_field`, `content.required`, or
`content.range`, avoiding duplicate type diagnostics from two validators.
L-8 parse/type errors are failures; unavailable runtime values are unknowns in
dependent rules, not syntax errors. Rule checks requiring invalid fields are
skipped with the prerequisite error retained. Unknowns require a specific reason
in details: `external`, `spawn_external`, `external_writes`,
`external_transitions`, `generated_sprite`, `runtime_value`, `probabilistic`, or
`analysis_limit`.

The full 14-rule catalog arrives in phase 4. Phase 2's
[MVP golden reports](../spec/fixtures/lint/mvp.json) freeze the four implemented
rules, including the L-5 external-unknown envelope and count behavior. Later
fixture additions may add codes, but may not silently change this envelope.
