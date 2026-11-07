# Pixorra

A standalone, local authoring and linting tool for game JSON. Product scope is
in [the PRD](docs/PRD.md); delivery order is in [PLAN.md](PLAN.md).

Phases 0, 1 and 2 are complete: contracts, a headless project loader, verified
minimal-diff saves and the MVP lint rules are available. The graph editor,
remaining lint rules and simulator arrive in later phases.

- [Decisions and compatibility policy](docs/decisions.md)
- [Schema and project contract](docs/schema-contract.md)
- [Ordered model, references, and diagnostics](docs/model-contract.md)
- [Expressions, randomness, and shared transitions](docs/evaluation-contract.md)
- [Verified saves and conflict handling](docs/save-contract.md)
- [Save API and failure handling](docs/saving.md)
- [MVP lint rules and examples](docs/lint.md)
- [Fixture format and acceptance matrix](spec/README.md)
- [Current progress](PROGRESS.md)

No dependency on any surrounding game project is permitted. Python 3.11+ is the
first implementation target; later backends must pass the same shared fixtures.

Install from this directory with `python -m pip install -e .`. The only runtime
dependency is `jsonschema` 4.x; no FastAPI or frontend packages are needed.

```text
python -m core examples/falling-sand
python -m core examples/falling-sand --lint
python -m unittest discover -s tests -v
```

The installed `pixorra <folder> [--schema relative/path.schema.json]` command
prints deterministic JSON containing schema identity/hash, files, entities,
resolved/missing/ambiguous references, diagnostics, and schema acknowledgment
state. Add `--lint` for L-1, L-3, L-5 and L-14 with separate severity/unknown
counts and disabled rules. It exits 1 on structural or enabled lint errors,
0 otherwise. Inspection and lint write no files. New projects report
informational `schema.history_missing` until their first mutating save.

For scripts:

```python
from core import load_project

project = load_project("examples/falling-sand")
material = project.resolve("materials", "water")[0]
source = project.documents[material.location.path]
print(material.id, source.hash, material.location.span)
```

Invalid schemas/configuration raise `LoadError` with portable diagnostics. Invalid
content returns an inspectable snapshot with `has_errors`, diagnostics, and
original `raw_files`, including bytes that failed parsing. Treat snapshots as
read-only. Call `lint_project(project)` for semantic lint; loading alone retains
the structural diagnostics and reference index. `SaveSession(project)` prepares
frozen, verified edits, exposes required previews and commits approved plans.
See [the save API](docs/saving.md) for acknowledgment and conflict handling.
