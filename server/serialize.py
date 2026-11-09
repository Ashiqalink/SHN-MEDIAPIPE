"""JSON helpers for the server.

Two problems handled here:

- ``Decimal``: core models hold numbers as ``int``/``Decimal`` (never float).
  Responses must serialize Decimals as JSON numbers; Decimal("1.6") -> 1.6,
  Decimal("20") -> 20.
- Requests: JSON bodies are parsed with ``parse_float=Decimal`` so a client
  sending ``1.6`` produces ``Decimal("1.6")`` instead of a float, which
  ``edit_document`` would refuse.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def decimal_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=decimal_default, ensure_ascii=False, indent=None)


def json_bytes(obj: Any) -> bytes:
    return dumps(obj).encode("utf-8")


def loads(text: str | bytes) -> Any:
    """Parse JSON body text into a model with int/Decimal numbers."""
    return json.loads(text, parse_float=Decimal)
