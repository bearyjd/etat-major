"""Recognize a bounded literal subset of Gradle scripts."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from etat_major.taskfile import TaskFileError
from etat_major.workspace import Issue

MAX_DEPTH = 64
_IDENT = r"[a-zA-Z_][a-zA-Z_0-9]*"
_WORD = re.compile(_IDENT)
_SEGMENT = r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*"
_PROJECT = re.compile(rf":?{_SEGMENT}(?::{_SEGMENT})*")
_DIRECTORY = re.compile(rf"{_SEGMENT}(?:/{_SEGMENT})*")
_COMMENT = re.compile(r"/\*|\*/")
_TOKEN = re.compile(
    rf"""(?P<skip>\s+|//[^\n]*)|(?P<comment>/\*)"""
    r"""|(?P<opaque>\$/[\s\S]*?/\$)|(?P<quote>['"])"""
    rf"""|(?P<word>{_IDENT})|(?P<other>.)"""
)
_PAIRS = {"(": ")", "[": "]", "{": "}"}
_SLASHY = re.compile(r"/(?:[^/\\]|\\[\s\S])*/")
_EXPRESSION_START = {"", "=", "(", "[", ",", ":", "~", "return"}


@dataclass(frozen=True)
class Token:
    value: str
    line: int
    kind: str

    @property
    def literal(self) -> str | None:
        if self.kind == "string" and "\\" not in self.value and "$" not in self.value:
            return self.value[1:-1]
        return None


def _comment_end(text: str, start: int, file: Path) -> int:
    depth = 1
    for match in _COMMENT.finditer(text, start):
        depth += 1 if match[0] == "/*" else -1
        if depth == 0:
            return match.end()
        if depth > MAX_DEPTH:
            raise TaskFileError(file, "syntax", "comment nesting limit exceeded")
    raise TaskFileError(file, "syntax", "unterminated block comment")


def _quoted_end(text: str, start: int, file: Path, depth: int = 0) -> tuple[int, str]:
    char = text[start]
    quote = char * 3 if text.startswith(char * 3, start) else char
    index = start + len(quote)
    raw = quote == '"""' and file.suffix == ".kts"
    while index < len(text):
        if text.startswith(quote, index):
            return index + len(quote), "string" if len(quote) == 1 else "opaque"
        if char == '"' and text.startswith("${", index):
            index = _interpolation_end(text, index + 2, file, depth + 1)
        elif text[index] == "\\" and not raw:
            index += 2
        elif text[index] == "\n" and len(quote) == 1:
            break
        else:
            index += 1
    raise TaskFileError(file, "syntax", "unterminated string")


def _interpolation_end(text: str, index: int, file: Path, depth: int) -> int:
    nesting = 1
    while index < len(text):
        if depth + nesting > MAX_DEPTH:
            raise TaskFileError(file, "syntax", "string interpolation nesting limit exceeded")
        char = text[index]
        if char in {"'", '"'}:
            index, _ = _quoted_end(text, index, file, depth + nesting)
            continue
        if text.startswith("/*", index):
            index = _comment_end(text, index + 2, file)
            continue
        if text.startswith("//", index):
            index = text.find("\n", index)
            if index < 0:
                break
            continue
        nesting += (char == "{") - (char == "}")
        index += 1
        if nesting == 0:
            return index
    raise TaskFileError(file, "syntax", "unterminated string interpolation")


def _tokens(text: str, file: Path) -> Iterator[Token]:
    offset, line = 0, 1
    previous = ""
    while offset < len(text):
        match = _TOKEN.match(text, offset)
        if match is None:
            raise TaskFileError(file, "syntax", f"line {line}: invalid token")
        end, kind = match.end(), match.lastgroup
        value = match[0]
        if kind == "comment":
            end = _comment_end(text, end, file)
        elif kind != "skip":
            if kind == "quote":
                end, kind = _quoted_end(text, offset, file)
                value = text[offset:end]
            elif value == "$" and text.startswith("$/", offset):
                raise TaskFileError(file, "syntax", f"line {line}: unterminated string")
            if (
                value == "/"
                and previous in _EXPRESSION_START
                and (slashy := _SLASHY.match(text, offset))
            ):
                end, kind, value = slashy.end(), "opaque", slashy[0]
            previous = value
            yield Token(value, line, kind or "other")
        line += text.count("\n", offset, end)
        offset = end


