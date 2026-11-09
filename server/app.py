"""Local FastAPI wrapper endpoints for Pixorra.

Run:  python -m server <project-folder>
or:   uvicorn server.app:app
Then open /api endpoints from the React editor (web/).

Endpoints (all local, read-only access to core; mutation only through the
SaveSession contract):

- POST /api/open          {"folder": str}  -> open/bind a project
- GET  /api/project                       -> snapshot + schema identity + lint
- GET  /api/schema                         -> schema categories (for the inspector)
- POST /api/prepare      {"models": {...}} -> SavePlan preview (diff + lint)
- POST /api/commit       {"token", ...}    -> SaveResult + refreshed snapshot
- POST /api/reload                         -> reload from disk
- POST /api/lint                           -> refresh lint report
"""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from core import (
    Diagnostic,
    Location,
    LoadError,
    LintReport,
    ProjectSnapshot,
    SaveError,
    SaveSession,
    load_project,
    lint_project,
)

from .serialize import dumps  # noqa: F401  (public helper)
from .serialize import json_bytes, loads


# --- shared api payload builders (also used by tests) ----------------------- LOCATION

def diagnostic_dict(d: Diagnostic) -> dict[str, Any]:
    return d.to_dict()


def lint_dict(report: LintReport) -> dict[str, Any]:
    return report.to_dict()


def snapshot_dict(snapshot: ProjectSnapshot) -> dict[str, Any]:
    """Project snapshot as JSON-safe primitives."""
    entities = []
    for entity in snapshot.entities:
        entities.append(
            {
                "kind": entity.kind,
                "category": entity.category,
                "id": entity.id,
                "nodeId": entity.node_id,
                "value": deepcopy(entity.value),
                "location": _location_dict(entity.location),
            }
        )
    references = [
        {
            "kind": ref.kind,
            "value": ref.value,
            "resolution": ref.resolution,
            "targets": [t.id for t in ref.targets],
            "entity": {"kind": ref.entity.kind, "id": ref.entity.id},
            "location": _location_dict(ref.location),
        }
        for ref in snapshot.references
    ]
    categories: list[dict[str, Any]] = []
    for category in snapshot.schema.categories:
        categories.append(
            {
                "name": category.name,
                "kind": category.kind,
                "path": category.path,
                "pointer": category.pointer,
                "schema": category.schema,
                "annotation": category.annotation,
                "entities": [e["id"] for e in entities if e["kind"] == category.kind],
            }
        )
    file_roots = {
        path: _plain(deepcopy(doc.root.value))
        for path, doc in snapshot.documents.items()
    }
    return {
        "root": str(snapshot.root),
        "schema": snapshot.schema.identity,
        "categories": categories,
        "entities": entities,
        "references": references,
        "diagnostics": [diagnostic_dict(d) for d in snapshot.diagnostics],
        "disabledRules": list(snapshot.disabled_rules),
        "acknowledgmentRequired": snapshot.acknowledgment_required,
        "hasErrors": snapshot.has_errors,
        # Complete ordered file roots (client sends these back for saves).
        "files": file_roots,
    }


def _location_dict(location: Location) -> dict[str, Any]:
    span = None
    if location.span is not None:
        span = {"start": location.span.start, "end": location.span.end}
    return {"path": location.path, "pointer": location.pointer, "span": span}


def error_payload(exc: SaveError | LoadError) -> dict[str, Any]:
    details = dict(getattr(exc, "details", {}) or {})
    # Conflict payloads carry raw bytes (currentBytes, diff, byteMetadata);
    # make them JSON-safe text without touching the core's semantics.
    safe: dict[str, Any] = {}
    for key, value in details.items():
        if isinstance(value, bytes):
            safe[key] = value.decode("utf-8", "replace")
        elif isinstance(value, dict):
            safe[key] = {
                k: (v.decode("utf-8", "replace") if isinstance(v, bytes) else v)
                for k, v in value.items()
            }
        else:
            safe[key] = value
    diagnostics = [diagnostic_dict(d) for d in getattr(exc, "diagnostics", ()) or ()]
    out: dict[str, Any] = {"code": getattr(exc, "code", "load.error"), "details": safe}
    if diagnostics:
        out["diagnostics"] = diagnostics
    return out


# --- application state ------------------------------------------------------ LOCATION

class _State:
    """One opened project per app instance (FR-5: one project at a time)."""

    def __init__(self) -> None:
        self.project: ProjectSnapshot | None = None
        self.session: SaveSession | None = None
        self.lint: LintReport | None = None
        self.plans: dict[str, Any] = {}

    def reset(self, folder: str | Path, schema_path: str | None = None) -> None:
        self.project = load_project(Path(folder), schema_path)
        self.session = None
        self.lint = None

    def require(self) -> tuple[ProjectSnapshot, SaveSession]:
        if self.project is None:
            raise SaveError("project.not_open", {})
        if self.session is None:
            self.session = SaveSession(self.project)
        assert self.session is not None
        return self.project, self.session


def refresh_lint(state: _State) -> LintReport:
    assert state.project is not None
    state.lint = lint_project(state.project)
    return state.lint


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _deepcopy_model(models: dict[str, Any]) -> dict[str, Any]:
    return {path: deepcopy(value) for path, value in models.items()}


async def body_json(request: Request) -> Any:
    raw = await request.body()
    if not raw:
        return {}
    return loads(raw)


# --- app factory ------------------------------------------------------------ LOCATION

