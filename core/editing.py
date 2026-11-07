"""Minimal byte patches with strict reparsing and independent verification."""

from dataclasses import dataclass
from decimal import Decimal
import json
import re

from .diagnostics import LoadError
from .source import escape, parse_document


class VerificationError(ValueError):
    pass


def ordered_equal(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return list(left) == list(right) and all(ordered_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(ordered_equal(a, b) for a, b in zip(left, right))
    numeric = lambda v: isinstance(v, (int, Decimal)) and not isinstance(v, bool)
    if numeric(left) and numeric(right):
        return left == right
    return type(left) is type(right) and left == right


def scalar(value):
    if value is None:
        return b"null"
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, (int, Decimal)):
        number = Decimal(value)
        if not number.is_finite() or len(number.as_tuple().digits) > 1024 or abs(number.as_tuple().exponent) > 6144:
            raise ValueError("Number exceeds portable limits")
        text = format(number, "f") if number else "0"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text.encode("ascii")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).encode("utf-8")
    raise ValueError("Use JSON values with int or Decimal numbers, never binary floats")


@dataclass(frozen=True)
class Patch:
    pointer: str
    start: int
    end: int
    replacement: bytes


@dataclass(frozen=True)
class EditedDocument:
    original: object
    candidate: bytes
    patches: tuple[Patch, ...]
    # (original pointer, candidate pointer) for unchanged nodes within changed containers.
    retained: tuple[tuple[str, str], ...]


def _style(document, node):
    """Prefer a container's immediate child indentation over global style."""
    raw = document.original
    containers = [node] + sorted((n for n in document.nodes.values()
                           if n.kind in ("array", "object") and n != node), key=lambda n: n.span.start)
    for container in containers:
        if container.kind not in ("array", "object") or not container.children:
            continue
        start = container.span.start
        first = container.key_spans[0].start if container.key_spans else container.children[0].span.start
        prefix = raw[start:first]
        match = re.search(rb"(\r\n|\n|\r)([ \t]*)[^\r\n]*$", prefix)
        if match:
            end = container.span.end - 1
            closing_start = max(raw.rfind(b"\n", start, end), raw.rfind(b"\r", start, end)) + 1
            closing_prefix = raw[closing_start:end]
            base = closing_prefix if closing_prefix.strip(b" \t") == b"" else b""
            indent = match[2][len(base):] if match[2].startswith(base) else match[2]
            return match[1], indent or b"  "
    return b"\n", b"  "


def _render(document, value, node, pointer, retained, newline, indent, base):
    if node is not None and ordered_equal(node.value, value):
        retained.append((node.pointer, pointer))
        return document.token(node.pointer)
    if not isinstance(value, (dict, list)):
        return scalar(value)
    if isinstance(value, dict) and any(not isinstance(k, str) for k in value):
        raise ValueError("Object keys must be strings")
    opening, closing = (b"{", b"}") if isinstance(value, dict) else (b"[", b"]")
    entries = list(value.items()) if isinstance(value, dict) else list(enumerate(value))
    if not entries:
        return opening + closing
    if node is not None:
        newline, indent = _style(document, node)
        if node.kind in ("object", "array"):
            closing_offset = node.span.end - 1
            line = max(document.original.rfind(b"\n", node.span.start, closing_offset),
                       document.original.rfind(b"\r", node.span.start, closing_offset)) + 1
            closing_prefix = document.original[line:closing_offset]
            if closing_prefix.strip(b" \t") == b"":
                base = closing_prefix
    old = {}
    if node is not None and node.kind == ("object" if isinstance(value, dict) else "array"):
        old = dict(zip(node.value if isinstance(value, dict) else range(len(node.children)), node.children))
    parts, used = [], set()
    for key, child in entries:
        previous = old.get(key)
        # In shifted arrays retain complete unchanged children, including their number spellings.
        if isinstance(value, list):
            previous = next((n for n in old.values() if n.pointer not in used
                             and ordered_equal(n.value, child)), previous)
        if previous is not None and previous.pointer in used:
            previous = None
        if previous is not None and (isinstance(value, dict) or ordered_equal(previous.value, child)):
            used.add(previous.pointer)
        child_pointer = pointer + "/" + escape(str(key))
        token = _render(document, child, previous, child_pointer, retained,
                        newline, indent, base + indent)
        if isinstance(value, dict):
            key_token = scalar(key)
            if node is not None and key in old:
                key_index = list(node.value).index(key)
                span = node.key_spans[key_index]
                key_token = document.original[span.start:span.end]
            token = key_token + b": " + token
        parts.append(base + indent + token)
    return opening + newline + (b"," + newline).join(parts) + newline + base + closing


