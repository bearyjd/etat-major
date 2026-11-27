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


def _redact(value: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    """Replace each run of overlapping or touching matches with one placeholder."""
    spans = sorted(match.span() for pattern in patterns for match in pattern.finditer(value))
    merged: list[tuple[int, int]] = []
    for start, end in spans:
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
    return _redact(value, (*patterns, _SCP_REMOTE) if scp_remotes else patterns)


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
