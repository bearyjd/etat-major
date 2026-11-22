"""Discover and resolve convention plugins from repository-local included builds."""

import stat
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from etat_major.gradle_parse import INPUT_LIMIT_KIB, MAX_DEPTH, Script, parse_script, read_script
from etat_major.gradle_plugin_parse import (
    PLUGIN_ID,
    alias_accessor,
    class_blocks,
    module_applications,
    plugin_content,
    registrations,
    warn,
)
from etat_major.localfiles import (
    directory_names,
    entry_mode,
    open_directory,
    open_relative_directory,
    read_text_kib,
)
from etat_major.taskfile import TaskFileError
from etat_major.workspace import Issue

_ENTRY_LIMIT = 1000
_COMPOSITION_LIMIT = 32
_BUILD_EXCLUSIONS = {"build", "src"}
_KOTLIN_PATH = Path("src/main")


@dataclass(frozen=True)
class PluginDependency:
    target: str
    configuration: str
    test_only: bool
    file: str
    line: int


@dataclass(frozen=True)
class PluginApplication:
    id: str
    line: int


@dataclass(frozen=True)
class Implementation:
    name: str
    file: str
    dependencies: tuple[PluginDependency, ...]
    applies: tuple[PluginApplication, ...]


def _warning(issues: list[Issue], file: str, field: str, line: int, message: str) -> None:
    issue = Issue(file, field, f"line {line}: {message}", severity="warning", blocking=False)
    if issue not in issues:
        issues.append(issue)


def _file_warning(issues: list[Issue], path: Path, field: str, message: str) -> None:
    if not message.startswith("line "):
        message = f"line 1: {message}"
    issues.append(Issue(path.as_posix(), field, message, severity="warning", blocking=False))


@dataclass
class _Walker:
    issues: list[Issue]
    remaining: int = _ENTRY_LIMIT

    def entries(self, path: Path, fd: int) -> Iterator[tuple[Path, int]]:
        try:
            names = directory_names(fd, self.remaining, stop_at_limit=True)
        except OSError:
            _file_warning(self.issues, path, "directory", "cannot list directory")
            return
        if len(names) > self.remaining:
            _file_warning(
                self.issues, path, "directory", "convention plugin file probe limit exceeded"
            )
            self.remaining = 0
            return
        self.remaining -= len(names)
        for name in names:
            if name.startswith("."):
                continue
            child = path / name
            try:
                mode = entry_mode(child, fd)
            except OSError:
                _file_warning(self.issues, child, "file", "cannot inspect file")
                continue
            except ValueError as exc:
                _file_warning(self.issues, child, "file", str(exc))
                continue
            yield child, mode

    def directories(
        self, path: Path, fd: int, *, excluded: set[str]
    ) -> Iterator[tuple[Path, int, list[Path]]]:
        if len(path.parts) > MAX_DEPTH:
            _file_warning(self.issues, path, "directory", "directory depth limit exceeded")
            return
        entries = tuple(self.entries(path, fd))
        yield path, fd, [child for child, mode in entries if stat.S_ISREG(mode)]
        for child, mode in entries:
            if not stat.S_ISDIR(mode) or child.name in excluded:
                continue
            if not self.remaining:
                _file_warning(
                    self.issues, child, "directory", "convention plugin file probe limit exceeded"
                )
                return
            try:
                with open_directory(child, fd) as child_fd:
                    yield from self.directories(child, child_fd, excluded=excluded)
            except OSError:
                _file_warning(
                    self.issues, child, "directory", "cannot open a symlink-free directory"
                )


def _parse_kotlin(file: Path, fd: int, issues: list[Issue]) -> Script | None:
    try:
        return parse_script(read_text_kib(file, INPUT_LIMIT_KIB, dir_fd=fd), file)
    except TaskFileError as exc:
        _file_warning(issues, file, exc.field_name, exc.message)
    except (OSError, UnicodeError):
        _file_warning(issues, file, "file", "cannot read Kotlin source as UTF-8")
    except ValueError as exc:
        _file_warning(issues, file, "file", str(exc))
    return None


def _implementation(script: Script, name: str, block: int, issues: list[Issue]) -> Implementation:
    path = script.file.as_posix()
    requests, applications = plugin_content(script, block, issues)
    dependencies = tuple(
        PluginDependency(
            request.target,
            request.configuration,
            request.test_only,
            path,
            script.tokens[request.index].line,
        )
        for request in requests
        if request.target is not None
    )
    applies = tuple(
        PluginApplication(app.id, script.tokens[app.index].line) for app in applications
    )
    return Implementation(name, path, dependencies, applies)


def _implementations(
    path: Path, fd: int, names: set[str], walker: _Walker
) -> dict[str, Implementation | None]:
    implementations: dict[str, Implementation | None] = {}
    try:
        with open_relative_directory(_KOTLIN_PATH, fd) as kotlin_fd:
            for _, source_fd, files in walker.directories(
                path / _KOTLIN_PATH, kotlin_fd, excluded=set()
            ):
                for file in files:
                    if file.suffix != ".kt":
                        continue
                    script = _parse_kotlin(file, source_fd, walker.issues)
                    if script is None:
                        continue
                    for name, block in class_blocks(script):
                        if name in names:
                            implementations[name] = (
                                None
                                if name in implementations
                                else _implementation(script, name, block, walker.issues)
                            )
    except FileNotFoundError:
        pass
    except OSError:
        _file_warning(
            walker.issues,
            path / _KOTLIN_PATH,
            "directory",
            "cannot open a symlink-free Kotlin source directory",
        )
    return implementations