@dataclass(frozen=True)
class Script:
    file: Path
    tokens: tuple[Token, ...]
    closing: tuple[int, ...]

    def issue(self, field: str, index: int, message: str) -> Issue:
        return Issue(self.file.as_posix(), field, f"line {self.tokens[index].line}: {message}")

    def siblings(self, start: int, stop: int) -> Iterator[int]:
        while start < stop:
            yield start
            start = self.closing[start] + 1

    def values(self, start: int, stop: int) -> tuple[str, ...]:
        return tuple(token.value for token in self.tokens[start:stop])

    def arguments(self, start: int, stop: int) -> Iterator[tuple[int, int]]:
        for i in self.siblings(start, stop):
            if self.tokens[i].value == ",":
                yield start, i
                start = i + 1
        if start < stop:
            yield start, stop


def parse_script(text: str, file: Path) -> Script:
    tokens = tuple(_tokens(text, file))
    closing = list(range(len(tokens)))
    stack: list[int] = []
    for i, token in enumerate(tokens):
        if token.value in _PAIRS:
            stack.append(i)
            if len(stack) > MAX_DEPTH:
                raise TaskFileError(file, "syntax", f"line {token.line}: nesting limit exceeded")
        elif token.value in _PAIRS.values():
            if not stack or _PAIRS[tokens[stack[-1]].value] != token.value:
                raise TaskFileError(file, "syntax", f"line {token.line}: mismatched delimiters")
            closing[stack.pop()] = i
    if stack:
        raise TaskFileError(file, "syntax", f"line {tokens[stack[-1]].line}: unclosed delimiter")
    return Script(file, tokens, tuple(closing))


def _project_id(literal: str | None) -> str | None:
    if literal == ":":
        return literal
    if literal is not None and _PROJECT.fullmatch(literal):
        return ":" + literal.lstrip(":")
    return None


def _include_ranges(script: Script, start: int) -> Iterator[tuple[int, int]]:
    tokens = script.tokens
    if start < len(tokens) and tokens[start].value == "(":
        yield from script.arguments(start + 1, script.closing[start])
        return
    stop = start
    while stop < len(tokens) and tokens[stop].value != ";":
        if tokens[stop].line > tokens[stop - 1].line and tokens[stop - 1].value != ",":
            break
        if tokens[stop].line > tokens[stop - 1].line and tokens[stop].value in {
            "include",
            "includeBuild",
            "includeFlat",
            "project",
            "rootProject",
        }:
            break
        stop = script.closing[stop] + 1
    yield from script.arguments(start, stop)


def _included(script: Script, index: int, issues: list[Issue]) -> Iterator[str]:
    ranges = tuple(_include_ranges(script, index + 1))
    if not ranges:
        issues.append(script.issue("include", index, "expected literal project paths"))
    for start, stop in ranges:
        project = _project_id(script.tokens[start].literal) if stop == start + 1 else None
        if project is None:
            issues.append(script.issue("include", index, "unsupported project path expression"))
        elif project.count(":") > MAX_DEPTH:
            issues.append(script.issue("include", start, "project directory depth limit exceeded"))
        else:
            yield project


def _remap(script: Script, index: int) -> tuple[str | None, str | None]:
    tokens = script.tokens
    start = index - 5
    if start < 0 or start and tokens[start - 1].value == ".":
        return None, None
    if script.values(start, index - 3) != ("project", "("):
        return None, None
    if script.values(index - 2, index) != (")", "."):
        return None, None
    project = _project_id(tokens[index - 3].literal)
    if script.values(index + 1, index + 4) != ("=", "file", "("):
        return project, None
    if script.closing[index + 3] != index + 5:
        return project, None
    end = index + 6
    if end < len(tokens) and tokens[end].value != ";":
        if tokens[end].line == tokens[end - 1].line or tokens[end].value in {
            ".",
            "+",
            "/",
            "?",
            "[",
            "(",
        }:
            return project, None
    directory = tokens[index + 4].literal
    if directory and _DIRECTORY.fullmatch(directory) and len(directory.split("/")) <= MAX_DEPTH:
        return project, directory
    return project, None


