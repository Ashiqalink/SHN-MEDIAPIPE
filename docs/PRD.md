# Pixorra — Product Requirements Document

Status: Draft v2.0 · Date: 2026-11-07

Working name: Pixorra (chosen by the user; check trademark and package-name
collisions before publishing).
Repository: standalone, open source, separate from any game project.
License: MIT (proposed).

The supplied VoxelForge PRD is retained below with the name changed to Pixorra.
Markdown formatting is normalized; product scope and requirements are unchanged.

## 1. Summary

Pixorra is a free, local, open-source authoring and linting tool for the JSON
content that drives voxel-and-pixel games: materials, reactions, spawn rules,
world regions, and the flags and quests that connect them to gameplay.

It authors content as visual node graphs, reads and writes the game's own JSON
without a proprietary project format, and validates it with a static lint engine
that understands voxel and pixel concepts: material IDs, palette indices, chunk
bounds, reaction cycles, and sprite references.

It is schema-driven. Every node type, field, enum, and validation rule comes from
a versioned schema file. The tool knows nothing about any specific game. Each
game ships a schema describing its own JSON, and Pixorra enforces it.

One line: "A node editor and linter for voxel-pixel game JSON, where a typo in a
material ID is an error before the game ever runs."

## 2. Problem Statement

Voxel-pixel games accumulate interlocking material definitions, reaction tables,
spawn tables, region rules, and quest flags. Hand-editing causes:

1. Silent reference breakage: misspelled IDs or out-of-range palette indices fail
   quietly at runtime, often far from the cause.
2. Unreadable interaction webs: orphaned reactions, unreachable materials, and
   cycles are invisible in raw JSON.
3. Slow iteration: checking a reaction requires launching the game and finding
   the case. Playgrounds help only after content is valid.
4. Single-author bottlenecks: only someone who knows the schema can edit safely.

## 3. Target Users

| User | Need |
|---|---|
| Indie voxel/pixel sandbox developers | Author and validate material, reaction, and quest content without hand-editing JSON |
| Researchers and playground users | Generate, inspect, and diff variants reproducibly |
| Designers and non-programmers on small teams | Edit reactions and story branches through graphs |
| Engine-agnostic tool builders | Reuse a schema-driven editor and linter across formats |

Primary launch user: the author's own voxel-pixel project, validating real content
before it ships.

## 4. Goals and Non-Goals

- G1: Read, visualize, edit, and write game JSON without changing the runtime.
- G2: Catch broken references and invalid values before the game runs.
- G3: Make material-reaction graphs and quest flow readable at a glance.
- G4: Support a new game by writing a schema, without tool code changes.
- G5: Stay free and local: no accounts, cloud, or paid services.
- G6: Keep simulation rule evaluation deterministic, testable, and headless.

Non-goals for v1: a game engine, renderer, or simulation runtime; voxel modeling
or pixel art editing; multi-user collaboration servers; localization pipelines;
conversion to dialogue languages such as Ink or Yarn. Sprites/models are referenced,
and the game retains its own runtime logic.

## 5. Content Scope

| Category | Examples | Graph role |
|---|---|---|
| Materials | ID, density, hardness, flammability, palette index, sprite reference | Nodes |
| Reactions | Inputs, outputs, trigger conditions, probability | Edges between materials |
| Spawn rules | Material, region, depth range, seed weight | Nodes linked to regions |
| Regions/biomes | Bounds, allowed materials, ambient parameters | Nodes |
| Palettes | Ordered colors, maximum size, shared material references | Reference targets |
| Flags and quests | Flag names, quest stages, rewards | State-machine nodes and edges |
| Dialogue | Lines, choices, conditions | Optional nodes and edges |

Schemas declare enabled categories and their relationships. Modules are optional:
falling-sand games can omit quests; story games can use materials as reference data.

## 6. Architecture

```text
Frontend   React + TypeScript + React Flow (graph UI)
           Zustand (editor state)
Backend    Python 3.11+ / FastAPI (local server)
           schema engine    loads/validates <game>.schema.json
           project service  hash-aware, round-trip-safe JSON reads/writes
           rule engine      expression grammar and reference resolution
           lint engine      structural and semantic checks
           simulator core   deterministic reaction and flag evaluation
           export engine    minimal-diff writes
Shared     /spec/fixtures/  executable cases used by every backend
Storage    The game's own JSON on disk
Adapters   /adapters/<engine>/ optional thin non-standard-JSON loaders
```

Standalone repository:

```text
pixorra/
  core/          schema, project, lint, simulator, export (no UI dependencies)
  server/        FastAPI wrapper around core
  web/           React editor
  schemas/       example-falling-sand, example-quest
  spec/fixtures/ executable behavior tests shared across implementations
  docs/          schema reference, expression grammar, rule catalog
  examples/      small sample projects
```

