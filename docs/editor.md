# Pixorra editor (phase 3)

The local graph editor is a thin UI over the core. It never re-implements
loading, saving, validation, or lint; it drives the same public Python APIs
the CLI uses.

## Parts

- `server/` — local FastAPI wrapper (`python -m server <folder>` on port 8799).
  Endpoints: `POST /api/open`, `GET /api/project`, `GET /api/schema`,
  `POST /api/prepare`, `POST /api/commit`, `POST /api/reload`, `POST /api/lint`.
- `web/` — React + TypeScript + React Flow + Zustand editor (`npm run dev`,
  port 5173, `/api` proxied to the server; `npm run build` type-checks and
  bundles to `web/dist/`).

## Behavior implemented here (per plan phase 3)

- Materials/palettes browser; material-reaction graph with pan, zoom,
  minimap, and fit view (React Flow).
- Typed ports: `material --input--> reaction --output--> material`. Drawing a
  connection updates the reaction's `inputs`/`outputs`; duplicate and
  self-links are refused by the graph logic; schema-invalid wiring is caught
  by the save candidate validation (`save.invalid_content`).
- Schema-driven inspector: material fields from `x-pixorra` annotations with
  resolved palette/references pickers; `paletteIndex` renders colors of the
  material's linked palette (resolved picker), spacer indirect number fields
  keep integers/decimals that survive round trips.
- CRUD: add/delete materials and reactions (browser list and graph buttons).
- Undo/redo over the working model with dirty state (client-side, whole-model
  snapshots, capped at 25 entries).
- Explicit saves only; autosave is not implemented (off by default per FR-12).
  Save prepares a plan through the core's SaveSession; when the plan requires
  a preview (first save, multiple top-level keys, override), a modal shows the
  unified diffs plus lint-at-save and requires explicit approval. Schema
  or history sidecar resets trigger the acknowledgment retry once, then show
  the error.
- Lint runs on demand (Lint button) and is displayed at save; the panel shows
  counts for errors/warnings/hints/infos/unknowns separately, lists disabled
  rules explicitly, and clicking a diagnostic focuses the related node.
- External edits (disk hash changes) block commit with `save.conflict`;
  "Reload disk" refreshes the baseline and clears prepared plans.

## Known limits

- The editor edits the five reference content categories of the sample only;
  quest/optional categories are inspector placeholders (phase 5).
- Reaction `condition` stays a free-form string until expressions land
  (phase 4).
- Palette authoring beyond the graph, spawn-rule editor, and region editor
  remain browser-only in this phase.
- Undo/redo and node positions are client-side only and never sent to the
  server except as part of the model state that reaches `prepare`.
