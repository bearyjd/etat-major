"""Discover Gradle projects and literal dependency declarations without executing scripts."""

import re
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from etat_major.gradle_parse import dependency_requests, parse_script, parse_settings
from etat_major.localfiles import open_directory, read_text_kib
from etat_major.taskfile import TaskFileError
from etat_major.workspace import Issue

_FILE_LIMIT = 5000
INPUT_LIMIT_KIB = 256
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
class GradleDependencies:
    modules: tuple[Module, ...]
    edges: tuple[Declaration, ...]
    issues: tuple[Issue, ...]


def _script(directory: Path, base: str, fd: int) -> tuple[Path, str] | None:
    for name in (f"{base}.gradle.kts", f"{base}.gradle"):
        file = directory / name
        try:
            return file, read_text_kib(file, INPUT_LIMIT_KIB, dir_fd=fd)
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError):
            raise TaskFileError(file, "file", "cannot read script as UTF-8") from None
        except ValueError as exc:
            raise TaskFileError(file, "file", str(exc)) from None
    return None


def _module_script(directory: Path, root_fd: int) -> tuple[Path, str] | None:
    try:
        with ExitStack() as stack:
            fd = root_fd
            for part in directory.parts:
                fd = stack.enter_context(open_directory(Path(part), fd))
            return _script(directory, "build", fd)
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
    script_file: tuple[Path, str],
    projects: dict[str, str],
    accessors: dict[str, list[str]],
    issues: list[Issue],
) -> list[Declaration]:
    file, text = script_file
    script = parse_script(text, file)
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
                file.as_posix(),
                script.tokens[request.index].line,
            )
        )
    return edges


def _read_module(
    module: Module,
    fd: int,
    projects: dict[str, str],
    accessors: dict[str, list[str]],
    issues: list[Issue],
) -> list[Declaration]:
    try:
        script = _module_script(Path(module.directory), fd)
        return _declarations(module, script, projects, accessors, issues) if script else []
    except TaskFileError as exc:
        directory = Path(module.directory)
        path = directory / exc.filename if exc.field != "directory" else directory
        issues.append(Issue(path.as_posix(), exc.field_name, exc.message))
        return []


def _discover(fd: int) -> GradleDependencies:
    settings = _script(Path("."), "settings", fd)
    if settings is None:
        raise TaskFileError(Path("settings.gradle"), "file", "missing Gradle settings script")
    file, text = settings
    issues: list[Issue] = []
    projects = parse_settings(parse_script(text, file), issues)
    if 2 + 2 * (len(projects.keys() - {":"}) + 1) > _FILE_LIMIT:
        raise TaskFileError(
            file, "include", f"repository exceeds the {_FILE_LIMIT} file probe limit"
        )
    try:
        root_script = _script(Path("."), "build", fd)
    except TaskFileError as exc:
        issues.append(Issue(exc.filename, exc.field_name, exc.message))
        root_script = None
    if root_script:
        projects[":"] = ""
    modules = tuple(Module(project, directory) for project, directory in sorted(projects.items()))
    accessors = _accessors(projects)
    edges = []
    if root_script:
        try:
            edges.extend(_declarations(Module(":", ""), root_script, projects, accessors, issues))
        except TaskFileError as exc:
            issues.append(Issue(exc.filename, exc.field_name, exc.message))
    for module in modules:
        if module.id != ":":
            edges.extend(_read_module(module, fd, projects, accessors, issues))
    return GradleDependencies(modules, tuple(edges), tuple(issues))


def load_dependencies(root: Path) -> GradleDependencies:
    """Read settings and the selected build script for each included project."""
    try:
        with open_directory(root) as fd:
            return _discover(fd)
    except (OSError, ValueError) as exc:
        if isinstance(exc, TaskFileError):
            raise
        raise TaskFileError(Path("."), "root", "cannot open a symlink-free directory") from None