Key invariants:

- Schema is the law: undeclared nodes, fields, and references are refused.
- Round-trip safety: never rewrite a file that has not changed; see Section 8.
- Core has no UI dependency: everything in core/ runs from a script or CI.
- Determinism: identical content and seed produce identical output on any platform.

## 7. Functional Requirements

### 7.1 Project and Schema

- FR-1: Open a project folder containing game JSON files.
- FR-2: Load schemas declaring categories, node types, field types, enums,
  palette limits, and rule definitions.
- FR-3: Validate schemas on load; report broken schemas rather than accepting them.
- FR-4: Browse materials, reaction sets, regions, palettes, and quests.
- FR-5: Version schemas, record the version last saved with, and warn on mismatch.

### 7.2 Graph Editor

- FR-6: Render material-reaction graphs and quest state machines with pan, zoom,
  and minimap.
- FR-7: Create, edit, delete, and connect nodes using schema-defined typed ports.
- FR-8: Inspect/edit every declared field using type-aware inputs, including
  palette/material pickers, enum dropdowns, and numeric ranges.
- FR-9: Resolve material and palette IDs from the project so authors choose values.
- FR-10: Undo and redo per graph.
- FR-11: Explicit save with dirty-state indication; optional autosave defaults off.

### 7.3 Lint Engine

Each rule defines input, firing condition, and an explicit unknown outcome when
static analysis cannot decide.

| ID | Class | Severity | Input | Fires when | Unknown when |
|---|---|---|---|---|---|
| L-1 | Unknown material reference | error | Any material_ref field | Value is not a declared material ID | Never |
| L-2 | Near-miss material reference | warning | Same as L-1 | Unknown ID is within edit distance 2 of a declared ID | Never |
| L-3 | Palette index out of range | error | Material color index | Index ≥ palette length | Never |
| L-4 | Palette overflow | error | Palette definition | Entry count exceeds schema max_size | Never |
| L-5 | Orphan material | warning | Materials, reactions, spawn rules | Material is never produced, spawned, or used in a reaction | Referenced by code, declared external: true in schema |
| L-6 | Unreachable material | warning | Spawn rules, reactions, region bounds | No spawn rule or reaction chain produces it from declared starting materials | Spawn logic lives in game code: spawn_external |
| L-7 | Reaction cycle | warning | Reaction graph | Cycle exists without a declared exit condition | A cycle condition cannot be evaluated statically |
| L-8 | Invalid expression | error | Any expression field | Fails to parse under the schema grammar | Never |
| L-9 | Unknown flag reference | error | Expressions and flag fields | Flag is not declared in the flags file | Never |
| L-10 | Unused flag | hint | Flags file and expressions | Flag is never read or written | Written by game code: external_writes |
| L-11 | Dead-end quest stage | error | Quest state machine | Nonterminal stage has no outgoing transition | Advanced by code: external_transitions |
| L-12 | Missing sprite | warning | Material and sprite fields | Sprite path does not resolve in project | Generated at build time |
| L-13 | Region bounds conflict | warning | Region definitions | Overlapping regions both claim exclusive ownership | Never |
| L-14 | Type mismatch | error | Any field | Value does not match schema type | Never |

- FR-12: Lint on demand, on save, and optionally live; count errors, warnings,
  hints, and unknowns separately.
- FR-13: Clicking a report item focuses its offending node.
- FR-14: Allow per-project rule disabling; list disabled rules in the report header.
- FR-15: Document every rule with triggering and non-triggering examples in docs/.

### 7.4 Expression Grammar

- FR-16: Conditions use a small declared grammar documented in docs/expressions.md
  and covered by spec/fixtures/.
- FR-17: Support comparisons, boolean operators, numeric literals, flag reads,
  material property reads such as `temperature > 300` and
  `neighbor.material == "water"`, and seed-controlled `random(p)`.
- FR-18: Exclude arbitrary code execution and functions outside the declared set.

### 7.5 Quest and State Composer

- FR-19: Display quest stages as state machines with typed transitions.
- FR-20: Attach required flags, rewards, and region to each quest.

### 7.6 Simulator (Headless Evaluation)

- FR-21: Evaluate reaction sets or quest graphs against given state without a renderer.
- FR-22: Step reaction chains tick by tick and show each state change.
- FR-23: Start from any node or state and branch from there.
- FR-24: Run seeded scenario files in batches and emit deterministic reports for CI
  and regression checking.
- FR-25: Use the same simulator code path for lint reachability so the two agree.

### 7.7 Round-Trip Export

- FR-26: Preserve original key order, indentation, and number formatting for
  unchanged values.
- FR-27: Produce minimal diffs; editing one material writes only its block.
- FR-28: Preview JSON diffs before the first session save and whenever more than
  one top-level key is touched.
