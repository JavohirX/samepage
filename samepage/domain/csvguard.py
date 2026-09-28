"""RFC 4180 formula guard. Numeric cells are left alone."""

from __future__ import annotations

_TRIGGERS = "=+-@\t\r"


def guard_cell(value, *, numeric: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if numeric or text == "":
        return text
    if text[0] in _TRIGGERS:
        return "'" + text
    return text
