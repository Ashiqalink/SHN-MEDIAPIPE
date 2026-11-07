# Pixorra phases

Status: phases 0, 1 and 2 complete · 2026-11-07

Baseline: [complete PRD](docs/PRD.md). The product name is Pixorra; all other
requirements remain in scope. Work on one requested phase at a time. Tick a phase
only when its exit checks pass.

## 0 — Contracts and decisions [complete]

- Define the schema/version contract, ordered content model with source spans,
  references, diagnostics, and fixture formats before dependent code.
- Resolve JSON Schema vocabulary versus custom format, expression scope for
  `random(p)`, Python/possible future port, and the specified portable RNG.
- Specify evaluation order, numeric behavior, and unknown outcomes. Share
  transition semantics between reachability and simulation (FR-25).
- Define save verification, atomic replacement, hash conflict checks, and
  diff-preview triggers from PRD Section 8.

Exit: contracts, acceptance cases, and decisions are recorded. Pixorra is the
chosen name; registry/trademark checks remain a release task. No check has been
performed yet. The quest sample includes a material-reaction module for L-7;
see [D-10](docs/decisions.md) and the evaluation contract.

## 1 — MVP: schema and project core [complete]

- Establish the standalone layout, Python 3.11+ headless core and shared fixtures.
- Load folders and validate versioned schemas; reject undeclared fields/types.
- Load materials and palettes, index references, and retain original source text.
- Prepare small falling-sand content; keep interfaces suitable for the quest schema.

Covers: FR-1–FR-5 core behavior; L-14 foundation.

Exit: valid content loads without UI/server dependencies; broken schemas, invalid
types, and schema-version mismatches produce the specified diagnostics.

## 2 — MVP: safe writes and four lint checks [complete]

- Implement source-span edits preserving untouched bytes, key order, whitespace,
  trailing newline, and number literals. Reparse and compare before committing.
- Use temp-file writes and atomic replacement; abort failed verification.
- Block saves on disk-hash changes; expose reload/explicit override and diff data.
- Implement L-1, L-3, L-5, L-14, including L-5's external-reference unknown outcome.

Covers: FR-26–FR-29 core behavior and the MVP lint subset.

Exit: every round-trip fixture passes no-op byte equality and one-edit span
checks; verification failure leaves originals intact; conflicts block saves;
the four rules have passing/failing fixtures and applicable unknown cases.

## 3 — MVP: local graph authoring

- Wrap core with local FastAPI. Build React + TypeScript + React Flow with Zustand.
- Add materials/palettes browser, material-reaction graph, pan/zoom/minimap,
  typed ports, CRUD/connections, schema-driven inspector, and resolved pickers.
- Add graph undo/redo, dirty state, explicit save and required diff previews.
- Expose MVP lint on demand/on save; show errors, warnings, hints and unknowns.
  Autosave remains off by default; live lint is optional.

Covers: FR-4, FR-6–FR-12 MVP behavior and save UI for FR-26–FR-29.

Exit: author, wire, save, and reopen a five-material set; verify undo/redo, first
save/multiple-top-level-key previews, conflict handling, and clean minimal diffs.
Measure the under-five-minute authoring target. MVP is independently useful here.

## 4 — M2: expressions and complete lint

- Specify and implement the restricted expression grammar and shared evaluator.
  No arbitrary code or undeclared functions. Specify seeded random semantics.
- Complete L-1–L-14, per-project disable controls, and visible disabled-rule lists.
- Keep unknown results distinct and use shared transition logic for reachability.
- Add docs/expressions.md, the rule catalog with positive/negative examples,
  exact expected reports, and lint-report jump-to-node.

Covers: FR-12–FR-18, all lint rules, and FR-25 shared-core foundation.

Exit: all 14 rules have passing/failing fixtures, applicable unknown fixtures,
and documented examples; planted errors are all caught with zero false positives
on the clean sample; invalid/unsafe expressions are rejected.

