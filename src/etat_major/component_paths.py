"""Repository-relative component path matching and sibling overlap checks."""

from collections.abc import Callable, Iterator
from fnmatch import fnmatchcase
from functools import lru_cache

from etat_major.refs import RefError, parse_ref

_WILDCARDS = "*?["
_OVERLAP_WORK_LIMIT = 500_000


class OverlapLimit(ValueError):
    pass


def component_path(value: str) -> str:
    return _checked(value, f"fp:f:{value}")


def component_file_path(value: str) -> str:
    return _checked(value, f"trail:{value}#file")


def _checked(value: str, ref: str) -> str:
    try:
        parse_ref(ref)
    except RefError:
        raise ValueError("expected a safe repository-relative path or glob") from None
    if ":" in value or "#" in value:
        raise ValueError("path or glob cannot contain colons or hash signs")
    return value


@lru_cache(maxsize=4096)
def literal_prefix(pattern: str) -> str:
    if not any(char in pattern for char in _WILDCARDS):
        return pattern
    offset = 0
    for segment in pattern.split("/"):
        for token in _tokens(segment):
            if token in ("*", "?") or len(token) > 1:
                return pattern[:offset]
            offset += 1
        offset += 1
    return pattern


def matches(pattern: str, path: str) -> bool:
    prefix = literal_prefix(pattern)
    if prefix == pattern:
        return path == pattern or path.startswith(pattern + "/")
    if not path.startswith(prefix) and path != prefix.removesuffix("/"):
        return False
    segments = pattern.split("/")
    positions = {0}
    for part in path.split("/"):
        following = set()
        for i in _skip_stars(segments, positions):
            if i < len(segments) and fnmatchcase(part, segments[i]):
                following.add(i if segments[i] == "**" else i + 1)
        if not following:
            return False
        positions = following
    return len(segments) in _skip_stars(segments, positions)


def _skip_stars(segments: list[str], starts: set[int]) -> set[int]:
    positions = set(starts)
    for i in starts:
        while i < len(segments) and segments[i] == "**":
            i += 1
            positions.add(i)
    return positions


def _transitions(
    tokens: tuple[str, ...], index: int, star: str, any_token: str
) -> Iterator[tuple[str | None, int]]:
    if index < len(tokens):
        token = tokens[index]
        if token == star:
            yield None, index + 1
            yield any_token, index
        else:
            yield token, index + 1


def _intersection(
    left: tuple[str, ...],
    right: tuple[str, ...],
    star: str,
    any_token: str,
    compatible: Callable[[str, str], bool],
    spend: Callable[[], None],
    *,
    nonempty: bool = False,
) -> bool:
    pending = [(0, 0, False)]
    seen = set(pending)
    for i, j, used in pending:
        spend()
        if i == len(left) and j == len(right) and (used or not nonempty):
            return True
        a = tuple(_transitions(left, i, star, any_token))
        b = tuple(_transitions(right, j, star, any_token))
        steps = [(ni, j, used) for token, ni in a if token is None]
        steps.extend((i, nj, used) for token, nj in b if token is None)
        steps.extend(
            (ni, nj, True)
            for x, ni in a
            if x is not None
            for y, nj in b
            if y is not None and compatible(x, y)
        )
        for step in steps:
            if step not in seen:
                seen.add(step)
                pending.append(step)
    return False


def _tokens(segment: str) -> tuple[str, ...]:
    tokens = []
    i = 0
    while i < len(segment):
        end = i
        if segment[i] == "[":
            start = i + 1
            if segment[start : start + 1] == "!":
                start += 1
            if segment[start : start + 1] == "]":
                start += 1
            end = max(i, segment.find("]", start))
        tokens.append(segment[i : end + 1])
        i = end + 1
    return tuple(tokens)


def _characters_overlap(left: str, right: str) -> bool:
    if len(left) == 1 and left != "?":
        return fnmatchcase(left, right)
    if len(right) == 1 and right != "?":
        return fnmatchcase(right, left)
    # Membership in either character class changes only at its range boundaries.
    points = {ord("a")}
    for char in left + right:
        points.update((ord(char), ord(char) - 1, ord(char) + 1))
    return any(
        fnmatchcase(chr(value), left) and fnmatchcase(chr(value), right)
        for value in points
        if 32 < value < 0x110000 and chr(value) not in "/\\%#:"
    )


def _segments_overlap(left: str, right: str, spend: Callable[[], None]) -> bool:
    if literal_prefix(left) == left:
        return fnmatchcase(left, right)
    if literal_prefix(right) == right:
        return fnmatchcase(right, left)
    return _intersection(
        _tokens(left), _tokens(right), "*", "?", _characters_overlap, spend, nonempty=True
    )


def _overlap_pattern(pattern: str) -> tuple[str, ...]:
    segments = tuple(pattern.split("/"))
    return (*segments, "**") if literal_prefix(pattern) == pattern else segments


def overlap_checker() -> Callable[[str, str], bool]:
    """Bound aggregate glob intersection work for one component document."""
    remaining = _OVERLAP_WORK_LIMIT

    def spend() -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise OverlapLimit("component path overlap exceeds the work limit")

    @lru_cache(maxsize=4096)
    def segments_overlap(left: str, right: str) -> bool:
        return _segments_overlap(left, right, spend)

    def overlaps(left: str, right: str) -> bool:
        a, b = literal_prefix(left), literal_prefix(right)
        if a == left and b == right:
            return matches(left, right) or matches(right, left)
        if not (a.startswith(b) or b.startswith(a)):
            return False
        return _intersection(
            _overlap_pattern(left), _overlap_pattern(right), "**", "*", segments_overlap, spend
        )

    return overlaps
