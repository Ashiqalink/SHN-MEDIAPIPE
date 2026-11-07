# MVP lint rules

Run `python -m core <project> --lint` or call `lint_project(load_project(folder))`.
The report follows the [model contract](model-contract.md): schema identity,
`reportVersion: 1`, disabled rules, sorted portable diagnostics and separate
`errors`, `warnings`, `hints`, `infos` and `unknowns` counts. Unknown outcomes
increment only `unknowns`. Loading and linting are read-only.

| Rule | Triggering example | Passing example | Unknown |
|---|---|---|---|
| L-1: unknown material, error | A material reference is `"missing"` with no such declared ID. | `"sand"` resolves to a declared material. | Never. |
| L-3: palette index, error | A palette with five colors is indexed at 5. | Index 4 in that palette. | Never; invalid/unresolved prerequisites are skipped. |
| L-5: orphan material, warning | `stone` is referenced only by a region, with no reaction or spawn use. | A spawn rule spawns `stone`, or a reaction consumes/produces it. | An otherwise orphan material is declared externally used by code. |
| L-14: type mismatch, error | Material density is `"heavy"` or `true` instead of a number. | Density is the JSON number `2.7`. | Never. |

All field names come from schema annotations and category roles; no conventional
game field names are assumed. L-1 visits annotated material references throughout
all categories. Duplicate IDs remain structural errors; an ambiguous reference
is not mislabeled as an unknown ID. L-3 follows the annotated entity-relative
`paletteField` and the palette's mapped `colors` role. Its `details.index` is an
exact decimal string so very large valid integers remain reportable.

L-5 counts annotated material references in reaction and spawn-rule entities.
It uses the material category's `external` default, overridden by an item boolean
annotated `externalMarker: "external"`. An external orphan emits
`material.external_usage`, `outcome: "unknown"`, warning severity and
`details: {"reason": "external"}`. It never becomes a pass or ordinary warning.
An item override of false restores an orphan warning.

Schema `rules` and `.pixorra/project.json` `disabledRules` form a numerically
sorted union in the report header. Disabled rules emit no lint outcomes.
Structural validation remains active, including L-14 type checks, so disabling
L-14 cannot authorize invalid saves. Other schema constraints (required fields,
ranges, enums, undeclared fields) remain infrastructure diagnostics rather than
duplicate L-14 reports. The CLI also returns failure for structural errors.

[Golden reports](../spec/fixtures/lint/mvp.json) freeze exact messages, spans,
entity focus data, related locations, schema hashes and unknown/count behavior.
The clean falling-sand sample has zero lint outcomes for these four rules.
The remaining ten rules and expression analysis belong to phase 4.
