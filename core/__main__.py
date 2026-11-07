"""Small read-only entry point; no local web server is required."""

import argparse
import json

from . import LoadError, lint_project, load_project


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect and validate a Pixorra project.")
    parser.add_argument("folder")
    parser.add_argument("--schema", help="Project-relative schema path (default: project.schema.json)")
    parser.add_argument("--lint", action="store_true", help="Run the MVP lint rules")
    args = parser.parse_args(argv)
    try:
        project = load_project(args.folder, args.schema)
    except LoadError as exc:
        print(json.dumps({"diagnostics": [d.to_dict() for d in exc.diagnostics]}, ensure_ascii=False, indent=2))
        return 1
    result = {
        "schema": project.schema.identity,
        "files": [{"path": d.path, "hash": d.hash} for d in project.documents.values()],
        "entities": [{"kind": e.kind, "id": e.id, "path": e.location.path,
                      "pointer": e.location.pointer} for e in project.entities],
        "references": [{"kind": r.kind, "value": r.value, "resolution": r.resolution,
                        "location": {"path": r.location.path, "pointer": r.location.pointer}}
                       for r in project.references],
        "disabledRules": list(project.disabled_rules),
        "acknowledgmentRequired": project.acknowledgment_required,
        "diagnostics": [d.to_dict() for d in project.diagnostics],
    }
    report = lint_project(project) if args.lint else None
    if report is not None:
        result["lint"] = report.to_dict()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if project.has_errors or (report is not None and report.counts["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
