# Schema and project contract v1

## Versions and discovery

Three versions are independent:

| Name | Representation | Compatibility |
|---|---|---|
| Contract | `x-pixorra.contractVersion`, initially `1.0.0` | v1 initially supports exactly `1.0.0`; reject other versions as `schema.contract_unsupported`. Expand an explicit supported list only with fixtures. |
| Game schema | `x-pixorra.schemaVersion`, canonical `MAJOR.MINOR.PATCH` | Author-assigned, no prerelease/build suffix in v1. Any difference from last-save metadata emits `schema.version_mismatch`; no automatic migration. |
| Fixture | `fixtureVersion`, initially `1` | Reject unsupported versions; a new fixture shape requires a new version. |

Open a folder with an explicitly selected local schema path, or default to
`project.schema.json` at its root. Never guess among multiple schemas. `$id` is
a stable URI identity, not a fetch instruction; schema content also has a SHA-256
hash. Same ID/version with a changed hash emits `schema.content_changed`.

Missing metadata emits informational `schema.history_missing`, not a mismatch.
A mismatch allows inspection and linting, but edits/save require an explicit
acknowledgment of the selected schema identity/version/hash. No acknowledgment
changes game data. Record the acknowledged version only after a successful save.

Optional `.pixorra/project.json` is a closed object with `configVersion: 1`,
`schemaPath` (relative path), and `disabledRules` (unique L-1–L-14 IDs). Missing
configuration means default schema discovery and no disabled rules. Unknown
fields/IDs or versions are errors. Explicit schema selection overrides schemaPath
for this session; do not silently rewrite configuration. No proprietary game
project format is introduced.

## Standard JSON Schema profile

The root has `$schema: "https://json-schema.org/draft/2020-12/schema"`, `$id`,
`type: "object"`, `properties`, `required`, `additionalProperties: false`, and
root `x-pixorra`. Each root property is an enabled category array. Omitted
categories have no implicit behavior or built-in game fields.

Supported keywords: `$schema`, `$id`, `$defs`, local `$ref`, `$comment`, `title`,
`description`, `default`, `examples`, `type`, `properties`, `required`,
`additionalProperties`, `items`, `minItems`, `maxItems`, `uniqueItems`, `enum`,
`const`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `minLength`,
`maxLength`, and `x-pixorra`. Types are single JSON types, not unions. Only root
`$id`/`$schema` are allowed. `$ref` may reference only `#/$defs/<name>` in this
schema, without siblings; resolve and reject reference cycles on load.

Object schemas must declare `properties`, `required` (possibly empty), and
`additionalProperties: false`. Arrays must declare `items`. String bounds count
Unicode scalar values; numeric bounds use exact decimal comparisons. `default`
is a UI suggestion and never mutates loaded data. All annotations, defaults,
examples, pointers, and bounds must themselves be well typed; contradictory
bounds, invalid required fields, duplicate enum values, and dangling references
make the schema invalid. Validate defaults/examples against their subschema.

Unsupported standard keywords, unknown `x-pixorra` keys, and unsupported
compositions (`oneOf`, `if`, dynamic refs, patterns, remote refs, etc.) produce
`schema.unsupported_keyword`. Do not silently weaken validation. Ordinary
Draft 2020-12 metaschema validation runs first, then this narrower profile and
the annotation/binding checks. Later profile expansion needs a contract update.
The fixture metaschema is tooling, not a game schema, and is not restricted to
this game-schema profile.

## Annotation vocabulary

All following objects are closed. JSON pointers below are RFC 6901, case
sensitive; empty string means the pointed-to value itself. Schema field pointers
are relative to an entity's data root, not paths through `properties` keywords.
They resolve through the data shape declared by that entity's schema. Array
elements use `*` only in the explicitly designated selector forms below.

Root `x-pixorra`:

| Key | Type / rule |
|---|---|
| `contractVersion` | Required string `1.0.0`. |
| `schemaVersion` | Required canonical game version. |
| `bindings` | Required object with exactly one member per root category. Each value is `{ "path": relativeFile, "pointer": jsonPointer }`. |
| `rules` | Optional object keyed by L-1–L-14, values `{ "enabled": boolean }`; defaults enabled. |
| `expressionContext` | Optional object mapping declared property paths to `{ "type": "number"|"string"|"boolean", "source": "state"|"subject"|"neighbor", "pointer": jsonPointer }`. Paths match `[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*`; `flag` and `random` are reserved roots. |

Category array `x-pixorra`:

| Key | Type / rule |
|---|---|
| `kind` | Required: `materials`, `reactions`, `spawn_rules`, `regions`, `palettes`, `flags`, `quests`, or `dialogue`. Arbitrary category names may share a kind. |
| `idField` | Required pointer to a required, nonempty string in each item. IDs are unique across all categories with the same kind. |
| `labelField` | Optional string-field pointer for display. |
| `external` | Optional boolean, default false; material code references cause L-5 unknown. |
| `spawn_external` | Optional boolean, default false; material spawning by game code causes L-6 unknown. |
| `external_writes` | Optional boolean, default false; flags cause L-10 unknown. |
| `external_transitions` | Optional boolean, default false; quest stages advanced by code cause L-11 unknown. |
| `max_size` | Required nonnegative integer for palettes, forbidden for other kinds. |
| `roles` | Required mapping for the chosen kind, as below. |

