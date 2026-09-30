"""Reject non-JSON numeric source values without silently rewriting evidence."""

from __future__ import annotations

import math
from typing import Any


def require_finite_source(value: Any) -> None:
    """Reject non-finite floats and cyclic source containers before projection."""
    active: set[int] = set()

    def visit(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Authored source contains a non-finite number")
        if isinstance(item, (dict, list, tuple)):
            identity = id(item)
            if identity in active:
                raise ValueError("Authored source contains a cyclic container")
            active.add(identity)
            if isinstance(item, dict):
                for key, child in item.items():
                    visit(key)
                    visit(child)
            else:
                for child in item:
                    visit(child)
            active.remove(identity)

    visit(value)
