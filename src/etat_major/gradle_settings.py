"""Recognize project discovery directives in Gradle settings."""

import re
from collections.abc import Iterator

from etat_major.gradle_parse import MAX_DEPTH, PROJECT_SEGMENT, Script, project_id
from etat_major.workspace import Issue

_DIRECTORY = re.compile(rf"{PROJECT_SEGMENT}(?:/{PROJECT_SEGMENT})*")


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
        project = project_id(script.tokens[start].literal) if stop == start + 1 else None
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
    project = project_id(tokens[index - 3].literal)
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


def _statement_start(script: Script, index: int) -> bool:
    if index == 0:
        return True
    previous, current = script.tokens[index - 1 : index + 1]
    return previous.value in {"{", "}", ";"} or (
        previous.line < current.line and previous.value not in {".", "=", ",", "+", "-", "/"}
    )


def _has_call_argument(script: Script, index: int) -> bool:
    following = script.tokens[index + 1 : index + 2]
    return bool(following) and (
        following[0].value == "("
        or (
            following[0].line == script.tokens[index].line
            and following[0].kind in {"word", "string", "opaque"}
        )
    )


def _composite_call(script: Script, index: int) -> bool:
    return _has_call_argument(script, index) and (
        _statement_start(script, index)
        or (index > 0 and script.tokens[index - 1].value == ")")
        or (index >= 2 and script.values(index - 2, index) == ("settings", "."))
    )


def _composite_issue(script: Script, index: int) -> Issue:
    return script.issue("includeBuild", index, "composite build not followed", blocking=False)


def _statement_end(script: Script, start: int, stop: int) -> int:
    tokens = script.tokens
    for i in script.siblings(start, stop):
        token = tokens[i]
        if token.value == ";":
            return i
        if i == start:
            continue
        if (
            tokens[i - 1].line < token.line
            and _statement_start(script, i)
            and token.value not in {".", "+", "-", "/", "?", "{", "else", "catch", "finally"}
        ):
            return i
        if token.value in {"include", "includeBuild", "includeFlat"} and tokens[
            i - 1
        ].value not in {".", "+", "-", "/", "?", ":", "="}:
            return i
    return stop


def _ignored_end(script: Script, index: int, issues: list[Issue]) -> int:
    value = script.tokens[index].value
    next_value = script.values(index + 1, index + 2)
    if value in {"pluginManagement", "dependencyResolutionManagement"} and next_value == ("{",):
        end = script.closing[index + 1]
        if value == "pluginManagement":
            for child in range(index + 2, end):
                if script.tokens[child].value == "includeBuild" and _composite_call(script, child):
                    issues.append(_composite_issue(script, child))
        return end + 1
    if value == "enableFeaturePreview" and _has_call_argument(script, index):
        return _statement_end(script, index + 1, len(script.tokens))
    if value == "rootProject" and script.values(index + 1, index + 4) == (".", "name", "="):
        return _statement_end(script, index + 4, len(script.tokens))
    return index


def _settings_tokens(script: Script, top_level: set[int], issues: list[Issue]) -> Iterator[int]:
    skip_until = 0
    groups: list[int] = []
    for i, token in enumerate(script.tokens):
        if i < skip_until:
            continue
        if groups and i == script.closing[groups[-1]]:
            groups.pop()
        if (
            token.value == "includeBuild"
            and (not groups or script.tokens[groups[-1]].value == "{")
            and _composite_call(script, i)
        ):
            issues.append(_composite_issue(script, i))
            end = script.closing[groups[-1]] if groups else len(script.tokens)
            skip_until = _statement_end(script, i + 1, end)
            continue
        if i in top_level and _statement_start(script, i):
            skip_until = _ignored_end(script, i, issues)
            if i < skip_until:
                continue
        if script.closing[i] != i:
            groups.append(i)
        yield i


def parse_settings(script: Script, issues: list[Issue]) -> dict[str, str]:
    projects: dict[str, str] = {}
    remaps: dict[str, tuple[str | None, int]] = {}
    top_level = set(script.siblings(0, len(script.tokens)))
    for i in _settings_tokens(script, top_level, issues):
        value = script.tokens[i].value
        if i not in top_level:
            if value in {"include", "includeFlat", "projectDir"}:
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
        elif value in {"includeFlat", "buildFileName"}:
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
