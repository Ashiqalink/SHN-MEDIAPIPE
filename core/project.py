"""Read-only, hash-aware project loading, validation, and reference indexing."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .diagnostics import Diagnostic, LoadError, Location, sort_diagnostics
from .schema import GameSchema, RULE_IDS, VERSION, load_schema, safe_path
from .source import SourceDocument, escape, parse_document, segments


def value_at(value, pointer):
    for segment in segments(pointer):
        value = value[int(segment)] if isinstance(value, list) else value[segment]
    return value


@dataclass(frozen=True)
class Entity:
    kind: str
    id: str
    category: str
    value: dict[str, Any]
    location: Location
    node_id: str


@dataclass(frozen=True)
class ReferenceUse:
    kind: str
    value: str
    location: Location
    entity: Entity
    resolution: str
    targets: tuple[Entity, ...]


@dataclass(frozen=True)
class ProjectSnapshot:
    root: Path
    schema: GameSchema
    documents: dict[str, SourceDocument]
    entities: tuple[Entity, ...]
    references: tuple[ReferenceUse, ...]
    index: dict[tuple[str, str], tuple[Entity, ...]]
    diagnostics: tuple[Diagnostic, ...]
    disabled_rules: tuple[str, ...]
    acknowledgment_required: bool = False
    raw_files: dict[str, bytes] = field(default_factory=dict)

    @property
    def has_errors(self):
        return any(d.severity == "error" and d.outcome == "fail" for d in self.diagnostics)

    def resolve(self, kind, identity):
        return self.index.get((kind, identity), ())


def _read_metadata(root, relative, version_key, allowed, required):
    try:
        path = safe_path(root, relative)
    except ValueError as exc:
        raise LoadError([Diagnostic("project.metadata_invalid", "Metadata path resolves outside the project.", Location(relative))]) from exc
    if not path.exists():
        return None
    try:
        document = parse_document(path.read_bytes(), relative)
    except OSError as exc:
        raise LoadError([Diagnostic("project.metadata_invalid", "Cannot read editor metadata.", Location(relative))]) from exc
    value = document.root.value
    if (not isinstance(value, dict) or value.keys() - set(allowed)
            or not set(required).issubset(value) or isinstance(value.get(version_key), bool)
            or value.get(version_key) != 1):
        raise LoadError([Diagnostic("project.metadata_invalid", "Invalid or unsupported editor metadata.", document.location())])
    return value


def _config(root):
    config = _read_metadata(root, ".pixorra/project.json", "configVersion",
                            ("configVersion", "schemaPath", "disabledRules"), ("configVersion",)) or {}
    disabled = config.get("disabledRules", [])
    if (not isinstance(disabled, list) or any(not isinstance(r, str) or r not in RULE_IDS for r in disabled)
            or len(set(disabled)) != len(disabled)
            or ("schemaPath" in config and not isinstance(config["schemaPath"], str))):
        raise LoadError([Diagnostic("project.config_invalid", "Invalid schema path or disabled-rule list.", Location(".pixorra/project.json"))])
    return config


def _history(root, schema, documents):
    diagnostics = []
    location = Location(".pixorra/state.json")
    try:
        history = _read_metadata(root, location.path, "stateVersion", ("stateVersion", "files"), ("stateVersion", "files"))
        if history is None:
            return [Diagnostic("schema.history_missing", "No previous save schema is recorded.",
                               location, severity="info")], False
        files = history["files"]
        if not isinstance(files, dict):
            raise ValueError("Invalid files map")
        import re
        for path, entry in files.items():
            safe_path(root, path)
            if (not isinstance(entry, dict) or entry.keys() != {"contentHash", "schemaId", "schemaVersion", "schemaHash"}
                    or any(not isinstance(v, str) for v in entry.values())
                    or not VERSION.fullmatch(entry.get("schemaVersion", ""))
                    or not entry.get("schemaId")
                    or any(not re.fullmatch("[0-9a-f]{64}", entry[k]) for k in ("contentHash", "schemaHash"))):
                raise ValueError("Invalid history entry")
        acknowledgment = False
        identity = schema.identity
        for path, document in documents.items():
            entry = files.get(path)
            if entry is None:
                diagnostics.append(Diagnostic("schema.history_missing", "No previous save schema is recorded.", Location(path), severity="info"))
                continue
            checks = (
                (entry["contentHash"] != document.hash, "schema.history_stale", "Save history does not match current content."),
                (entry["schemaVersion"] != identity["version"], "schema.version_mismatch", "Selected schema version differs from the last save."),
                (entry["schemaId"] != identity["id"], "schema.identity_mismatch", "Selected schema identity differs from the last save."),
                (entry["schemaId"] == identity["id"] and entry["schemaVersion"] == identity["version"] and entry["schemaHash"] != identity["hash"],
                 "schema.content_changed", "Schema bytes changed without a version change."),
            )
            for condition, code, message in checks:
                if condition:
                    diagnostics.append(Diagnostic(code, message, Location(path), severity="warning"))
                    acknowledgment = True
        return diagnostics, acknowledgment
    except (LoadError, ValueError, TypeError):
        return [Diagnostic("schema.history_invalid", "Save history is invalid; acknowledge reset before saving.",
                           location, severity="warning")], True


def _content_errors(category, errors, document):
    result = []
    for error in errors:
        pointer = category.pointer + "".join("/" + escape(str(p)) for p in error.path)
        code, rule = "content.constraint", None
        if error.validator == "type":
            code, rule = "type.mismatch", "L-14"
            message = f"Expected {error.validator_value}."
        elif error.validator == "additionalProperties":
            code, message = "content.undeclared_field", "Object contains undeclared fields."
        elif error.validator == "required":
            code, message = "content.required", "A required field is missing."
        else:
            code, message = "content.range", f"Value violates {error.validator}."
        result.append(Diagnostic(code, message, document.location(pointer), rule=rule))
    return result


def _walk_references(schema, node_schema, node, pointer, entity, document, index):
    node_schema = schema.resolve(node_schema)
    annotation = node_schema.get("x-pixorra", {})
    uses = []
    ref = annotation.get("reference")
    if ref and isinstance(node, str):
        targets = index.get((ref["kind"], node), ())
        uses.append(ReferenceUse(ref["kind"], node, document.location(pointer), entity,
                                 "missing" if not targets else "resolved" if len(targets) == 1 else "ambiguous", targets))
    if isinstance(node, dict) and node_schema.get("type") == "object":
        for key, child in node.items():
            if key in node_schema["properties"]:
                uses.extend(_walk_references(schema, node_schema["properties"][key], child,
                            pointer + "/" + escape(key), entity, document, index))
    elif isinstance(node, list) and node_schema.get("type") == "array":
        for i, child in enumerate(node):
            uses.extend(_walk_references(schema, node_schema["items"], child,
                        pointer + f"/{i}", entity, document, index))
    return uses


def load_project(folder: str | Path, schema_path: str | None = None, *,
                 _raw_files: dict[str, bytes] | None = None) -> ProjectSnapshot:
    """Open game content without a server, UI, filesystem writes, or network access.

    Invalid schema/config raises LoadError. Invalid content stays inspectable in
    a snapshot with diagnostics and its original bytes; it is never coerced.
    """
    root = Path(folder).resolve()
    if not root.is_dir():
        raise LoadError([Diagnostic("project.not_directory", "Project folder does not exist.", Location(""))])
    config = _config(root)
    try:
        selected = safe_path(root, schema_path if schema_path is not None else config.get("schemaPath", "project.schema.json"))
    except (ValueError, TypeError) as exc:
        raise LoadError([Diagnostic("project.schema_path_invalid", "Schema path must resolve within the project.", Location(""))]) from exc
    schema = load_schema(selected, root)
    resolved_bindings = {}
    for category in schema.categories:
        resolved = safe_path(root, category.path)
        if resolved in resolved_bindings and resolved_bindings[resolved] != category.path:
            raise LoadError([Diagnostic("schema.binding_invalid", "Multiple paths alias the same content file.", schema.document.location())])
        resolved_bindings[resolved] = category.path
    if any(safe_path(root, c.path) == selected for c in schema.categories):
        raise LoadError([Diagnostic("schema.binding_invalid", "A game binding cannot overwrite its schema.", schema.document.location())])
    documents, raw_files, diagnostics = {}, {}, []
    # Build expected physical wrapper shape; schema loading already rejected overlaps.
    layouts = {}
    for category in schema.categories:
        current = layouts.setdefault(category.path, {})
        parts = segments(category.pointer)
        for part in parts:
            current = current.setdefault(part, {})
        current[None] = category.name
    for relative in sorted(layouts):
        try:
            path = safe_path(root, relative)
            raw_files[relative] = (_raw_files[relative] if _raw_files is not None
                                   else path.read_bytes())
            documents[relative] = parse_document(raw_files[relative], relative)
        except (OSError, KeyError):
            diagnostics.append(Diagnostic("content.read_failed", "Cannot read a bound content file.", Location(relative)))
        except ValueError:
            diagnostics.append(Diagnostic("content.path_invalid", "Content path resolves outside the project.", Location(relative)))
        except LoadError as exc:
            diagnostics.extend(exc.diagnostics)

    def validate_layout(shape, value, document, pointer=""):
        if None in shape:
            return
        if not isinstance(value, dict):
            diagnostics.append(Diagnostic("type.mismatch", "Expected object.", document.location(pointer), rule="L-14"))
            return
        for key in value.keys() - shape.keys():
            diagnostics.append(Diagnostic("content.undeclared_field", "Object contains an unbound field.", document.location(pointer + "/" + escape(key))))
        for key in shape:
            child_pointer = pointer + "/" + escape(key)
            if key not in value:
                diagnostics.append(Diagnostic("content.required", "A bound category or wrapper is missing.", document.location(child_pointer)))
            else:
                validate_layout(shape[key], value[key], document, child_pointer)

    for path, document in documents.items():
        validate_layout(layouts[path], document.root.value, document)
    entities, pairs = [], []
    for category in schema.categories:
        document = documents.get(category.path)
        if document is None:
            continue
        try:
            values = value_at(document.root.value, category.pointer)
        except (KeyError, IndexError, TypeError, ValueError):
            continue  # Missing wrapper/category already has a layout diagnostic.
        validator = schema.validator.evolve(schema=category.schema)
        diagnostics.extend(_content_errors(category, validator.iter_errors(values), document))
        if not isinstance(values, list):
            continue
        for i, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            pointer = category.pointer + f"/{i}"
            try:
                identity = value_at(value, category.annotation["idField"])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if not isinstance(identity, str) or not identity:
                continue
            entity = Entity(category.kind, identity, category.name, value,
                            document.location(pointer), document.nodes[pointer].node_id)
            entities.append(entity)
            pairs.append((entity, category, document))
    mutable_index = {}
    for entity in entities:
        mutable_index.setdefault((entity.kind, entity.id), []).append(entity)
    index = {key: tuple(targets) for key, targets in mutable_index.items()}
    for (kind, identity), targets in index.items():
        if len(targets) > 1:
            diagnostics.append(Diagnostic("content.duplicate_id", "Entity ID is declared more than once.",
                targets[0].location, entity={"kind": kind, "id": identity},
                related=tuple(sorted((t.location for t in targets[1:]), key=lambda loc: (loc.path, loc.pointer)))))
    references = []
    for entity, category, document in pairs:
        references.extend(_walk_references(schema, category.schema["items"], entity.value,
                          entity.location.pointer, entity, document, index))
    history_diagnostics, acknowledgment = _history(root, schema, documents)
    diagnostics.extend(history_diagnostics)
    disabled = set(config.get("disabledRules", [])) | {
        rule for rule, setting in schema.data["x-pixorra"].get("rules", {}).items() if not setting["enabled"]}
    return ProjectSnapshot(root, schema, documents, tuple(entities), tuple(references), index,
                           sort_diagnostics(diagnostics), tuple(sorted(disabled, key=lambda r: int(r[2:]))),
                           acknowledgment, raw_files)
