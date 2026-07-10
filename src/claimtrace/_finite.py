"""Recursive finite-number checks for JSON- and YAML-derived data."""

from __future__ import annotations

import math
from typing import TypeVar


T = TypeVar("T")


def ensure_finite(value: T, path: str = "$") -> T:
    """Return *value* after rejecting NaN and infinite floats anywhere inside it."""

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"Non-finite numeric value is not allowed at {path}.")
    if isinstance(value, dict):
        for key, child in value.items():
            ensure_finite(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            ensure_finite(child, f"{path}[{index}]")
    return value
