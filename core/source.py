"""Strict JSON source trees with exact decimal values and UTF-8 byte spans.

This module only reads. Keeping tokens, trivia ranges, and source bytes here
allows the later save service to patch source without a lossy JSON round trip.
"""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Any

from .diagnostics import Diagnostic, LoadError, Location, Span


def escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def segments(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Expected a JSON pointer")
    result = pointer[1:].split("/")
    if any(re.search(r"~(?![01])", part) for part in result):
        raise ValueError("Invalid JSON pointer escape")
    return [p.replace("~1", "/").replace("~0", "~") for p in result]


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    pointer: str
    parent_id: str | None
    span: Span
    value: Any
    children: tuple["Node", ...] = ()
    key_spans: tuple[Span, ...] = ()
    trivia: tuple[Span, ...] = ()


@dataclass(frozen=True)
class SourceDocument:
    path: str
    original: bytes
    hash: str
    root: Node
    nodes: dict[str, Node]
    newline: str
    indent: str
    bom: bool
    trailing_newline: str

    def location(self, pointer: str = "") -> Location:
        node = self.nodes.get(pointer)
        return Location(self.path, pointer, node.span if node else None)

    def line_column(self, offset: int) -> tuple[int, int]:
        if not 0 <= offset <= len(self.original):
            raise ValueError("Byte offset outside document")
        prefix = self.original[:offset].decode("utf-8-sig")
        lines = re.split(r"\r\n|\r|\n", prefix)
        return len(lines), len(lines[-1]) + 1

    def token(self, pointer: str) -> bytes:
        span = self.nodes[pointer].span
        return self.original[span.start:span.end]


_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_DECODER = json.JSONDecoder()


class _ParseFailure(Exception):
    def __init__(self, message, position, code="content.json_invalid"):
        self.message, self.position, self.code = message, position, code


class _Parser:
    def __init__(self, raw: bytes, path: str):
        self.raw, self.path = raw, path
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        self.text = raw.decode("utf-8-sig")
        self.offsets = [3 if self.bom else 0]
        for char in self.text:
            self.offsets.append(self.offsets[-1] + len(char.encode("utf-8")))
        self.pos = 0
        self.nodes = {}

    def span(self, start, end):
        return Span(self.offsets[start], self.offsets[end])

    def whitespace(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def string(self):
        start = self.pos
        try:
            value, self.pos = _DECODER.raw_decode(self.text, start)
        except json.JSONDecodeError as exc:
            raise _ParseFailure("Invalid JSON string.", exc.pos) from exc
        if not isinstance(value, str) or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise _ParseFailure("Invalid Unicode scalar string.", start)
        return value, self.span(start, self.pos)

    def parse(self, pointer="", parent=None, depth=0):
        if depth > 128:
            raise _ParseFailure("JSON nesting exceeds 128 levels.", self.pos)
        self.whitespace()
        start = self.pos
        if start == len(self.text):
            raise _ParseFailure("Expected a JSON value.", start)
        char = self.text[self.pos]
        node_id = f"{len(self.path)}:{self.path}#{pointer}"
        children, key_spans, trivia = [], [], []
        if char in "[{":
            kind = "object" if char == "{" else "array"
            closing = "}" if char == "{" else "]"
            value = {} if kind == "object" else []
            self.pos += 1
            gap = self.pos
            self.whitespace()
            while self.pos < len(self.text) and self.text[self.pos] != closing:
                if kind == "object":
                    if self.text[self.pos] != '"':
                        raise _ParseFailure("Expected an object key.", self.pos)
                    key, key_span = self.string()
                    if key in value:
                        raise _ParseFailure("Duplicate JSON object key.", self.pos,
                                            "content.duplicate_key")
                    key_spans.append(key_span)
                    self.whitespace()
                    if self.pos == len(self.text) or self.text[self.pos] != ":":
                        raise _ParseFailure("Expected a colon.", self.pos)
                    self.pos += 1
                else:
                    key = str(len(value))
                child = self.parse(f"{pointer}/{escape(key)}", node_id, depth + 1)
                trivia.append(self.span(gap, self._char_offset(child.span.start)))
                children.append(child)
                if kind == "object":
                    value[key] = child.value
                else:
                    value.append(child.value)
                gap = self.pos
                self.whitespace()
                if self.pos < len(self.text) and self.text[self.pos] == ",":
                    self.pos += 1
                    self.whitespace()
                    if self.pos < len(self.text) and self.text[self.pos] == closing:
                        raise _ParseFailure("Trailing comma is not JSON.", self.pos)
                else:
                    break
            self.whitespace()
            if self.pos == len(self.text) or self.text[self.pos] != closing:
                raise _ParseFailure("Expected a closing delimiter.", self.pos)
            trivia.append(self.span(gap, self.pos))
            self.pos += 1
        elif char == '"':
            kind = "string"
            value, _ = self.string()
        elif char in "-0123456789":
            match = _NUMBER.match(self.text, self.pos)
            if not match:
                raise _ParseFailure("Invalid JSON number.", self.pos)
            literal = match.group()
            coefficient, _, exponent = literal.lower().partition("e")
            digits = coefficient.replace("-", "").replace(".", "")
            significant_exponent = exponent.lstrip("+-0") or "0"
            if len(digits) > 1024 or (exponent and
                    (len(significant_exponent) > 4 or int(significant_exponent) > 6144)):
                raise _ParseFailure("Number exceeds portable limits.", self.pos,
                                    "content.number_limit")
            value, kind = Decimal(literal), "number"
            self.pos = match.end()
        else:
            kind, value = None, None
            for literal, scalar, scalar_kind in (
                    ("true", True, "boolean"), ("false", False, "boolean"),
                    ("null", None, "null")):
                if self.text.startswith(literal, self.pos):
                    value, kind = scalar, scalar_kind
                    self.pos += len(literal)
                    break
            if kind is None:
                raise _ParseFailure("Expected a JSON value.", self.pos)
        node = Node(node_id, kind, pointer, parent, self.span(start, self.pos),
                    value, tuple(children), tuple(key_spans), tuple(trivia))
        self.nodes[pointer] = node
        return node

    def _char_offset(self, byte_offset):
        # Each child begins at the parser's immediately preceding offset.
        # Binary search avoids rescanning prefixes of large source documents.
        from bisect import bisect_left
        return bisect_left(self.offsets, byte_offset)


def parse_document(raw: bytes, path: str) -> SourceDocument:
    """Parse without normalizing a single source byte; failures retain no writes."""
    try:
        parser = _Parser(raw, path)
        root = parser.parse()
        parser.whitespace()
        if parser.pos != len(parser.text):
            raise _ParseFailure("Unexpected data after JSON value.", parser.pos)
    except UnicodeDecodeError as exc:
        raise LoadError([Diagnostic("content.encoding", "Expected UTF-8 JSON.",
                                   Location(path, span=Span(exc.start, exc.end)))]) from exc
    except _ParseFailure as exc:
        offset = parser.offsets[min(exc.position, len(parser.text))]
        raise LoadError([Diagnostic(exc.code, exc.message,
                                   Location(path, span=Span(offset, offset)))]) from exc
    newline = re.search(r"\r\n|\r|\n", parser.text)
    indent = re.search(r"(?:\r\n|\r|\n)([ \t]+)\S", parser.text)
    trailing = re.search(r"(\r\n|\r|\n)$", parser.text)
    return SourceDocument(path, raw, sha256(raw).hexdigest(), root, parser.nodes,
                          newline.group() if newline else "\n",
                          indent.group(1) if indent else "  ", parser.bom,
                          trailing.group() if trailing else "")
