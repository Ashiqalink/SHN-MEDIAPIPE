# Pixorra progress

Last updated: 2026-11-07, after phase 2 implementation and final verification.

Now: Phases 0, 1 and 2 complete. Headless loading, verified minimal-diff saves
and the four MVP lint rules are available.
Next: Phase 3 - local graph authoring, web API and editor integration (not started).
Blocked: None.

- [x] 0 - Contracts and decisions
- [x] 1 - MVP: schemas and project core
- [x] 2 - MVP: safe writes and four lint checks
- [ ] 3 - MVP: local graph authoring
- [ ] 4 - M2: expressions and complete lint
- [ ] 5 - M2: whole-project and quest authoring
- [ ] 6 - M3: headless simulator and batches
- [ ] 7 - M3: simulator UI and v1 validation
- [ ] 8 - Stretch (optional)

Validation (2026-11-07): `python -m unittest discover -s tests` passes all 53 tests
on Windows with Python 3.13.0 and jsonschema 4.26.0. Python 3.11 syntax is checked;
runtime execution on Python 3.11 and other operating systems remains unverified.
The suite includes 21 existing tests and 32 phase 2 tests. Local documentation
links and completed-phase markers also pass validation. The sample CLI with
`--lint` exits successfully with no lint diagnostics.

Phase 2 evidence: all four raw round-trip seeds preserve no-op bytes and edit
only the intended span. Eleven exact golden lint reports cover L-1, L-3, L-5,
L-14, external unknowns, item overrides and disabled rules. Seven shared save
scenarios and additional fault tests cover previews, frozen plans, no-op writes,
schema/history acknowledgment, conflicts and overrides, reload, final hash/schema
checks, temporary-file corruption, atomic replacement failures, history failures,
partial batches, symlinks and post-replace durability uncertainty. The sample
has zero MVP lint outcomes. Saves remain explicit; inspection/lint are read-only.

Implemented entry points: [byte editing](core/editing.py),
[save sessions](core/saving.py), [lint reports](core/lint.py), and the
[CLI](core/__main__.py). Acceptance checks are in
[phase 2 tests](tests/test_phase2.py), with shared
[lint reports](spec/fixtures/lint/mvp.json) and
[save scenarios](spec/fixtures/save/mvp.json).

Phase 3 starts with the local FastAPI wrapper and React/TypeScript graph editor.
Its exit checks include authoring, saving and reopening five materials, graph
undo/redo, required save previews, conflict handling and minimal diffs. The
under-five-minute authoring target remains to be measured in that phase.

See [save API](docs/saving.md), [lint rules](docs/lint.md),
[contracts](README.md), [shared fixtures](spec/README.md) and [PLAN.md](PLAN.md).
Content/history and whole batches are not atomic transactions. Portable APIs
retain a race against noncooperating writers after the final hash check.
RNG vectors are recorded for later implementation. Package/trademark
availability, expressions, simulation, the other ten lint rules and UI remain
later-phase work.