def edit_document(document, value):
    """Freeze a target ordered JSON model into verified source-span patches."""
    patches, retained = [], []

    def visit(node, desired):
        if ordered_equal(node.value, desired):
            return
        same_object = isinstance(desired, dict) and node.kind == "object" and list(node.value) == list(desired)
        same_array = isinstance(desired, list) and node.kind == "array" and len(node.children) == len(desired)
        if same_object or same_array:
            values = desired.values() if same_object else desired
            for child, target in zip(node.children, values):
                visit(child, target)
            return
        raw = document.original
        line = max(raw.rfind(b"\n", 0, node.span.start), raw.rfind(b"\r", 0, node.span.start)) + 1
        base = re.match(rb"[ \t]*", raw[line:node.span.start]).group()
        newline, indent = _style(document, node)
        replacement = _render(document, desired, node, node.pointer, retained, newline, indent, base)
        patches.append(Patch(node.pointer, node.span.start, node.span.end, replacement))

    visit(document.root, value)
    chunks, offset = [], 0
    for item in patches:
        chunks.extend((document.original[offset:item.start], item.replacement))
        offset = item.end
    candidate = b"".join(chunks) + document.original[offset:]
    result = EditedDocument(document, candidate, tuple(patches), tuple(retained))
    verify_edit(result, value)
    return result


def verify_edit(edit, desired):
    """Check model/order, patch ownership, offset intervals and retained raw tokens."""
    try:
        parsed = parse_document(edit.candidate, edit.original.path)
    except LoadError as exc:
        raise VerificationError("Candidate is not strict JSON") from exc
    if not ordered_equal(parsed.root.value, desired):
        raise VerificationError("Candidate differs from the planned ordered model")
    old_offset = new_offset = 0
    for item in edit.patches:
        node = edit.original.nodes[item.pointer]
        if (item.start != node.span.start or item.end != node.span.end
                or item.start < old_offset):
            raise VerificationError("Invalid patch ownership or overlap")
        target = parsed.nodes[item.pointer]
        if ((node.kind == target.kind == "object" and list(node.value) == list(target.value))
                or (node.kind == target.kind == "array" and len(node.children) == len(target.children))):
            raise VerificationError("Container patch owns more than the required child tokens")
        if node.kind == target.kind == "object":
            before_keys = dict(zip(node.value, node.key_spans))
            after_keys = dict(zip(target.value, target.key_spans))
            for key in before_keys.keys() & after_keys.keys():
                before, after = before_keys[key], after_keys[key]
                if edit.original.original[before.start:before.end] != edit.candidate[after.start:after.end]:
                    raise VerificationError("Unchanged key token differs")
        length = item.start - old_offset
        if edit.original.original[old_offset:item.start] != edit.candidate[new_offset:new_offset + length]:
            raise VerificationError("Untouched interval differs")
        new_offset += length
        if edit.candidate[new_offset:new_offset + len(item.replacement)] != item.replacement:
            raise VerificationError("Replacement differs")
        new_offset += len(item.replacement)
        old_offset = item.end
    if edit.original.original[old_offset:] != edit.candidate[new_offset:]:
        raise VerificationError("Untouched suffix differs")
    for before, after in edit.retained:
        if edit.original.token(before) != parsed.token(after):
            raise VerificationError("Unchanged child token differs")
    return parsed


def new_document(value, path):
    empty = parse_document(b"null\n", path)
    return edit_document(empty, value).candidate