def _build_plugins(
    path: Path, fd: int, walker: _Walker
) -> Iterator[tuple[str, Implementation | None, Script, int]]:
    try:
        source = read_script(path, "build", fd)
        if source is None:
            return
        script = parse_script(source[1], source[0])
    except TaskFileError as exc:
        _file_warning(walker.issues, path / exc.filename, exc.field_name, exc.message)
        return
    found = tuple(registrations(script, walker.issues))
    if not found:
        return
    classes = _implementations(path, fd, {item.implementation for item in found}, walker)
    for item in found:
        implementation = classes.get(item.implementation)
        if implementation is None:
            warn(
                script,
                walker.issues,
                "implementationClass",
                item.index,
                "missing or ambiguous convention plugin implementation",
            )
        yield item.id, implementation, script, item.index


def discover_plugins(
    settings: Script, includes: dict[str, int], root_fd: int, issues: list[Issue]
) -> dict[str, Implementation | None]:
    plugins: dict[str, Implementation | None] = {}
    walker = _Walker(issues)
    for included, index in includes.items():
        if not walker.remaining:
            warn(
                settings,
                issues,
                "includeBuild",
                index,
                "convention plugin file probe limit exceeded",
            )
            break
        path = Path(included)
        try:
            with open_relative_directory(path, root_fd) as fd:
                for directory, directory_fd, files in walker.directories(
                    path, fd, excluded=_BUILD_EXCLUSIONS
                ):
                    if not any(file.name in {"build.gradle.kts", "build.gradle"} for file in files):
                        continue
                    for plugin_id, body, script, registration in _build_plugins(
                        directory, directory_fd, walker
                    ):
                        if plugin_id in plugins:
                            warn(
                                script,
                                issues,
                                "gradlePlugin",
                                registration,
                                "ambiguous convention plugin ID",
                            )
                            body = None
                        plugins[plugin_id] = body
        except OSError:
            warn(
                settings,
                issues,
                "includeBuild",
                index,
                "composite build not followed: cannot open a symlink-free directory",
            )
    return plugins


def read_plugin_aliases(root_fd: int, issues: list[Issue]) -> dict[str, str]:
    catalog = Path("gradle/libs.versions.toml")
    try:
        with open_relative_directory(catalog.parent, root_fd) as fd:
            text = read_text_kib(catalog, INPUT_LIMIT_KIB, dir_fd=fd)
        plugins = tomllib.loads(text).get("plugins", {})
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError):
        _file_warning(issues, catalog, "plugins", "cannot read a bounded symlink-free TOML catalog")
        return {}
    if not isinstance(plugins, dict):
        _file_warning(issues, catalog, "plugins", "expected a TOML plugin table")
        return {}
    aliases = {}
    for key, value in plugins.items():
        name = alias_accessor(key)
        plugin_id = value.get("id") if isinstance(value, dict) else None
        if isinstance(value, str) and ":" in value:
            plugin_id = value.split(":", 1)[0]
        if name in aliases:
            aliases[name] = ""
        elif isinstance(plugin_id, str) and PLUGIN_ID.fullmatch(plugin_id):
            aliases[name] = plugin_id
    return aliases


def _expansion(
    application: PluginApplication,
    path: str,
    plugins: dict[str, Implementation | None],
    depths: dict[str, int],
    active: set[str],
    issues: list[Issue],
) -> Iterator[tuple[str, Implementation]]:
    plugin_id = application.id
    implementation = plugins.get(plugin_id)
    if implementation is None:
        return
    if plugin_id in active:
        _warning(issues, path, "plugins", application.line, "convention plugin composition cycle")
        return
    depth = len(active)
    previous_depth = depths.get(plugin_id)
    if previous_depth is not None and depth >= previous_depth:
        return
    if depth >= _COMPOSITION_LIMIT:
        _warning(
            issues,
            path,
            "plugins",
            application.line,
            "convention plugin composition depth limit exceeded",
        )
        return
    depths[plugin_id] = depth
    active.add(plugin_id)
    if previous_depth is None:
        yield plugin_id, implementation
    for nested in implementation.applies:
        yield from _expansion(nested, implementation.file, plugins, depths, active, issues)
    active.remove(plugin_id)


def applied_plugins(
    script: Script,
    plugins: dict[str, Implementation | None],
    aliases: dict[str, str],
    issues: list[Issue],
) -> Iterator[tuple[str, Implementation]]:
    depths: dict[str, int] = {}
    for app in module_applications(script, aliases, issues):
        application = PluginApplication(app.id, script.tokens[app.index].line)
        yield from _expansion(application, script.file.as_posix(), plugins, depths, set(), issues)