def parse_settings(script: Script, issues: list[Issue]) -> dict[str, str]:
    projects: dict[str, str] = {}
    remaps: dict[str, tuple[str | None, int]] = {}
    top_level = set(script.siblings(0, len(script.tokens)))
    for i, token in enumerate(script.tokens):
        value = token.value
        if i not in top_level:
            if value in {"include", "includeBuild", "includeFlat", "projectDir"}:
                issues.append(script.issue(value, i, "unsupported nested settings directive"))
                if value == "projectDir":
                    project, _ = _remap(script, i)
                    if project:
                        remaps[project] = None, i
            continue
        if value == "include":
            if i and script.tokens[i - 1].value == ".":
                issues.append(script.issue(value, i, "unsupported qualified settings directive"))
                continue
            projects.update(
                (project, project[1:].replace(":", "/")) for project in _included(script, i, issues)
            )
        elif value in {"includeBuild", "includeFlat", "buildFileName"}:
            issues.append(script.issue(value, i, "unsupported settings directive"))
        elif value == "projectDir":
            project, directory = _remap(script, i)
            if project:
                remaps[project] = directory, i
            else:
                issues.append(script.issue("projectDir", i, "unsupported project directory"))
    for project, (directory, i) in remaps.items():
        if project in projects and directory is not None:
            projects[project] = directory
        else:
            projects.pop(project, None)
            if i in top_level:
                issues.append(script.issue("projectDir", i, "unsupported project directory"))
    return projects


def _direct_project(script: Script, start: int, stop: int) -> str | None:
    tokens = script.tokens
    if script.values(start, start + 2) != ("project", "("):
        return None
    if script.closing[start + 1] != stop - 1:
        return None
    for a, b in script.arguments(start + 2, stop - 1):
        if b - a >= 2 and script.values(a, a + 2) in {("path", ":"), ("path", "=")}:
            return _project_id(tokens[a + 2].literal) if b == a + 3 else None
        if a == start + 2 and b == a + 1:
            return _project_id(tokens[a].literal)
    return None


def _accessor(values: tuple[str, ...]) -> str | None:
    if len(values) >= 3 and values[1::2] == (".",) * (len(values) // 2):
        if len(values) % 2 == 1 and all(_WORD.fullmatch(word) for word in values[2::2]):
            return ".".join(values[2::2])
    return None


def _unwrap(script: Script, start: int, stop: int) -> tuple[int, int, bool]:
    fixtures = False
    while script.values(start, start + 2) == ("testFixtures", "("):
        if script.closing[start + 1] != stop - 1:
            break
        start, stop = start + 2, stop - 1
        fixtures = True
    return start, stop, fixtures


@dataclass(frozen=True)
class Request:
    target: str | None
    accessor: bool
    configuration: str
    test_only: bool
    index: int


def _request(script: Script, config: str, start: int, stop: int, index: int) -> Request | None:
    start, stop, fixtures = _unwrap(script, start, stop)
    if start >= stop:
        return None
    value = script.tokens[start].value
    if value not in {"project", "projects", "testFixtures"}:
        return None
    target = (
        _accessor(script.values(start, stop))
        if value == "projects"
        else _direct_project(script, start, stop)
    )
    test_only = fixtures or config.lower().startswith(("test", "androidtest"))
    return Request(target, value == "projects", config, test_only, index)


def _statement_end(script: Script, start: int, stop: int) -> int:
    tokens = script.tokens
    for i in script.siblings(start, stop):
        if tokens[i].value == ";":
            return i
        if i > start and tokens[i].line > tokens[i - 1].line:
            if tokens[i].value not in {".", "{"} and tokens[i - 1].value not in {".", ","}:
                return i
    return stop


def _configuration(script: Script, start: int, stop: int) -> Request | None:
    config = script.tokens[start].value
    arg = start + 1
    if arg >= stop or not _WORD.fullmatch(config):
        return None
    if script.tokens[arg].value == "(":
        close = script.closing[arg]
        args = iter(script.arguments(arg + 1, close))
        first = next(args, None)
        if config == "add" and first is not None:
            a, b = first
            config = (script.tokens[a].literal or "") if b == a + 1 else ""
            first = next(args, None)
        if first and _WORD.fullmatch(config):
            return _request(script, config, *first, start)
        return None
    return _request(script, config, arg, stop, start)


def dependency_requests(script: Script) -> Iterator[Request]:
    tokens = script.tokens
    for i in script.siblings(0, len(tokens)):
        if script.values(i, i + 2) != ("dependencies", "{"):
            continue
        if i and tokens[i - 1].value == ".":
            continue
        end = script.closing[i + 1]
        start = i + 2
        while start < end:
            stop = _statement_end(script, start, end)
            if start < stop:
                request = _configuration(script, start, stop)
                if request is not None:
                    yield request
                elif _has_project_reference(script, start, stop):
                    yield Request(None, False, "", False, start)
            start = stop + (stop < end and tokens[stop].value == ";")


def _has_project_reference(script: Script, start: int, stop: int) -> bool:
    tokens = script.tokens
    return any(
        (tokens[i].value, tokens[i + 1].value)
        in {("project", "("), ("projects", "."), ("findProject", "(")}
        and (i == start or tokens[i - 1].value != ".")
        for i in range(start, stop - 1)
    )
