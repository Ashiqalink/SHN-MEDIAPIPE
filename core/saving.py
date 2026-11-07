"""Frozen save plans, exact diff approval, conflict checks and atomic files.

Replacements are atomic per file. Portable APIs cannot exclude a noncooperating
writer between the last hash check and os.replace; batches are not transactions.
"""

from dataclasses import dataclass, field
from hashlib import sha256
import difflib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import uuid

from .diagnostics import LoadError
from .editing import VerificationError, edit_document, new_document, verify_edit
from .lint import lint_project
from .project import _history, load_project
from .schema import safe_path
from .source import parse_document, segments


def digest(raw):
    return None if raw is None else sha256(raw).hexdigest()


class SaveError(Exception):
    def __init__(self, code, message, **details):
        self.code, self.details = code, details
        super().__init__(message)


@dataclass(frozen=True)
class FilePlan:
    path: str
    source_hash: str | None
    original: bytes | None
    candidate: bytes
    candidate_hash: str
    diff: str
    byte_metadata: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class SavePlan:
    token: str
    revision: int
    schema_hash: str
    files: tuple[FilePlan, ...]
    touched_keys: tuple[tuple[str, str], ...]
    preview_required: bool
    history_hash: str | None
    history_bytes: bytes | None
    acknowledged_schema: bool
    reset_history: bool
    history_preview: FilePlan | None
    lint: object = field(compare=False, repr=False)

    def preview(self):
        return {"token": self.token, "revision": self.revision,
                "schemaHash": self.schema_hash, "previewRequired": self.preview_required,
                "touchedKeys": list(self.touched_keys),
                "files": [{"path": f.path, "sourceHash": f.source_hash,
                           "candidateHash": f.candidate_hash, "diff": f.diff,
                           "byteMetadata": dict(f.byte_metadata)} for f in self.files],
                "historyHash": self.history_hash,
                "history": None if self.history_preview is None else {
                    "path": self.history_preview.path,
                    "sourceHash": self.history_preview.source_hash,
                    "candidateHash": self.history_preview.candidate_hash,
                    "diff": self.history_preview.diff,
                    "byteMetadata": dict(self.history_preview.byte_metadata)},
                "lint": self.lint.to_dict()}


@dataclass(frozen=True)
class SaveResult:
    status: str
    files: tuple[dict, ...] = ()
    diagnostics: tuple[dict, ...] = ()


_LOCK = threading.RLock()  # One process-wide lock also serializes overlapping sessions.


def _path(root, relative):
    try:
        result = safe_path(root, relative)
        # Refuse aliases as well as escapes, including symlinked parent directories.
        current = root
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise ValueError("Symlink or junction in save path")
        return result
    except (ValueError, OSError) as exc:
        raise SaveError("save.path_invalid", "Save path is unsafe.", path=relative) from exc


def _read(root, relative):
    try:
        return _path(root, relative).read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SaveError("save.read_failed", "Cannot read destination.", path=relative) from exc


def _format_metadata(raw):
    if raw is None:
        return {"exists": False, "bom": False, "crlf": 0, "lf": 0, "cr": 0, "finalNewline": ""}
    ending = "CRLF" if raw.endswith(b"\r\n") else "LF" if raw.endswith(b"\n") else "CR" if raw.endswith(b"\r") else ""
    return {"exists": True, "bom": raw.startswith(b"\xef\xbb\xbf"),
            "crlf": raw.count(b"\r\n"), "lf": raw.count(b"\n") - raw.count(b"\r\n"),
            "cr": raw.count(b"\r") - raw.count(b"\r\n"), "finalNewline": ending}


def _diff(path, before, after):
    # keepends=False avoids hiding a missing final newline; metadata captures it.
    lines = list(difflib.unified_diff(
        (before or b"").decode("utf-8", errors="backslashreplace").splitlines(),
        after.decode("utf-8").splitlines(), fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""))
    metadata = (("before", _format_metadata(before)), ("after", _format_metadata(after)))
    return "\n".join(lines) + ("\n" if lines else ""), metadata


def _check(root, relative, expected, candidate=None):
    current = _read(root, relative)
    if digest(current) != expected:
        diff, metadata = _diff(relative, current, candidate) if candidate is not None else ("", ())
        raise SaveError("save.conflict", "Destination changed; reload or prepare an explicit override.",
                        path=relative, observedHash=digest(current), currentBytes=current,
                        diff=diff, byteMetadata=dict(metadata))


def _sync_directory(path):
    if os.name == "nt":
        return  # Python has no supported directory-fsync API on Windows.
    import errno
    try:
        handle = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(handle)
        finally:
            os.close(handle)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS):
            raise


