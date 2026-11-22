"""Recognize literal convention plugin registrations, applications, and dependencies."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from etat_major.gradle_parse import Request, Script, dependency_block_requests, statement_end
from etat_major.workspace import Issue

PLUGIN_ID = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
_CLASS_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", re.ASCII)
_ALIAS_SEPARATOR = re.compile(r"[-_.]")


@dataclass(frozen=True)
class Registration:
    id: str
    implementation: str
    index: int


@dataclass(frozen=True)
class Application:
    id: str
    index: int


def warn(script: Script, issues: list[Issue], field: str, index: int, message: str) -> None:
    issues.append(script.issue(field, index, message, blocking=False))


def _literal(script: Script, start: int, stop: int) -> str:
    return (
        (script.tokens[start].literal or "")
        if stop == start + 1 and start < len(script.tokens)
        else ""
    )


def _call_argument(script: Script, start: int) -> tuple[int, int]:
    if script.values(start, start + 1) == ("(",):
        args = tuple(script.arguments(start + 1, script.closing[start]))
        if len(args) == 1:
            return args[0]
    return start, start


def _block_children(script: Script, start: int, stop: int, name: str) -> Iterator[int]:
    for i in script.siblings(start, stop):
        if script.values(i, i + 2) == (name, "{") and script.statement_start(i):
            yield i + 1


def _registration_fields(script: Script, block: int) -> dict[str, str]:
    fields: dict[str, str] = {}
    stop = script.closing[block]
    for i in script.siblings(block + 1, stop):
        field = script.tokens[i].value
        if field not in {"id", "implementationClass"} or not script.statement_start(i):
            continue
        value = ""
        if i + 2 < stop and script.values(i + 1, i + 2) == ("=",):
            token, following = script.tokens[i + 2 : i + 4]
            if (
                following.value in {";", "}"}
                or following.line > token.line
                and following.value not in {".", "+", "?", "["}
            ):
                value = token.literal or ""
        fields[field] = value if field not in fields else ""
    return fields


def _registrations(script: Script, block: int, issues: list[Issue]) -> Iterator[Registration]:
    for i in script.siblings(block + 1, script.closing[block]):
        if script.tokens[i].value not in {"register", "create"}:
            continue
        fields: dict[str, str] = {}
        if script.statement_start(i) and script.values(i + 1, i + 2) == ("(",):
            end = script.closing[i + 1] + 1
            if _literal(script, *_call_argument(script, i + 1)) and script.values(end, end + 1) == (
                "{",
            ):
                fields = _registration_fields(script, end)
        plugin_id = fields.get("id", "")
        implementation = fields.get("implementationClass", "")
        if PLUGIN_ID.fullmatch(plugin_id) and _CLASS_NAME.fullmatch(implementation):
            yield Registration(plugin_id, implementation, i)
        else:
            warn(script, issues, "gradlePlugin", i, "unsupported convention plugin registration")


def registrations(script: Script, issues: list[Issue]) -> Iterator[Registration]:
    for block in _block_children(script, 0, len(script.tokens), "gradlePlugin"):
        for plugins in _block_children(script, block + 1, script.closing[block], "plugins"):
            yield from _registrations(script, plugins, issues)


def alias_accessor(alias: str) -> str:
    return ".".join(_ALIAS_SEPARATOR.split(alias))


def _alias(script: Script, start: int, stop: int, aliases: dict[str, str]) -> str:
    values = script.values(start, stop)
    if (
        len(values) < 5
        or len(values) % 2 == 0
        or values[:4] != ("libs", ".", "plugins", ".")
        or values[5::2] != (".",) * ((len(values) - 5) // 2)
    ):
        return ""
    return aliases.get(".".join(values[4::2]), "")


def _applies(script: Script, index: int) -> bool | None:
    if script.values(index, index + 2) == (".", "version"):
        index += 1
    values = script.values(index, index + 2)
    if values == ("version", "("):
        index = script.closing[index + 1] + 1
    elif values[:1] == ("version",):
        index += 2
    if script.values(index, index + 1) == (".",):
        index += 1
        if script.values(index, index + 1) != ("apply",):
            return None
    if script.values(index, index + 1) != ("apply",):
        return True
    if script.values(index + 1, index + 2) == ("(",):
        argument = script.values(*_call_argument(script, index + 1))
    else:
        argument = script.values(index + 1, index + 2)
    return True if argument == ("true",) else False if argument == ("false",) else None


def _module_plugin_block(
    script: Script, block: int, aliases: dict[str, str], issues: list[Issue]
) -> Iterator[Application]:
    stop = script.closing[block]
    direct = set(script.siblings(block + 1, stop))
    for i in range(block + 1, stop):
        directive = script.tokens[i].value
        if directive not in {"alias", "id"}:
            continue
        if i not in direct or not script.statement_start(i):
            following = script.tokens[i + 1]
            if following.value != "(" and following.literal is None:
                continue
            warn(script, issues, "plugins", i, "unsupported plugin application placement")
            continue
        start = i + 1
        if script.values(start, start + 1) == ("(",):
            arg = _call_argument(script, start)
            end = script.closing[start] + 1
        else:
            arg = start, start + 1
            end = start + 1
        applied = _applies(script, end)
        if applied is False:
            continue
        plugin_id = (
            _alias(script, *arg, aliases) if directive == "alias" else _literal(script, *arg)
        )
        if applied and PLUGIN_ID.fullmatch(plugin_id):
            yield Application(plugin_id, i)
        else:
            warn(script, issues, "plugins", i, "unsupported or unresolved plugin application")


def _plugin_application(
    script: Script, i: int, limit: int, issues: list[Issue]
) -> Application | None:
    start, stop = _call_argument(script, i + 1)
    qualified = i >= 2 and script.values(i - 2, i) == ("pluginManager", ".")
    if not qualified:
        if script.values(i + 1, i + 3) == ("plugin", ":"):
            start, stop = i + 1, statement_end(script, i + 1, limit)
        if script.values(start, start + 2) not in {("plugin", "="), ("plugin", ":")}:
            return None
        start += 2
    plugin_id = _literal(script, start, stop)
    if PLUGIN_ID.fullmatch(plugin_id):
        return Application(plugin_id, i)
    warn(script, issues, "plugins", i, "unsupported plugin application expression")
    return None


def module_applications(
    script: Script, aliases: dict[str, str], issues: list[Issue]
) -> Iterator[Application]:
    stop = len(script.tokens)
    for block in _block_children(script, 0, stop, "plugins"):
        yield from _module_plugin_block(script, block, aliases, issues)
    for i in script.siblings(0, stop):
        if script.tokens[i].value == "apply" and script.statement_start(i):
            application = _plugin_application(script, i, stop, issues)
            if application:
                yield application


def _package(script: Script, top_level: list[int]) -> str:
    for i in top_level:
        if script.tokens[i].value == "package":
            line = script.tokens[i].line
            words = []
            for token in script.tokens[i + 1 :]:
                if token.line != line or token.value == ";":
                    break
                words.append(token.value)
            return "".join(words)
    return ""


def class_blocks(script: Script) -> Iterator[tuple[str, int]]:
    top_level = list(script.siblings(0, len(script.tokens)))
    package = _package(script, top_level)
    for position, i in enumerate(top_level):
        if script.tokens[i].value != "class" or i + 1 >= len(script.tokens):
            continue
        short_name = script.tokens[i + 1].value
        if not _CLASS_NAME.fullmatch(short_name):
            continue
        for next_position in range(position + 2, len(top_level)):
            child = top_level[next_position]
            value = script.tokens[child].value
            if value == "{":
                yield f"{package}.{short_name}" if package else short_name, child
                break
            if value in {";", "class", "interface", "object", "fun", "val", "var"}:
                break


def _receiver_block(script: Script, start: int, receiver: str) -> int | None:
    if script.values(start, start + 5) == ("with", "(", receiver, ")", "{"):
        return start + 4
    if script.values(start, start + 2) == (receiver, "."):
        if script.values(start + 2, start + 4) in {("run", "{"), ("apply", "{")}:
            return start + 3
    return None


def _apply_bodies(script: Script, block: int) -> Iterator[tuple[int, int, str]]:
    for i in script.siblings(block + 1, script.closing[block]):
        if script.values(i, i + 3) != ("fun", "apply", "("):
            continue
        start, stop = _call_argument(script, i + 2)
        argument = script.values(start, stop)
        if not argument or argument[1:] not in {
            (":", "Project"),
            (":", "org", ".", "gradle", ".", "api", ".", "Project"),
        }:
            continue
        receiver = argument[0]
        body = script.closing[i + 2] + 1
        if script.values(body, body + 2) == (":", "Unit"):
            body += 2
        if script.values(body, body + 1) == ("{",):
            yield body + 1, script.closing[body], receiver
        elif script.values(body, body + 1) == ("=",):
            expression = _receiver_block(script, body + 1, receiver)
            if expression is not None:
                yield expression + 1, script.closing[expression], receiver


def _unparsed_scope(script: Script, start: int, stop: int, issues: list[Issue]) -> None:
    for i in range(start, stop):
        if script.values(i, i + 2) == ("dependencies", "{"):
            warn(
                script, issues, "dependencies", i, "unsupported convention plugin dependency scope"
            )
        elif script.values(i, i + 3) == ("pluginManager", ".", "apply") or (
            script.values(i, i + 3) in {("apply", "(", "plugin"), ("apply", "plugin", ":")}
        ):
            warn(script, issues, "plugins", i, "unsupported convention plugin application scope")


def _body_items(
    script: Script, start: int, stop: int, receiver: str, issues: list[Issue]
) -> Iterator[Request | Application]:
    i = start
    while i < stop:
        if not script.statement_start(i):
            _unparsed_scope(script, i, script.closing[i] + 1, issues)
            i = script.closing[i] + 1
            continue
        wrapper = _receiver_block(script, i, receiver)
        if wrapper is not None:
            end = script.closing[wrapper]
            yield from _body_items(script, wrapper + 1, end, receiver, issues)
            i = end + 1
            continue
        directive = i + 2 if script.values(i, i + 2) == (receiver, ".") else i
        if script.values(directive, directive + 2) == ("dependencies", "{"):
            for request in dependency_block_requests(script, directive + 1, convention=True):
                if request.target is None or request.accessor:
                    warn(
                        script,
                        issues,
                        "dependencies",
                        request.index,
                        "unsupported convention plugin dependency expression",
                    )
                else:
                    yield request
            i = script.closing[directive + 1] + 1
            continue
        if script.values(directive, directive + 3) == ("pluginManager", ".", "apply"):
            directive += 2
        if script.values(directive, directive + 1) == ("apply",):
            application = _plugin_application(script, directive, stop, issues)
            if application:
                yield application
            i = script.closing[directive + 1] + 1 if directive + 1 < stop else stop
            continue
        end = script.closing[i] + 1
        _unparsed_scope(script, i, end, issues)
        i = end


def plugin_content(
    script: Script, block: int, issues: list[Issue]
) -> tuple[tuple[Request, ...], tuple[Application, ...]]:
    requests, applications = [], []
    for start, stop, receiver in _apply_bodies(script, block):
        for item in _body_items(script, start, stop, receiver, issues):
            if isinstance(item, Request):
                requests.append(item)
            else:
                applications.append(item)
    return tuple(requests), tuple(applications)
