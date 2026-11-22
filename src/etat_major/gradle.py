"""Discover Gradle projects and literal dependency declarations without executing scripts."""

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from etat_major.gradle_parse import Script, dependency_requests, parse_script, read_script
from etat_major.gradle_plugins import (
    Implementation,
    applied_plugins,
    discover_plugins,
    read_plugin_aliases,
)
from etat_major.gradle_settings import parse_settings
from etat_major.localfiles import open_directory, open_relative_directory
from etat_major.taskfile import TaskFileError
from etat_major.workspace import Issue

_FILE_LIMIT = 5000
_ACCESSOR_SEPARATOR = re.compile(r"[-_](?=[a-zA-Z0-9])")


@dataclass(frozen=True)
class Module:
    id: str
    directory: str


@dataclass(frozen=True)
class Declaration:
    source: str
    target: str
    configuration: str
    test_only: bool
    file: str
    line: int


@dataclass(frozen=True)
class ImplicitDeclaration(Declaration):
    plugin_id: str
    plugin_class: str
    implicit: bool = True


@dataclass(frozen=True)
class GradleDependencies:
    modules: tuple[Module, ...]
    edges: tuple[Declaration, ...]
    issues: tuple[Issue, ...]
    implicit_edges: tuple[ImplicitDeclaration, ...] = ()


def _module_script(directory: Path, root_fd: int) -> tuple[Path, str] | None:
    try:
        with open_relative_directory(directory, root_fd) as fd:
            return read_script(directory, "build", fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise TaskFileError(
            directory, "directory", "cannot open a symlink-free directory"
        ) from None


def _accessors(projects: dict[str, str]) -> dict[str, list[str]]:
    by_accessor: dict[str, list[str]] = defaultdict(list)
    for project in projects:
        words = []
        for segment in project[1:].split(":"):
            head, *tail = _ACCESSOR_SEPARATOR.split(segment)
            words.append(head + "".join(word[0].upper() + word[1:] for word in tail))
        by_accessor[".".join(words)].append(project)
    return by_accessor


def _declarations(
    module: Module,
    script: Script,
    projects: dict[str, str],
    accessors: dict[str, list[str]],
    issues: list[Issue],
) -> list[Declaration]:
    edges = []
    for request in dependency_requests(script):
        target = request.target
        if request.accessor and target is not None:
            candidates = accessors.get(target, [])
        else:
            candidates = [target] if target is not None and target in projects else []
        if len(candidates) != 1:
            message = (
                "unsupported project dependency expression"
                if target is None
                else "ambiguous project accessor"
                if candidates
                else "unresolved project dependency"
            )
            issues.append(script.issue("dependencies", request.index, message))
            continue
        edges.append(
            Declaration(
                module.id,
                candidates[0],
                request.configuration,
                request.test_only,
                script.file.as_posix(),
                script.tokens[request.index].line,
            )
        )
    return edges


def _read_module(
    module: Module,
    fd: int,
    issues: list[Issue],
    root_script: tuple[Path, str] | None,
) -> Script | None:
    try:
        script_file = (
            root_script if module.id == ":" else _module_script(Path(module.directory), fd)
        )
        return parse_script(script_file[1], script_file[0]) if script_file else None
    except TaskFileError as exc:
        directory = Path(module.directory)
        path = directory / exc.filename if exc.field != "directory" else directory
        issues.append(Issue(path.as_posix(), exc.field_name, exc.message))
        return None


def _implicit_declarations(
    module: Module,
    script: Script,
    projects: dict[str, str],
    plugins: dict[str, Implementation | None],
    aliases: dict[str, str],
    issues: list[Issue],
) -> list[ImplicitDeclaration]:
    edges = []
    for plugin_id, implementation in applied_plugins(script, plugins, aliases, issues):
        for request in implementation.dependencies:
            if request.target in projects:
                edges.append(
                    ImplicitDeclaration(
                        module.id,
                        request.target,
                        request.configuration,
                        request.test_only,
                        request.file,
                        request.line,
                        plugin_id,
                        implementation.name,
                    )
                )
            else:
                issue = Issue(
                    request.file,
                    "dependencies",
                    f"line {request.line}: unresolved project dependency",
                    severity="warning",
                    blocking=False,
                )
                if issue not in issues:
                    issues.append(issue)
    return edges


def _scan_modules(
    fd: int,
    projects: dict[str, str],
    root_script: tuple[Path, str] | None,
    plugins: dict[str, Implementation | None],
    issues: list[Issue],
) -> GradleDependencies:
    modules = tuple(Module(project, directory) for project, directory in sorted(projects.items()))
    accessors = _accessors(projects)
    aliases = read_plugin_aliases(fd, issues) if plugins else {}
    edges = []
    implicit_edges = []
    for module in modules:
        script = _read_module(module, fd, issues, root_script)
        if script is None:
            continue
        edges.extend(_declarations(module, script, projects, accessors, issues))
        if plugins:
            implicit_edges.extend(
                _implicit_declarations(module, script, projects, plugins, aliases, issues)
            )
    return GradleDependencies(modules, tuple(edges), tuple(issues), tuple(implicit_edges))


def _settings_issue_order(issue: Issue, file: Path) -> tuple[int, int]:
    if issue.path != file.as_posix():
        return (1, 0)
    line = issue.message.removeprefix("line ").partition(":")[0]
    return (0, int(line) if line.isdecimal() else 0)


def _discover(fd: int) -> GradleDependencies:
    settings_file = read_script(Path("."), "settings", fd)
    if settings_file is None:
        raise TaskFileError(Path("settings.gradle"), "file", "missing Gradle settings script")
    file, text = settings_file
    issues: list[Issue] = []
    includes: dict[str, int] = {}
    settings = parse_script(text, file)
    projects = parse_settings(settings, issues, includes)
    if 2 + 2 * (len(projects.keys() - {":"}) + 1) > _FILE_LIMIT:
        raise TaskFileError(
            file, "include", f"repository exceeds the {_FILE_LIMIT} file probe limit"
        )
    try:
        root_script = read_script(Path("."), "build", fd)
    except TaskFileError as exc:
        issues.append(Issue(exc.filename, exc.field_name, exc.message))
        root_script = None
    if root_script:
        projects[":"] = ""
    plugins = discover_plugins(settings, includes, fd, issues)
    issues.sort(key=lambda issue: _settings_issue_order(issue, file))
    return _scan_modules(fd, projects, root_script, plugins, issues)


def load_dependencies(root: Path) -> GradleDependencies:
    """Read settings and the selected build script for each included project."""
    try:
        with open_directory(root) as fd:
            return _discover(fd)
    except (OSError, ValueError) as exc:
        if isinstance(exc, TaskFileError):
            raise
        raise TaskFileError(Path("."), "root", "cannot open a symlink-free directory") from None
