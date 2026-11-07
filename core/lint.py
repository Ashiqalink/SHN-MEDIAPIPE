"""Schema-driven MVP lint; static uncertainty stays separate from failures."""

from dataclasses import dataclass
from decimal import Decimal

from .diagnostics import Diagnostic, sort_diagnostics
from .project import value_at
from .source import escape


@dataclass(frozen=True)
class LintReport:
    diagnostics: tuple[Diagnostic, ...]
    disabled_rules: tuple[str, ...]
    schema: dict

    @property
    def counts(self):
        return {key: sum(d.outcome == "unknown" if key == "unknowns" else
                         d.outcome != "unknown" and d.severity == severity
                         for d in self.diagnostics)
                for key, severity in (("errors", "error"), ("warnings", "warning"),
                                      ("hints", "hint"), ("infos", "info"), ("unknowns", None))}

    def to_dict(self):
        return {"reportVersion": 1, "schema": self.schema,
                "disabledRules": list(self.disabled_rules), "counts": self.counts,
                "diagnostics": [d.to_dict() for d in self.diagnostics]}


def _fields(schema, definition, value, pointer=""):
    definition = schema.resolve(definition)
    yield definition.get("x-pixorra", {}), value, pointer
    if isinstance(value, dict) and definition.get("type") == "object":
        for key, child in value.items():
            if key in definition["properties"]:
                yield from _fields(schema, definition["properties"][key], child,
                                   pointer + "/" + escape(key))
    elif isinstance(value, list) and definition.get("type") == "array":
        for i, child in enumerate(value):
            yield from _fields(schema, definition["items"], child, pointer + f"/{i}")


def lint_project(project):
    """Report L-1/L-3/L-5/L-14 with locations, counts and disabled rules.

    Structural errors remain in ProjectSnapshot even when L-14 is disabled.
    The lint report honors disabling independently of save validation.
    """
    diagnostics = [d for d in project.diagnostics if d.rule == "L-14"]
    schema = project.schema
    categories = {c.name: c for c in schema.categories}
    for ref in project.references:
        if ref.kind == "materials" and ref.resolution == "missing":
            diagnostics.append(Diagnostic("material.unknown", "Unknown material ID.",
                ref.location, rule="L-1", entity={"kind": ref.entity.kind, "id": ref.entity.id},
                details={"value": ref.value}))
    used = {ref.value for ref in project.references if ref.kind == "materials"
            and ref.entity.kind in ("reactions", "spawn_rules")}
    for entity in project.entities:
        category = categories[entity.category]
        document = project.documents[entity.location.path]
        fields = list(_fields(schema, category.schema["items"], entity.value))
        identity = {"kind": entity.kind, "id": entity.id}
        for annotation, value, pointer in fields:
            spec = annotation.get("paletteIndex")
            if spec is None or isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                continue
            if value < 0 or (isinstance(value, Decimal) and value != value.to_integral_value()):
                continue  # A structural range/type error already identifies invalid indices.
            try:
                palette_id = value_at(entity.value, spec["paletteField"])
                palettes = project.resolve("palettes", palette_id)
                if len(palettes) != 1:
                    continue  # No L-3 conclusion without a uniquely resolved palette.
                palette = palettes[0]
                colors_pointer = categories[palette.category].annotation["roles"]["colors"]
                colors = value_at(palette.value, colors_pointer)
                if not isinstance(colors, list):
                    continue
            except (KeyError, TypeError, IndexError, ValueError):
                continue
            if value >= len(colors):
                diagnostics.append(Diagnostic("palette.index_out_of_range",
                    "Palette index is outside the palette.",
                    document.location(entity.location.pointer + pointer), rule="L-3",
                    entity=identity, related=(palette.location,),
                    details={"index": str(value), "length": len(colors)}))
        if entity.kind == "materials" and entity.id not in used:
            external = category.annotation.get("external", False)
            for annotation, value, _ in fields:
                if annotation.get("externalMarker") == "external" and isinstance(value, bool):
                    external = value
            diagnostics.append(Diagnostic(
                "material.external_usage" if external else "material.orphan",
                "Game code may use this material." if external else
                "Material is never produced, spawned, or used in a reaction.",
                entity.location, severity="warning", outcome="unknown" if external else "fail",
                rule="L-5", entity=identity,
                details={"reason": "external"} if external else {}))
    return LintReport(sort_diagnostics(d for d in diagnostics if d.rule not in project.disabled_rules),
                      project.disabled_rules, dict(schema.identity))
