"""User-facing path diagnostics."""

from __future__ import annotations

import re


WINDOWS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def windows_path_hint(value: object) -> str:
    text = str(value)
    if not WINDOWS_PATH_RE.match(text):
        return ""
    if text.startswith("\\\\"):
        return (
            " This looks like a Windows UNC path. In WSL, mount or copy the file "
            "and pass a Linux path instead."
        )
    drive = text[0].lower()
    rest = text[2:].replace("\\", "/").lstrip("/")
    return f" This looks like a Windows path. In WSL, use /mnt/{drive}/{rest} instead."