- FR-29: Block saving externally changed files until reload or explicit override.

### 7.8 Adapters and Export (Stretch)

- FR-30: Optional adapters in adapters/ translate non-standard JSON into the
  canonical internal model.
- FR-31: Export reaction graphs as Graphviz DOT or Mermaid files.

## 8. Round-Trip Definition

1. Parse preserving key order, whitespace style (indent width, trailing newline),
   and literal number text.
2. Model content as an ordered tree with source spans for every node.
3. Edit only changed nodes; unchanged nodes retain original source text.
4. Serialize changed nodes using detected indentation; copy unchanged nodes verbatim.
5. Reparse output, verify semantic equality with the model, and verify that all
   unchanged source spans are byte-identical.

Abort and report failed verification. Never leave partially written user files:
write to a temporary file and atomically rename it.

Acceptance: load every spec/fixtures/roundtrip/ file and verify byte-identical
no-op saves. Make one edit per fixture and verify only the intended span changes.

## 9. Behavior Spec and Shared Fixtures

Every rule-engine/simulator implementation, including future ports, passes the
same fixtures:

- spec/fixtures/expressions/: parse/evaluate cases and expected results.
- spec/fixtures/lint/: content plus exact expected lint reports.
- spec/fixtures/simulation/: seeded scenarios and expected tick-by-tick state.
- spec/fixtures/roundtrip/: Section 8 acceptance files.

CI runs the full suite on every commit. Rule-behavior changes update fixtures in
the same commit to make behavior changes visible in review.

## 10. Example Schemas

- example-falling-sand: materials, palettes, reactions, spawn rules, regions;
  covers L-1–L-6 and L-12–L-14.
- example-quest: flags and quest state machines with dialogue; covers L-7–L-11.

A third game-specific schema can live in the game's own repository. Pixorra
does not depend on it. Success means loading and linting new schemas without
tool code changes.

## 11. Success Metrics

| ID | Metric | Target |
|---|---|---|
| S1 | No-op round-trip fixtures remain byte-identical | 100% |
| S2 | Lint rules with passing and failing fixtures | 14 of 14 |
| S3 | Planted-error detection in sample project | 100%; zero false positives on clean sample |
| S4 | Third-party schema loads/lints without code changes | Works |
| S5 | Same seeded batch on Windows, macOS, Linux | Identical reports |
| S6 | Create and wire a five-material reaction set in UI | Under 5 minutes |

## 12. Milestones

MVP — "Lint my materials":

- Schema loading/validation (FR-1–FR-3).
- Materials/palettes project browser (FR-4).
- Material-reaction graph viewing/editing (FR-6–FR-11).
- Minimal-diff round-trip export (FR-26–FR-29).
- L-1, L-3, L-5, L-14 and shared fixtures for those rules and round trips.

M2 — "Lint the whole project":

- All lint rules with fixtures (FR-12–FR-15).
- Expression grammar/parser (FR-16–FR-18).
- Quest state-machine view (FR-19–FR-20).
- Jump-to-node from reports (FR-13).

M3 — "Simulate before the game":

- Headless simulator/batch runner (FR-21–FR-25).
- UI step-through and branch-from-node (FR-22–FR-23).
- Deterministic CI reports (FR-24).

Stretch: adapters (FR-30), DOT/Mermaid export (FR-31), and playground integration
for seeded world previews.

## 13. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Round-trip corruption | Lost work and trust | Source spans, byte-identical no-op tests, atomic writes, diff gate |
| Python/second implementation drift | Lint/simulator disagreement | Shared CI fixtures and shared lint/simulator code path |
| Grammar grows into scripting | Unsafe, unmaintainable system | Documented grammar/exclusions; review new functions |
| Lint false positives | Authors disable lint | Explicit unknowns, visible per-rule disable, fixture-tested precision |
| Slow large graphs | Sluggish editing | Virtualized rendering, lazy loading per reaction set |
| Schema/game drift | Silent breakage | Version schemas in game repositories; game CI runs lint |
| Name/trademark collision | Late rename cost | Check registries/trademarks before first release |
| Scope expands into engine/editor | Never ships | Useful independent milestones; review non-goals at each milestone |

## 14. Decisions

- Name: Pixorra, chosen by the user. Availability checks remain before release.
- Expression scope: decide whether `random(p)` is allowed in lint-checked reactions
  or only in simulation; FR-17's support remains required.
- Schema format: JSON Schema extended with a Pixorra vocabulary versus custom
  format. Recommendation: JSON Schema base for existing editor/CI tooling.
- Core language: Python is proposed. Decide later whether engine use needs a
  port or WebAssembly compilation.
- Determinism source: choose and specify an RNG, such as PCG or xoshiro, so every
  implementation matches.
