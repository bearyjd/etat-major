"""Format untrusted values for plain-text output and diagnostics."""

from unicodedata import category

_ESCAPED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"})


def is_control(char: str) -> bool:
    return category(char) in {"Cc", "Cf"}


def _escape(char: str) -> str:
    if category(char) not in _ESCAPED_CATEGORIES:
        return char
    codepoint = ord(char)
    return rf"\u{codepoint:04x}" if codepoint <= 0xFFFF else rf"\U{codepoint:08x}"


def safe(value: object, *, limit: int | None = None) -> str:
    """Escape unsafe terminal characters and optionally bound the escaped output."""
    escaped = map(_escape, str(value))
    if limit is None:
        return "".join(escaped)
    if limit <= 0:
        return ""
    parts, size = [], 0
    for part in escaped:
        if size + len(part) > limit:
            if size == limit:
                parts.pop()
            parts.append("…")
            break
        parts.append(part)
        size += len(part)
    return "".join(parts)


def bounded_repr(value: object) -> str:
    """Quote at most 80 source characters for display in a diagnostic."""
    if isinstance(value, str):
        return repr(value[:80]) + ("…" if len(value) > 80 else "")
    if value is not None and not isinstance(value, (bool, int, float)):
        return f"<{type(value).__name__[:78]}>"
    representation = repr(value)
    return representation[:80] + ("…" if len(representation) > 80 else "")
