"""Portable diagnostics shared by headless loaders and future callers."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass(frozen=True)
class Location:
    path: str
    pointer: str = ""
    span: Span | None = None


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    location: Location
    severity: str = "error"
    outcome: str = "fail"
    rule: str | None = None
    entity: dict[str, str] | None = None
    related: tuple[Location, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["related"] = list(result["related"])
        return result


def sort_diagnostics(items):
    return tuple(sorted(items, key=lambda d: (
        d.location.path, d.location.pointer,
        int(d.rule[2:]) if d.rule else 0, d.code, d.message,
    )))


class LoadError(Exception):
    """A schema/configuration could not be accepted for editable loading."""

    def __init__(self, diagnostics):
        self.diagnostics = sort_diagnostics(diagnostics)
        super().__init__("; ".join(d.code for d in self.diagnostics))