def _atomic(root, relative, candidate, expected, check_schema):
    _check(root, relative, expected, candidate)
    target = _path(root, relative)
    temp = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _path(root, relative)
        fd, temp = tempfile.mkstemp(prefix=".pixorra-", suffix=".tmp", dir=target.parent)
        with os.fdopen(fd, "wb") as stream:
            if target.exists():
                os.chmod(temp, stat.S_IMODE(target.stat().st_mode))
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        if Path(temp).read_bytes() != candidate:
            raise SaveError("save.verification_failed", "Temporary file differs from verified candidate.", path=relative)
        _check(root, relative, expected, candidate)
        check_schema()
        # Re-resolve immediately before replace; no delete/truncate fallback.
        target = _path(root, relative)
        try:
            os.replace(temp, target)
        except OSError as exc:
            raise SaveError("save.replace_failed", "Atomic replacement failed.", path=relative) from exc
        temp = None
        try:
            _sync_directory(target.parent)
        except OSError:
            return "saved_durability_unknown"
        return "saved"
    except OSError as exc:
        raise SaveError("save.write_failed", "Temporary write failed.", path=relative) from exc
    finally:
        if temp is not None:
            try:
                Path(temp).unlink(missing_ok=True)
            except OSError:
                pass


class SaveSession:
    """One opened-project session. Caller models remain caller-owned and mutable.

    prepare freezes them into bytes; edits after preparation are never cleared.
    Reload explicitly discards the session baseline and invalidates every plan.
    """

    def __init__(self, project):
        self.project = project
        self.revision = 0
        self._first_save = True
        self._plans = {}
        self._reload_required = False
        self._schema_path = project.schema.document.path
        self._config_hash = digest(_read(project.root, ".pixorra/project.json"))

    def reload(self):
        with _LOCK:
            self.project = load_project(self.project.root, self._schema_path)
            self.revision += 1
            self._plans.clear()
            self._reload_required = False
            self._config_hash = digest(_read(self.project.root, ".pixorra/project.json"))
            return self.project

    def _check_schema(self):
        if self._reload_required:
            raise SaveError("save.reload_required", "Reload after the schema/configuration changed during a commit.")
        if digest(_read(self.project.root, self._schema_path)) != self.project.schema.document.hash:
            raise SaveError("save.schema_changed", "Selected schema changed; reload before saving.")
        if digest(_read(self.project.root, ".pixorra/project.json")) != self._config_hash:
            raise SaveError("save.config_changed", "Project configuration changed; reload before saving.")

    def prepare(self, models=None, *, acknowledge_schema=False, override_hashes=None):
        """models maps bound file paths to complete ordered target JSON values.

        override_hashes is an explicit {path: observedHash-or-None} approval to
        replace exactly that disk revision. It always requires a fresh preview.
        No files or sidecars are written here.
        """
        with _LOCK:
            return self._prepare(models or {}, acknowledge_schema, override_hashes or {})

    def _prepare(self, models, acknowledge_schema, overrides):
        project = self.project
        bound = {c.path for c in project.schema.categories}
        if set(models) - bound or set(overrides) - set(models):
            raise SaveError("save.invalid_target", "Only bound game files may be edited or overridden.")
        raw = dict(project.raw_files)
        files, touched = [], set()
        for path, model in sorted(models.items()):
            document = project.documents.get(path)
            original = project.raw_files.get(path)
            try:
                if document:
                    edit = edit_document(document, model)
                    verify_edit(edit, model)
                    candidate = edit.candidate
                    pointers = [p.pointer for p in edit.patches]
                else:
                    candidate = new_document(model, path)
                    pointers = [""]
            except VerificationError as exc:
                raise SaveError("save.verification_failed", str(exc), path=path) from exc
            except (ValueError, TypeError, UnicodeError, LoadError, RecursionError) as exc:
                raise SaveError("save.invalid_content", "Target is not valid portable JSON.", path=path) from exc
            raw[path] = candidate
            if original == candidate and path not in overrides:
                continue
            self._check_schema()
            before = original
            if path in overrides:
                before = _read(project.root, path)
                if digest(before) != overrides[path]:
                    _check(project.root, path, overrides[path], candidate)
                # An override replaces the external revision, so count its root.
                pointers = [""]
            for pointer in pointers:
                parts = segments(pointer)
                touched.add((path, parts[0] if parts else ""))
            diff, metadata = _diff(path, before, candidate)
            files.append(FilePlan(path, digest(before), before, candidate, digest(candidate), diff, metadata))
        history = _read(project.root, ".pixorra/state.json") if files else None
        if files:
            self._check_schema()
        try:
            validated = load_project(project.root, self._schema_path, _raw_files=raw) if files else project
        except LoadError as exc:
            raise SaveError("save.invalid_content", "Schema/configuration cannot be validated.",
                            diagnostics=[d.to_dict() for d in exc.diagnostics]) from exc
        if files and validated.has_errors:
            raise SaveError("save.invalid_content", "Structural validation failed.",
                            diagnostics=[d.to_dict() for d in validated.diagnostics if d.severity == "error"])
        # History describes the loaded baseline, not the unsaved candidate.
        history_diagnostics, history_ack = _history(project.root, project.schema, project.documents) if files else ((), False)
        if files and (project.acknowledgment_required or history_ack) and not acknowledge_schema:
            raise SaveError("save.schema_acknowledgment_required", "Acknowledge schema/history warnings before saving.")
        # Validate the whole batch before any initial conflict check or write.
        for item in files:
            _check(project.root, item.path, item.source_hash, item.candidate)
        reset_history = any(d.code == "schema.history_invalid" for d in history_diagnostics)
        history_preview = None
        if files:
            self._check_schema()
            _check(project.root, ".pixorra/state.json", digest(history))
            history_candidate = self._history_content(history, files, reset_history)
            history_diff, history_metadata = _diff(".pixorra/state.json", history, history_candidate)
            history_preview = FilePlan(".pixorra/state.json", digest(history), history,
                                       history_candidate, digest(history_candidate), history_diff, history_metadata)
        # A new preparation supersedes previous model revisions and approvals.
        self.revision += 1
        plan = SavePlan(uuid.uuid4().hex, self.revision, project.schema.document.hash,
                        tuple(files), tuple(sorted(touched)),
                        bool(files) and (self._first_save or len(touched) > 1 or bool(overrides)),
                        digest(history), history, acknowledge_schema, reset_history,
                        history_preview, lint_project(validated))
        self._plans.clear()
        self._plans[plan.token] = plan
        return plan

    def commit(self, plan, *, acknowledge_preview=None):
        with _LOCK:
            if self._plans.get(plan.token) is not plan or plan.revision != self.revision:
                raise SaveError("save.stale_plan", "Plan is no longer current; prepare again.")
            if not plan.files:
                return SaveResult("unchanged")
            self._check_schema()
            for item in plan.files:
                _check(self.project.root, item.path, item.source_hash, item.candidate)
            _check(self.project.root, ".pixorra/state.json", plan.history_hash)
            if plan.preview_required and acknowledge_preview != plan.token:
                raise SaveError("save.preview_required", "Acknowledge this exact preview before committing.", preview=plan.preview())
            results, diagnostics, committed = [], [], []
            for item in plan.files:
                try:
                    status = _atomic(self.project.root, item.path, item.candidate,
                                     item.source_hash, self._check_schema)
                except SaveError as exc:
                    results.append({"path": item.path, "status": exc.code})
                    diagnostics.append({"code": exc.code, "path": item.path})
                    break
                committed.append(item)
                results.append({"path": item.path, "status": status, "hash": item.candidate_hash})
            for item in plan.files[len(results):]:
                results.append({"path": item.path, "status": "not_saved"})
            if committed:
                try:
                    self._save_history(plan, committed)
                except (SaveError, LoadError, ValueError, OSError) as exc:
                    diagnostics.append({"code": "save.history_failed", "reason": getattr(exc, "code", str(exc))})
                self._first_save = False
                # Update only committed baselines; never adopt unrelated external writes.
                raw = dict(self.project.raw_files)
                raw.update({f.path: f.candidate for f in committed})
                try:
                    self._check_schema()
                    refreshed = load_project(self.project.root, self._schema_path, _raw_files=raw)
                    self._check_schema()
                    if refreshed.schema.document.hash != plan.schema_hash:
                        raise SaveError("save.schema_changed", "Schema changed during refresh.")
                    self.project = refreshed
                except (LoadError, SaveError):
                    # Schema may have changed after replace: keep known committed bytes
                    # and require reload rather than treating stale spans as current.
                    from dataclasses import replace
                    documents = dict(self.project.documents)
                    documents.update({f.path: parse_document(f.candidate, f.path) for f in committed})
                    self.project = replace(self.project, documents=documents, raw_files=raw)
                    self._reload_required = True
                    diagnostics.append({"code": "save.reload_required"})
                self.revision += 1
                self._plans.clear()
            status = "partial" if committed and len(committed) != len(plan.files) else (
                "failed" if not committed else "saved_durability_unknown" if any(
                    r["status"] == "saved_durability_unknown" for r in results) else "saved")
            return SaveResult(status, tuple(results), tuple(diagnostics))

    def _save_history(self, plan, committed):
        candidate = self._history_content(plan.history_bytes, committed, plan.reset_history)
        status = _atomic(self.project.root, ".pixorra/state.json", candidate,
                         plan.history_hash, self._check_schema)
        if status == "saved_durability_unknown":
            raise SaveError("save.history_durability_unknown", "History directory sync failed.")

    def _history_content(self, original, committed, reset):
        history = {"stateVersion": 1, "files": {}}
        if original is not None and not reset:
            history = parse_document(original, ".pixorra/state.json").root.value
        identity = self.project.schema.identity
        for item in committed:
            history["files"][item.path] = {"contentHash": item.candidate_hash,
                "schemaId": identity["id"], "schemaVersion": identity["version"],
                "schemaHash": identity["hash"]}
        candidate = new_document(history, ".pixorra/state.json")
        parsed = parse_document(candidate, ".pixorra/state.json")
        if parsed.root.value != history:
            raise SaveError("save.verification_failed", "History verification failed.")
        return candidate
