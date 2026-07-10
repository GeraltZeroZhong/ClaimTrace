"""Small YAML reader/writer used when PyYAML is unavailable.

The fallback intentionally supports only the answer-template subset used by ClaimTrace:
mappings, lists, strings, booleans, numbers and null-like values.
"""

from __future__ import annotations

import json
from typing import Any


def loads(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        lines = _prepare_lines(text)
        value, index = _parse_block(lines, 0, 0)
        if index < len(lines):
            raise ValueError(f"Could not parse YAML near line {index + 1}")
        return value


def dumps(data: Any) -> str:
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
    except Exception:
        return _dump_value(data, 0).rstrip() + "\n"


def load_path(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return loads(handle.read())


def dump_path(data: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(dumps(data))


def _prepare_lines(text: str) -> list[tuple[int, str]]:
    prepared: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        prepared.append((indent, raw.strip()))
    return prepared


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    is_list = lines[index][0] == indent and lines[index][1].startswith("- ")
    result: Any = [] if is_list else {}
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"Unexpected indentation at line {index + 1}")
        if is_list:
            if not content.startswith("- "):
                break
            item_text = content[2:].strip()
            if not item_text:
                item, index = _parse_block(lines, index + 1, indent + 2)
                result.append(item)
                continue
            if ":" in item_text and not item_text.startswith(("'", '"')):
                key, value_text = item_text.split(":", 1)
                item = {key.strip(): _parse_scalar(value_text.strip())} if value_text.strip() else {}
                index += 1
                if index < len(lines) and lines[index][0] > indent:
                    nested, index = _parse_block(lines, index, indent + 2)
                    if isinstance(nested, dict):
                        item.update(nested)
                    else:
                        item[key.strip()] = nested
                result.append(item)
                continue
            result.append(_parse_scalar(item_text))
            index += 1
            continue
        if ":" not in content:
            raise ValueError(f"Expected key/value mapping at line {index + 1}")
        key, value_text = content.split(":", 1)
        key = key.strip()
        value_text = value_text.strip()
        index += 1
        if value_text:
            result[key] = _parse_scalar(value_text)
        elif index < len(lines) and lines[index][0] > indent:
            result[key], index = _parse_block(lines, index, indent + 2)
        else:
            result[key] = {}
    return result, index


def _parse_scalar(value: str) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _dump_value(data: Any, indent: int) -> str:
    prefix = " " * indent
    if isinstance(data, dict):
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_dump_value(value, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(value)}")
        return "\n".join(lines)
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                lines.append(_dump_value(item, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.append(_dump_value(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_format_scalar(data)}"


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text or text.strip() != text or any(ch in text for ch in [":", "#", "[", "]", "{", "}"]):
        return json.dumps(text)
    return text
