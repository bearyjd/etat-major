"""Format untrusted values for plain-text output and diagnostics."""

import re
from unicodedata import category
from urllib.parse import urlsplit, urlunsplit

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


# These strings are free-form prose. Typed source URLs and HTTP route paths use their
# own contracts and bypass this filter.
_PRIVATE_LOCATION = re.compile(
    r"""(?ix)
    (?:[a-z][a-z0-9+.-]*://|[\w.+-]+@[\w.-]+:)
    [^\s"'<>]+
    | (?<![\w/])(?:[a-z]:[\\/]|\\\\|~?/)[^\s"'<>]+
    """
)


def public_text(value: str) -> str:
    return _PRIVATE_LOCATION.sub("[redacted location]", value)


def public_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    authority = parts.netloc.rsplit("@", 1)[-1]
    if not authority or "\\" in authority:
        return None
    return safe(urlunsplit((parts.scheme, authority, parts.path, "", "")))
