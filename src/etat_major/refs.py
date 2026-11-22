"""Parse and validate cross-record references (docs/TRACEABILITY.md, "Reference grammar").

Grammar: ``<kind>:<id>``. Project-scoped kinds use ``<project>/<n>``; research and
decision ids are global; a research finding is ``research:<id>#<finding>``; code refs
are ``fp:n:<component>``, ``fp:f:<path>`` and ``trail:<path>#<symbol>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_PROJECT = r"[a-z0-9][a-z0-9_-]*"
_PATH_OK = re.compile(r"[^\s#]+")
_PROJECT_KINDS: Final = {"feature": r"[0-9]+", "task": r"[0-9]+", "milestone": r"[a-z0-9]+"}
_GLOBAL_KINDS: Final = ("research", "decision")
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_FINDING = re.compile(r"[A-Za-z0-9_-]+")
_GLOBAL_ID = re.compile(r"[0-9]+")
_GRAMMAR = (
    "feature|task|milestone:<project>/<n>, research:<id>[#<finding>], decision:<id>, "
    "fp:n:<component>, fp:f:<path>, trail:<path>#<symbol>"
)


class RefError(ValueError):
    """A reference does not follow the grammar."""

    def __init__(self, text: object, reason: str) -> None:
        self.text = text
        super().__init__(f"invalid reference {text!r}: {reason}; expected {_GRAMMAR}")


@dataclass(frozen=True)
class Ref:
    """A validated reference. ``fragment`` is a finding id or a trail symbol."""

    kind: str
    id: str
    project: str | None = None
    fragment: str | None = None

    def __str__(self) -> str:
        if self.kind in ("fp:n", "fp:f"):
            return f"{self.kind}:{self.id}"
        if self.kind == "trail":
            return f"trail:{self.id}#{self.fragment}"
        body = f"{self.project}/{self.id}" if self.project else self.id
        return f"{self.kind}:{body}" + (f"#{self.fragment}" if self.fragment else "")


def _check_path(text: str, path: str) -> None:
    if not _PATH_OK.fullmatch(path) or path.startswith("/") or ".." in path.split("/"):
        raise RefError(text, "path must be relative, without '..', spaces or '#'")


def _code_ref(text: str) -> Ref | None:
    if text.startswith("fp:n:"):
        comp = text[5:]
        if not _COMPONENT.fullmatch(comp):
            raise RefError(text, "bad component id")
        return Ref("fp:n", comp)
    if text.startswith("fp:f:"):
        _check_path(text, text[5:])
        return Ref("fp:f", text[5:])
    if text.startswith("trail:"):
        path, sep, symbol = text[6:].partition("#")
        _check_path(text, path)
        if not sep or not _PATH_OK.fullmatch(symbol):
            raise RefError(text, "trail refs need a '#<symbol>'")
        return Ref("trail", path, fragment=symbol)
    return None


def parse_ref(text: str) -> Ref:
    """Parse ``text`` into a ``Ref`` or raise ``RefError``."""
    if not isinstance(text, str):
        raise RefError(text, "reference must be a string")
    code = _code_ref(text)
    if code is not None:
        return code
    kind, sep, rest = text.partition(":")
    if not sep:
        raise RefError(text, "missing '<kind>:' prefix")
    if kind in _PROJECT_KINDS:
        m = re.fullmatch(rf"({_PROJECT})/({_PROJECT_KINDS[kind]})", rest)
        if not m:
            raise RefError(text, f"{kind} refs use '<project>/<n>'")
        return Ref(kind, m.group(2), project=m.group(1))
    if kind in _GLOBAL_KINDS:
        ident, hash_, frag = rest.partition("#")
        if not _GLOBAL_ID.fullmatch(ident):
            raise RefError(text, f"{kind} ids are global numbers")
        if hash_ and (kind != "research" or not _FINDING.fullmatch(frag)):
            raise RefError(text, "only research refs take a '#<finding>' fragment")
        return Ref(kind, ident, fragment=frag or None)
    raise RefError(text, f"unknown kind '{kind}'")
