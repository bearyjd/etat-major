"""Format untrusted values for plain-text output and diagnostics."""

from unicodedata import category


def is_control(char: str) -> bool:
    return category(char) in {"Cc", "Cf"}


def safe(value: object) -> str:
    """Escape terminal control and formatting characters, preserving other text."""
    return "".join(
        (rf"\u{ord(char):04x}" if ord(char) <= 0xFFFF else rf"\U{ord(char):08x}")
        if is_control(char)
        else char
        for char in str(value)
    )


def bounded_repr(value: object) -> str:
    """Quote at most 80 source characters for display in a diagnostic."""
    if isinstance(value, str):
        return repr(value[:80]) + ("…" if len(value) > 80 else "")
    if value is not None and not isinstance(value, (bool, int, float)):
        return f"<{type(value).__name__[:78]}>"
    representation = repr(value)
    return representation[:80] + ("…" if len(representation) > 80 else "")