def create_app(folder: str | None = None, schema: str | None = None) -> FastAPI:
    app = FastAPI(title="Pixorra local API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    state = _State()
    if folder is not None:
        state.reset(folder, schema)

    def ok(payload: Any) -> Response:
        return Response(content=json_bytes(payload), media_type="application/json; charset=utf-8")

    @app.post("/api/open", response_class=Response)
    async def open_project(request: Request) -> Response:
        data = await body_json(request)
        if not isinstance(data, dict):
            data = {}
        folder = data.get("folder")
        if not isinstance(folder, str) or not folder:
            return ok({"code": "open.invalid_folder", "error": "folder is required"})
        try:
            state.reset(folder, data.get("schema"))
        except LoadError as exc:
            return ok({"code": "open.load_failed", "error": error_payload(exc)})
        assert state.project is not None
        return ok(
            {
                "snapshot": snapshot_dict(state.project),
                "lint": refresh_lint(state).to_dict(),
            }
        )

    @app.get("/api/project", response_class=Response)
    async def get_project() -> Response:
        if state.project is None:
            return ok({"code": "project.not_open"})
        return ok(
            {
                "snapshot": snapshot_dict(state.project),
                "lint": refresh_lint(state).to_dict(),
            }
        )

    @app.get("/api/schema", response_class=Response)
    async def get_schema() -> Response:
        if state.project is None:
            return ok({"code": "project.not_open"})
        snapshot = state.project
        return ok(
            {
                "schema": snapshot.schema.identity,
                "categories": snapshot_dict(snapshot)["categories"],
                "expressionContext": snapshot.schema.data.get("x-pixorra", {}).get(
                    "expressionContext", {}
                ),
            }
        )

    @app.post("/api/prepare", response_class=Response)
    async def prepare(request: Request) -> Response:
        data = await body_json(request)
        if not isinstance(data, dict):
            data = {}
        try:
            _project, session = state.require()
        except SaveError as exc:
            return ok({"error": error_payload(exc)})
        try:
            plan = session.prepare(
                _deepcopy_model(data.get("models") or {}),
                acknowledge_schema=bool(data.get("acknowledgeSchema")),
            )
        except SaveError as exc:
            return ok({"error": error_payload(exc)})
        state.plans.clear()
        state.plans[plan.token] = plan
        return ok(
            {
                "plan": {
                    "token": plan.token,
                    "revision": plan.revision,
                    "schemaHash": plan.schema_hash,
                    "files": [
                        {
                            "path": fp.path,
                            "sourceHash": fp.source_hash,
                            "candidateHash": fp.candidate_hash,
                            "diff": fp.diff,
                            "byteMetadata": _plain(dict(fp.byte_metadata)),
                        }
                        for fp in plan.files
                    ],
                    "touchedKeys": [
                        {"path": p, "topKey": k} for p, k in plan.touched_keys
                    ],
                    "previewRequired": plan.preview_required,
                    "history": (
                        None
                        if plan.history_preview is None
                        else {
                            "path": plan.history_preview.path,
                            "diff": plan.history_preview.diff,
                            "byteMetadata": _plain(
                                dict(plan.history_preview.byte_metadata)
                            ),
                        }
                    ),
                    "historyPreview": plan.history_preview is not None,
                    "acknowledgedSchema": plan.acknowledged_schema,
                    "resetHistory": plan.reset_history,
                    "lint": plan.lint.to_dict(),
                }
            }
        )

    @app.post("/api/commit", response_class=Response)
    async def commit(request: Request) -> Response:
        data = await body_json(request)
        if not isinstance(data, dict):
            data = {}
        try:
            _project, session = state.require()
        except SaveError as exc:
            return ok({"error": error_payload(exc)})
        token = data.get("token")
        plan = state.plans.get(token)
        if plan is None:
            return ok({"error": {"code": "commit.unknown_plan"}})
        try:
            result = session.commit(
                plan,
                acknowledge_preview=(
                    token if data.get("acknowledgePreview") else None
                ),
            )
        except SaveError as exc:
            return ok({"error": error_payload(exc)})
        result_dict = {
            "status": result.status,
            "files": list(result.files),
            "diagnostics": [dict(d) for d in result.diagnostics],
        }
        if result.status in {"saved", "saved_durability_unknown", "unchanged"}:
            state.project = session.reload()
            state.lint = None
            state.plans.clear()
        return ok(
            {
                "result": result_dict,
                "snapshot": snapshot_dict(state.project) if state.project else None,
                "lint": refresh_lint(state).to_dict() if result.status in {"saved", "saved_durability_unknown", "unchanged"} else None,
            }
        )

    @app.post("/api/reload", response_class=Response)
    async def reload_project() -> Response:
        try:
            _project, session = state.require()
        except SaveError as exc:
            return ok({"error": error_payload(exc)})
        state.project = session.reload()
        state.lint = None
        state.plans.clear()
        return ok(
            {
                "snapshot": snapshot_dict(state.project) if state.project else None,
                "lint": refresh_lint(state).to_dict(),
            }
        )

    @app.post("/api/lint", response_class=Response)
    async def lint() -> Response:
        if state.project is None:
            return ok({"code": "project.not_open"})
        return ok({"lint": refresh_lint(state).to_dict()})

    return app


# Plans are tracked per-opened-project on the app state (state.plans), keyed by
# token. The core session's security model (fresh-token approval, preview
# gating, conflict tracking) is unchanged; this avoids shipping whole plan
# objects back through the client.

app = create_app()
