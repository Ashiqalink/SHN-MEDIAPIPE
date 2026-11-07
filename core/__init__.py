"""Pixorra's standalone project, lint and verified-save core (Python 3.11+)."""

from .diagnostics import Diagnostic, LoadError, Location, Span
from .project import Entity, ProjectSnapshot, ReferenceUse, load_project
from .source import SourceDocument, parse_document
from .editing import edit_document
from .lint import LintReport, lint_project
from .saving import SaveError, SavePlan, SaveResult, SaveSession

__all__ = ["Diagnostic", "Entity", "LoadError", "Location", "ProjectSnapshot",
           "ReferenceUse", "SourceDocument", "Span", "load_project", "parse_document",
           "edit_document", "LintReport", "lint_project", "SaveError", "SavePlan",
           "SaveResult", "SaveSession"]
