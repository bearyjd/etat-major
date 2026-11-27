"""Format untrusted values for plain-text output and diagnostics."""

import re
from collections.abc import Iterable
from unicodedata import category
from urllib.parse import urlsplit, urlunsplit

_ESCAPED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"})
_SPACING = re.compile(r"[ \t\r\n]+")


def is_control(char: str) -> bool:
    return category(char) in {"Cc", "Cf"}


def _escape(char: str) -> str:
    if category(char) not in _ESCAPED_CATEGORIES:
        return char
    codepoint = ord(char)
    return rf"\u{codepoint:04x}" if codepoint <= 0xFFFF else rf"\U{codepoint:08x}"


def safe(value: object, *, limit: int | None = None) -> str:
    """Escape unsafe terminal characters and optionally bound the escaped output."""
    return _bounded(map(_escape, str(value)), limit)


def safe_field(value: str, *, multiline: bool = False, limit: int | None = None) -> str:
    """Escape a view or export field, handling line breaks. Never use for terminal output.

    A single-line field turns each spacing run that holds a tab, CR or LF into one
    space and trims it. A multiline field keeps line feeds and writes CRLF and CR as
    LF. Every other character is escaped as by ``safe``.
    """
    if not multiline:
        return safe(_one_line(value), limit=limit)
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return _bounded((char if char == "\n" else _escape(char) for char in text), limit)


def _one_line(value: str) -> str:
    # Explicit characters only: str.split and \s would also swallow U+0085 and U+2028.
    joined = _SPACING.sub(lambda run: run[0] if not run[0].strip(" ") else " ", value)
    return joined.strip(" ")


def _bounded(escaped: Iterable[str], limit: int | None) -> str:
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
    (?<![\w.+-])(?:[a-z][a-z0-9+.-]*://|[\w.+-]+@[\w.-]+:)
    [^\s"'<>]+
    | (?<![\w/])(?:[a-z]:[\\/]|\\\\|~?/)[^\s"'<>]+
    """
)


_SCP_REMOTE = re.compile(
    r"""(?ix)
    (?<![\w./+-])(?:[\w.+-]+@)?
    (?:
        (?:[\w-]+\.)+[\w-]+: | \[[0-9a-f:.]+\]:
        | [\w-]+:(?=[^\s"'<>:]*/|[^\s"'<>:]*\.git(?:$|[\s"'<>),.;]))
    )
    [^\s"'<>:]+
    """
)


_REDACTED = "[redacted location]"
# Matching existing placeholders keeps one whole when another span cuts into it.
_PLACEHOLDER = re.compile(re.escape(_REDACTED))


def _spans(value: str, patterns: tuple[re.Pattern[str], ...]) -> list[tuple[int, int]]:
    return [match.span() for pattern in patterns for match in pattern.finditer(value)]


def _redact(value: str, spans: list[tuple[int, int]]) -> str:
    """Replace each run of overlapping or touching spans with one placeholder."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    parts, kept_from = [], 0
    for start, end in merged:
        parts += [value[kept_from:start], _REDACTED]
        kept_from = end
    return "".join([*parts, value[kept_from:]])


def public_text(value: str, *, scp_remotes: bool = False) -> str:
    # Every pattern reads the original text, never another pattern's placeholder.
    patterns = (_PLACEHOLDER, _PRIVATE_LOCATION)
    return _redact(value, _spans(value, (*patterns, _SCP_REMOTE) if scp_remotes else patterns))


def redact_escaped_locations(value: str) -> str:
    """Also redact what reads as one location once ``safe`` has escaped the value.

    An escape such as ``\\u000a`` joins the words around it. Matches found in that
    form are mapped back by position, so the value itself is never rewritten.
    """
    parts = [_escape(char) for char in value]
    owner = [index for index, part in enumerate(parts) for _ in part]
    found = _spans("".join(parts), (_PLACEHOLDER, _PRIVATE_LOCATION, _SCP_REMOTE))
    return _redact(value, [(owner[start], owner[end - 1] + 1) for start, end in found])


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