## 5 — M2: whole-project and quest authoring

- Complete category browsing and schema-driven editing for spawn rules, regions,
  flags, quests, and optional dialogue; retain materials-only configurations.
- Add quest state-machine view, typed transitions, required flags, rewards, region.
- Ship both reference schemas and demonstrate a third-party schema without code edits.

Covers: remaining FR-4/FR-8 category behavior, FR-19–FR-20.

Exit: both reference projects lint/edit/save/reopen; quest diagnostics focus the
correct nodes; a third-party schema loads and lints unchanged. M2 is complete.

## 6 — M3: headless simulator and batch reports

- Expose shared reaction/quest evaluation from a supplied state, tick-by-tick
  state changes, arbitrary starting states, branching, and seeded scenario files.
- Emit deterministic batch reports suitable for CI. Lint reachability and
  simulation share transition code; unresolved static conditions stay unknown.

Covers: FR-21–FR-25 core behavior.

Exit: shared simulation fixtures match expected ticks and reports; identical seeds
produce identical output on Windows, macOS, and Linux. CI runs the full shared
fixture suite on every commit, with behavior and fixture changes kept together.

## 7 — M3: simulator UI and v1 validation

- Add step-through and branch-from-node/state controls using the existing core.
- Validate real game content, graph performance, local operation, docs, and all
  success metrics. Use lazy loading and rendering virtualization as needed.
- Review non-goals; confirm license, package names, and trademark availability
  before publication. Prepare the independent tool for release.

Covers: FR-22–FR-23 UI and final FR-1–FR-29 acceptance.

Exit: all v1 acceptance checks and S1–S6 have recorded evidence; remaining
limitations are explicit. M3 is complete. Publication is a separate action.

## 8 — Stretch (optional)

- Thin engine adapters in adapters/<engine>/ (FR-30).
- Graphviz DOT/Mermaid reaction graph export (FR-31).
- Playground integration for seeded world previews, without becoming a runtime.

Exit: each requested addition has fixtures and preserves core independence.
Stretch work does not block v1.

## Intended layout

```text
pixorra/
  core/           schema, project, rules, lint, simulator, export; no UI dependency
  server/         local FastAPI wrapper
  web/            React + TypeScript + React Flow + Zustand
  schemas/        example-falling-sand and example-quest
  spec/fixtures/  expressions/, lint/, simulation/, roundtrip/
  docs/           PRD, schema reference, expressions, rule catalog
  examples/       small sample projects
  adapters/       optional engine loaders
```

Phases 0, 1 and 2 are implemented in this workspace directory. The tool remains
standalone and must not depend on surrounding game projects. Phase 3 is next:
local graph authoring with a web API and editor.

## Recorded exit evidence

- Phase 0: [decisions](docs/decisions.md), schema/model/evaluation/save contracts,
  [fixture format](spec/README.md), and [acceptance matrix](spec/fixtures/acceptance.json).
  The quest sample uses material reactions for L-7. Name availability remains unchecked.
- Phase 1: standalone `core/`, schema profile checks, strict source-preserving JSON,
  material/palette/reference indexing, version-history diagnostics, CLI, and five-material
  [sample](examples/falling-sand). Headless suite: 21 tests pass on Windows/Python 3.13.
  Python 3.11+ is the declared target; other interpreters/platforms are not yet verified.

- Phase 2: [save API](docs/saving.md), byte patch verification, atomic replacement,
  exact-plan previews, conflict/reload/override handling, history metadata and
  [MVP lint](docs/lint.md). All four round-trip seeds, eleven exact lint reports,
  seven shared save scenarios and injected I/O/race/partial-batch checks pass.
  Headless suite: 53 tests pass on Windows/Python 3.13. Python 3.11 syntax is
  checked; execution on other runtimes/platforms remains unverified. Per-file
  atomicity is supported; batch atomicity and OS-wide writer exclusion are not.