Optional external annotations are category-wide defaults. An item may override
them only through a boolean field annotated with `externalMarker` whose value is
one of the four marker names. No built-in field named `external` is assumed.

Field `x-pixorra` may contain `reference`, `paletteIndex`, `expression`, `sprite`,
or `externalMarker`. A reference is `{ "kind": targetKind }` on a string field;
array references annotate `items`. `paletteIndex` is
`{ "paletteField": pointer }` on an integer with minimum at least zero; its
palette field is a sibling entity field annotated as a palette reference.
`expression: true` marks a string condition. `sprite` is
`{ "generated": boolean }` on a project-relative path string. `externalMarker`
marks a boolean as above. Reject incompatible combinations: a field has at most
one of these five semantic annotations. Plain JSON Schema constraints still apply.

`roles` maps the following keys to declared item-relative field pointers. Keys
marked `?` are optional; all others are required. Wrong shapes/kinds are schema
errors, and role-selected reference/expression/sprite fields must have the matching
field annotation. A selector ending in `/*` addresses elements of an array.

| Kind | Role keys and required data shapes |
|---|---|
| materials | `properties?`: object with declared scalar fields; `sprite?`: sprite string; `paletteIndex?`: annotated integer. |
| palettes | `colors`: array of strings (color spelling constrained by game enum if needed). |
| reactions | `inputs`: array of material refs; `outputs`: array of material refs; `condition?`: expression string; `exitCondition?`: expression string; `priority?`: integer. Inputs must be nonempty; outputs may be empty (consumption). |
| spawn_rules | `material`: material ref; `region?`: region ref; `condition?`: expression; `weight?`: nonnegative number. |
| regions | `min`, `max`: arrays of three numbers; `exclusive`: boolean; `materials?`: array of material refs. Bounds are half-open on each axis; require min < max componentwise. |
| flags | `initial`: boolean. |
| quests | `stages`: array of closed objects with `id` string, `terminal` boolean, `transitions` array; `initialStage`: stage ID string; `requiredFlags?`: array of flag refs; `rewards?`: array of material refs; `region?`: region ref. |
| dialogue | `lines`: array of strings; `choices?`: array of closed objects with `target` dialogue ref and optional `condition` expression. |

Quest stage/transition object key names above are conventional roles, mapped by
additional quest-role keys `stageId`, `terminal`, `transitions` relative to a
stage, and `target`, `condition?`, `setFlags?`, `priority?` relative to a transition.
`setFlags` is an array of closed objects with string `flag` (flag reference) and
boolean `value`; these two keys are fixed v1 action record keys. Stage IDs are
unique within a quest; targets resolve only within that quest. Optional stage
`external_transitions` overrides use the same marker annotation mechanism.
An empty `roles` object is valid for materials. Stage/transition role mappings
are mandatory for quests, so a third-party format may choose different field
names without code changes. Additional ordinary game fields remain editable if
declared, but acquire no implicit rule behavior.

L-1–L-14 are built-in rule algorithms bound through this vocabulary; schemas
select/configure them, never embed Python or new executable rule implementations.
Expression context adds property bindings, never functions or code.

## File bindings and closed content

Bindings assemble category arrays into one logical root object for validation.
For example `materials -> {path: "data/world.json", pointer: "/materials"}` and
`palettes -> {path: "data/world.json", pointer: "/palettes"}` share a file.
`pointer: ""` binds an entire file array and cannot share that file. A category
has one binding; a file pointer has one category; overlapping pointers are
invalid. Intermediate pointer segments must be object keys, never array indices.
No globs, symlink escapes, `..`, absolute paths, or network reads are allowed.
Paths use `/` and must resolve within the project; case-colliding paths are
rejected for portable projects.

The file's entire shape must be accounted for by its bindings: wrapper object
keys are exactly the pointer prefixes, and leaves are the declared arrays. Reject
unbound file fields as `content.undeclared_field`. This prevents assembling only
known fields and accidentally hiding undeclared ones. Unbound unrelated files
in the folder are ignored and never rewritten. A missing required bound file or
category is an error, not an empty array invented by the loader. Empty arrays
must be explicit. New files/categories require explicit creation, then validation.

Game JSON is strict UTF-8 JSON, with optional UTF-8 BOM retained. Reject duplicate
keys, comments, trailing commas, invalid scalar Unicode, and nonfinite numbers.
Unknown fields/types fail validation without discarding their original bytes.
Schema errors block editable loading; content errors allow inspection/repair.
Lint/save never silently delete unknown fields or coerce values.

## Minimal illustrative schema

This is a contract example, not the phase 1 falling-sand reference schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:pixorra:example:minimal",
  "type": "object",
  "properties": {
    "materials": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": { "id": { "type": "string", "minLength": 1 } },
        "required": ["id"],
        "additionalProperties": false
      },
      "x-pixorra": { "kind": "materials", "idField": "/id", "roles": {} }
    }
  },
  "required": ["materials"],
  "additionalProperties": false,
  "x-pixorra": {
    "contractVersion": "1.0.0",
    "schemaVersion": "1.0.0",
    "bindings": { "materials": { "path": "materials.json", "pointer": "" } }
  }
}
```
