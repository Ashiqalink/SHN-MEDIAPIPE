"""Closed JSON Schema profile and game-specific semantic binding validation."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlparse

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import SchemaError

from .diagnostics import Diagnostic, LoadError, Location
from .source import SourceDocument, escape, parse_document, segments


CONTRACT_VERSION = "1.0.0"
RULE_IDS = frozenset(f"L-{i}" for i in range(1, 15))
KINDS = frozenset(("materials", "reactions", "spawn_rules", "regions",
                   "palettes", "flags", "quests", "dialogue"))
MARKERS = frozenset(("external", "spawn_external", "external_writes",
                     "external_transitions"))
KEYWORDS = frozenset(("$schema", "$id", "$defs", "$ref", "$comment", "title",
    "description", "default", "examples", "type", "properties", "required",
    "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
    "enum", "const", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minLength", "maxLength", "x-pixorra"))
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")


def local_ref_name(ref):
    if not isinstance(ref, str) or not ref.startswith("#/") or re.search(r"%(?![0-9a-fA-F]{2})", ref):
        raise ValueError("Only local #/$defs/<name> references are supported")
    parts = segments(unquote(ref[1:], errors="strict"))
    if len(parts) != 2 or parts[0] != "$defs":
        raise ValueError("Only local #/$defs/<name> references are supported")
    return parts[1]


def _integer(checker, value):
    return (isinstance(value, int) and not isinstance(value, bool)) or (
        isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value())


Validator = validators.extend(Draft202012Validator, type_checker=
    Draft202012Validator.TYPE_CHECKER.redefine("integer", _integer))


def normalize_schema(value):
    """Convert integral schema constants to ints without rounding any decimals."""
    if (isinstance(value, Decimal) and value.adjusted() < 1024
            and value == value.to_integral_value()):
        return int(value)
    if isinstance(value, dict):
        return {key: normalize_schema(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_schema(item) for item in value]
    return value


def safe_path(root: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or ":" in relative or "\x00" in relative):
        raise ValueError("Expected a project-relative path using forward slashes")
    pure = PurePosixPath(relative)
    if (pure.is_absolute() or any(p in ("", ".", "..") for p in relative.split("/"))):
        raise ValueError("Path must stay within the project")
    resolved = root.joinpath(*pure.parts).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Path resolves outside the project")
    return resolved


@dataclass(frozen=True)
class Category:
    name: str
    kind: str
    schema: dict
    annotation: dict
    path: str
    pointer: str


@dataclass(frozen=True)
class GameSchema:
    document: SourceDocument
    data: dict
    categories: tuple[Category, ...]
    validator: object

    @property
    def identity(self):
        return {"id": self.data["$id"],
                "version": self.data["x-pixorra"]["schemaVersion"],
                "hash": self.document.hash}

    def resolve(self, schema):
        while "$ref" in schema:
            name = local_ref_name(schema["$ref"])
            schema = self.data["$defs"][name]
        return schema


class _SchemaCheck:
    def __init__(self, document, root):
        self.document, self.root = document, root
        self.data = normalize_schema(document.root.value)
        self.errors = []

    def error(self, pointer, message, code="schema.invalid"):
        self.errors.append(Diagnostic(code, message, self.document.location(pointer)))

    def closed(self, value, allowed, pointer, required=()):
        if not isinstance(value, dict):
            self.error(pointer, "Expected an annotation object.")
            return False
        for key in value.keys() - set(allowed):
            self.error(f"{pointer}/{escape(key)}", "Unsupported annotation key.",
                       "schema.unsupported_keyword")
        for key in set(required) - value.keys():
            self.error(pointer, f"Missing required annotation: {key}.")
        return True

    def resolve(self, node, active=()):
        if not isinstance(node, dict):
            raise ValueError("Schema must be an object")
        if "$ref" not in node:
            return node
        ref = node["$ref"]
        name = local_ref_name(ref)
        if ref in active:
            raise ValueError("Cyclic schema references are forbidden")
        definitions = self.data.get("$defs", {})
        if name not in definitions:
            raise ValueError("Unresolved local schema reference")
        return self.resolve(definitions[name], (*active, ref))

    def field(self, node, pointer, required=False):
        for part in segments(pointer):
            node = self.resolve(node)
            if part == "*" and node.get("type") == "array":
                node = node["items"]
            elif node.get("type") == "object" and part in node.get("properties", {}):
                if required and part not in node.get("required", []):
                    raise ValueError("Identity fields must be required")
                node = node["properties"][part]
            else:
                raise ValueError("Role pointer does not resolve through declared fields")
        return self.resolve(node)

    def profile(self, node, pointer="", active=()):
        if not isinstance(node, dict):
            self.error(pointer, "Boolean schemas are not supported.")
            return
        for key in node.keys() - KEYWORDS:
            self.error(f"{pointer}/{escape(key)}", "Unsupported schema keyword.",
                       "schema.unsupported_keyword")
        if pointer and ("$id" in node or "$schema" in node):
            self.error(pointer, "$id and $schema are allowed only at the root.")
        if "$ref" in node:
            if len(node) != 1:
                self.error(pointer, "$ref cannot have sibling keywords.")
            try:
                ref = node["$ref"]
                target = self.resolve(node, active)
                # Walk the target too: cycles may pass through object/array fields.
                self.profile(target, pointer, (*active, ref))
            except (ValueError, KeyError, TypeError) as exc:
                self.error(pointer, str(exc), "schema.reference_invalid")
            return
        kind = node.get("type")
        if kind not in ("object", "array", "string", "number", "integer", "boolean", "null"):
            self.error(pointer, "Declare a single supported JSON type.")
        if kind == "object":
            if (not isinstance(node.get("properties"), dict)
                    or "required" not in node or node.get("additionalProperties") is not False):
                self.error(pointer, "Objects require properties, required, and additionalProperties: false.")
            else:
                if not set(node["required"]).issubset(node["properties"]):
                    self.error(pointer, "A required field is undeclared.")
                for name, child in node["properties"].items():
                    self.profile(child, f"{pointer}/properties/{escape(name)}", active)
        if kind == "array":
            if "items" not in node:
                self.error(pointer, "Array items must be declared.")
            else:
                self.profile(node["items"], f"{pointer}/items", active)
        for name, child in node.get("$defs", {}).items():
            self.profile(child, f"{pointer}/$defs/{escape(name)}", active)
        for low, high in (("minLength", "maxLength"), ("minItems", "maxItems"),
                          ("minimum", "maximum")):
            if low in node and high in node and node[low] > node[high]:
                self.error(pointer, "Contradictory schema bounds.")
        lows = [(node[k], k.startswith("exclusive")) for k in ("minimum", "exclusiveMinimum") if k in node]
        highs = [(node[k], k.startswith("exclusive")) for k in ("maximum", "exclusiveMaximum") if k in node]
        if any(a > b or (a == b and (ae or be)) for a, ae in lows for b, be in highs):
            self.error(pointer, "Contradictory numeric bounds.")
        ann = node.get("x-pixorra")
        is_category = pointer.startswith("/properties/") and pointer.count("/") == 2
        if ann is not None and pointer and not is_category:
            self.field_annotation(node, ann, pointer + "/x-pixorra")

    def field_annotation(self, node, ann, pointer):
        allowed = ("reference", "paletteIndex", "expression", "sprite", "externalMarker")
        if not self.closed(ann, allowed, pointer):
            return
        if len(ann) != 1:
            self.error(pointer, "A field requires exactly one semantic annotation.")
        kind = node.get("type")
        if "reference" in ann:
            ref = ann["reference"]
            if (self.closed(ref, ("kind",), pointer + "/reference", ("kind",))
                    and (kind != "string" or ref.get("kind") not in KINDS)):
                self.error(pointer, "References require string fields and a declared kind.")
        if "paletteIndex" in ann:
            config = ann["paletteIndex"]
            if self.closed(config, ("paletteField",), pointer + "/paletteIndex", ("paletteField",)):
                if kind != "integer" or node.get("minimum", -1) < 0:
                    self.error(pointer, "Palette indices require nonnegative integers.")
                try:
                    segments(config.get("paletteField"))
                except (ValueError, TypeError):
                    self.error(pointer, "Invalid palette field pointer.")
        if "expression" in ann and (kind != "string" or ann["expression"] is not True):
            self.error(pointer, "Expression annotations require a string and true.")
        if "sprite" in ann:
            config = ann["sprite"]
            if self.closed(config, ("generated",), pointer + "/sprite", ("generated",)):
                if kind != "string" or not isinstance(config.get("generated"), bool):
                    self.error(pointer, "Sprite annotations require a string and boolean generated.")
        if "externalMarker" in ann and (kind != "boolean" or ann["externalMarker"] not in MARKERS):
            self.error(pointer, "Invalid external marker annotation.")

    def category(self, name, node, binding):
        pointer = f"/properties/{escape(name)}/x-pixorra"
        ann = node.get("x-pixorra")
        allowed = {"kind", "idField", "labelField", "roles", "max_size", *MARKERS}
        if not self.closed(ann, allowed, pointer, ("kind", "idField", "roles")):
            return None
        kind = ann.get("kind")
        if node.get("type") != "array" or kind not in KINDS:
            self.error(pointer, "Categories must be arrays with a supported kind.")
            return None
        try:
            item = self.resolve(node["items"])
            if item.get("type") != "object":
                raise ValueError("Category items must be objects")
            if "*" in segments(ann.get("idField")):
                raise ValueError("Identity pointers cannot select array elements")
            identity = self.field(item, ann.get("idField"), required=True)
            if identity.get("type") != "string" or identity.get("minLength", 0) < 1:
                raise ValueError("Identity must be a required nonempty string")
            if "labelField" in ann and self.field(item, ann["labelField"]).get("type") != "string":
                raise ValueError("Label must be a string field")
            for marker in MARKERS & ann.keys():
                if not isinstance(ann[marker], bool):
                    raise ValueError("External defaults must be boolean")
            if kind == "palettes":
                size = ann.get("max_size")
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    raise ValueError("Palettes require a nonnegative max_size")
            elif "max_size" in ann:
                raise ValueError("Only palettes declare max_size")
            self.roles(kind, item, ann, pointer)
            self.entity_fields(item, item, pointer)
        except (ValueError, KeyError, TypeError) as exc:
            self.error(pointer, str(exc), "schema.binding_invalid")
        if not self.closed(binding, ("path", "pointer"), pointer, ("path", "pointer")):
            return None
        try:
            safe_path(self.root, binding.get("path"))
            parts = segments(binding.get("pointer"))
            if any(part.isdecimal() or part == "*" for part in parts):
                raise ValueError("Binding prefixes must be object keys, not indices")
            if binding["path"].split("/")[0].casefold() == ".pixorra":
                raise ValueError("Game bindings cannot target editor metadata")
        except (ValueError, TypeError) as exc:
            self.error(pointer, str(exc), "schema.binding_invalid")
            return None
        return Category(name, kind, node, ann, binding["path"], binding["pointer"])

    def roles(self, kind, item, ann, pointer):
        # Role types are checked here; concrete semantic rules arrive in later phases.
        definitions = {
            "materials": ({}, {"properties": "object", "sprite": "string", "paletteIndex": "integer"}),
            "palettes": ({"colors": "array"}, {}),
            "reactions": ({"inputs": "array", "outputs": "array"}, {"condition": "string", "exitCondition": "string", "priority": "integer"}),
            "spawn_rules": ({"material": "string"}, {"region": "string", "condition": "string", "weight": "number"}),
            "regions": ({"min": "array", "max": "array", "exclusive": "boolean"}, {"materials": "array"}),
            "flags": ({"initial": "boolean"}, {}),
            "quests": ({"stages": "array", "initialStage": "string", "stageId": "string", "terminal": "boolean", "transitions": "array", "target": "string"}, {"requiredFlags": "array", "rewards": "array", "region": "string", "condition": "string", "setFlags": "array", "priority": "integer"}),
            "dialogue": ({"lines": "array"}, {"choices": "array"}),
        }
        required, optional = definitions[kind]
        roles = ann.get("roles")
        if not self.closed(roles, required.keys() | optional.keys(), pointer + "/roles", required):
            return
        scopes = {key: item for key in roles}
        if kind == "quests" and "stages" in roles:
            stage = self.resolve(self.field(item, roles["stages"])["items"])
            for key in ("stageId", "terminal", "transitions"):
                scopes[key] = stage
            if "transitions" in roles:
                transition = self.resolve(self.field(stage, roles["transitions"])["items"])
                for key in ("target", "condition", "setFlags", "priority"):
                    scopes[key] = transition
        for role, path in roles.items():
            if role not in required and role not in optional:
                continue
            field = self.field(scopes.get(role, item), path)
            expected = required.get(role, optional.get(role))
            if field.get("type") != expected:
                raise ValueError(f"Role {role} must point to {expected}")
            if role in ("condition", "exitCondition"):
                if field.get("x-pixorra", {}).get("expression") is not True:
                    raise ValueError("Condition roles require expression annotations")
            if role == "sprite" and "sprite" not in field.get("x-pixorra", {}):
                raise ValueError("Sprite roles require sprite annotations")
            if role == "paletteIndex" and "paletteIndex" not in field.get("x-pixorra", {}):
                raise ValueError("Palette index role requires paletteIndex annotation")
            target = {"inputs": "materials", "outputs": "materials", "material": "materials",
                      "materials": "materials", "rewards": "materials", "region": "regions",
                      "requiredFlags": "flags"}.get(role)
            if target:
                ref = self.resolve(field["items"]) if expected == "array" else field
                if ref.get("x-pixorra", {}).get("reference") != {"kind": target}:
                    raise ValueError(f"Role {role} requires {target} references")
            if role in ("colors", "lines") and self.resolve(field["items"]).get("type") != "string":
                raise ValueError(f"Role {role} requires string items")
            if role == "inputs" and field.get("minItems", 0) < 1:
                raise ValueError("Reaction inputs must be nonempty")
            if role in ("min", "max") and (field.get("minItems") != 3 or field.get("maxItems") != 3
                    or self.resolve(field["items"]).get("type") != "number"):
                raise ValueError("Region bounds must have exactly three numbers")
            if role == "weight" and field.get("minimum", -1) < 0:
                raise ValueError("Spawn weights must be nonnegative")

    def entity_fields(self, node, entity, pointer):
        node = self.resolve(node)
        ann = node.get("x-pixorra", {})
        if "paletteIndex" in ann:
            palette = self.field(entity, ann["paletteIndex"]["paletteField"])
            if palette.get("x-pixorra", {}).get("reference") != {"kind": "palettes"}:
                raise ValueError("Palette index must name a palette reference field")
        if node.get("type") == "object":
            for child in node["properties"].values():
                self.entity_fields(child, entity, pointer)
        elif node.get("type") == "array":
            self.entity_fields(node["items"], entity, pointer)

    def run(self):
        data = self.data
        if not isinstance(data, dict):
            raise LoadError([Diagnostic("schema.invalid", "Schema root must be an object.", self.document.location())])
        try:
            Draft202012Validator.check_schema(data)
        except SchemaError as exc:
            path = "/" + "/".join(escape(str(p)) for p in exc.path) if exc.path else ""
            raise LoadError([Diagnostic("schema.invalid", "Schema fails the Draft 2020-12 metaschema.", self.document.location(path))]) from exc
        if data.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            self.error("/$schema", "Use JSON Schema Draft 2020-12.")
        if not isinstance(data.get("$id"), str) or not urlparse(data.get("$id", "")).scheme:
            self.error("/$id", "Declare a stable URI schema identity.")
        self.profile(data)
        # Stop here: later binding checks rely on a valid, finite schema tree.
        if self.errors:
            raise LoadError(self.errors)
        ann = data.get("x-pixorra")
        if not self.closed(ann, ("contractVersion", "schemaVersion", "bindings", "rules", "expressionContext"),
                           "/x-pixorra", ("contractVersion", "schemaVersion", "bindings")):
            raise LoadError(self.errors)
        if ann.get("contractVersion") != CONTRACT_VERSION:
            self.error("/x-pixorra/contractVersion", "Unsupported Pixorra contract version.", "schema.contract_unsupported")
        if not isinstance(ann.get("schemaVersion"), str) or not VERSION.fullmatch(ann["schemaVersion"]):
            self.error("/x-pixorra/schemaVersion", "Expected a canonical MAJOR.MINOR.PATCH version.")
        properties = data.get("properties", {})
        if data.get("type") != "object" or set(data.get("required", [])) != properties.keys():
            self.error("", "The root must require every declared category.")
        bindings = ann.get("bindings")
        if not isinstance(bindings, dict) or bindings.keys() != properties.keys():
            self.error("/x-pixorra/bindings", "Bindings must match enabled categories exactly.")
            raise LoadError(self.errors)
        categories = [self.category(name, node, bindings[name]) for name, node in properties.items()]
        categories = [c for c in categories if c is not None]
        seen_paths = {}
        for i, category in enumerate(categories):
            folded = category.path.casefold()
            if folded in seen_paths and seen_paths[folded] != category.path:
                self.error("/x-pixorra/bindings", "Case-colliding paths are not portable.", "schema.binding_invalid")
            seen_paths[folded] = category.path
            for other in categories[:i]:
                a, b = segments(category.pointer), segments(other.pointer)
                if folded == other.path.casefold() and (a[:len(b)] == b or b[:len(a)] == a):
                    self.error("/x-pixorra/bindings", "File bindings overlap.", "schema.binding_invalid")
        rules = ann.get("rules", {})
        if self.closed(rules, RULE_IDS, "/x-pixorra/rules"):
            for rule, config in rules.items():
                if self.closed(config, ("enabled",), "/x-pixorra/rules/" + rule, ("enabled",)):
                    if not isinstance(config.get("enabled"), bool):
                        self.error("/x-pixorra/rules/" + rule, "Rule enabled must be boolean.")
        context = ann.get("expressionContext", {})
        if not isinstance(context, dict):
            self.error("/x-pixorra/expressionContext", "Expected a context binding object.")
        else:
            for name, config in context.items():
                at = "/x-pixorra/expressionContext/" + escape(name)
                if not re.fullmatch(r"[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*", name) or name.split(".")[0] in ("flag", "random"):
                    self.error(at, "Invalid expression context name.")
                if self.closed(config, ("type", "source", "pointer"), at, ("type", "source", "pointer")):
                    if config.get("type") not in ("number", "string", "boolean") or config.get("source") not in ("state", "subject", "neighbor"):
                        self.error(at, "Invalid expression context type or source.")
                    try:
                        segments(config.get("pointer"))
                    except (ValueError, TypeError):
                        self.error(at, "Invalid expression context pointer.")
        if self.errors:
            raise LoadError(self.errors)
        validator = Validator(data)
        self.validate_examples(data, validator)
        if self.errors:
            raise LoadError(self.errors)
        return GameSchema(self.document, data, tuple(categories), validator)

    def validate_examples(self, node, validator, pointer=""):
        if "$ref" in node:
            return
        local = validator.evolve(schema=node)
        values = ([node["default"]] if "default" in node else []) + node.get("examples", [])
        if any(not local.is_valid(value) for value in values):
            self.error(pointer, "Defaults and examples must satisfy their schema.")
        for key in ("properties", "$defs"):
            for name, child in node.get(key, {}).items():
                self.validate_examples(child, validator, f"{pointer}/{key}/{escape(name)}")
        if "items" in node:
            self.validate_examples(node["items"], validator, pointer + "/items")


def load_schema(path: Path, project_root: Path) -> GameSchema:
    try:
        relative = path.relative_to(project_root).as_posix()
        document = parse_document(path.read_bytes(), relative)
    except OSError as exc:
        raise LoadError([Diagnostic("schema.read_failed", "Cannot read the selected schema.", Location(path.name))]) from exc
    try:
        return _SchemaCheck(document, project_root).run()
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError) as exc:
        # Malformed extension shapes must become diagnostics, never host tracebacks.
        # Explicit LoadError diagnostics from normal checks pass through unchanged.
        raise LoadError([Diagnostic("schema.invalid", "Invalid schema annotation structure.", document.location())]) from exc
