"""Check a release tag against every version source and write the release notes.

Run by `.github/workflows/release.yml` with the pushed tag in `RELEASE_TAG`. Standard library
only. It reads three files of the checkout and writes the notes file it is given; it runs no
process, makes no network call and never creates a tag or a release.
"""

import argparse
import ast
import os
import re
import sys
import tomllib
from datetime import date
from pathlib import Path

NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION = rf"{NUMBER}\.{NUMBER}\.{NUMBER}"
TAG = re.compile(rf"v({VERSION})")
# CommonMark: an ATX heading or a code fence may be indented by up to three spaces.
HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t\r]|$)")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
RELEASE = re.compile(rf"##[ \t]+\[({VERSION})\](.*)")
COMMENT_START = re.compile(r" {0,3}<!--")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# Lines that render as no words: thematic breaks, setext underlines and link definitions.
RULE = re.compile(r" {0,3}(?:=+|-+|(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})[ \t]*")
LINK_DEFINITION = re.compile(
    r""" {0,3}\[[^\[\]]+\]:[ \t]*(?:<[^<>]*>|\S+)(?:[ \t]+(?:"[^"]*"|'[^']*'|\([^()]*\)))?[ \t]*"""
)
DATED = re.compile(r" - ([0-9]{4}-[0-9]{2}-[0-9]{2})")
INIT = "src/etat_major/__init__.py"
PYPROJECT = "pyproject.toml"
CHANGELOG = "CHANGELOG.md"
VERSION_ATTR = "etat_major.__version__"


class ReleaseError(ValueError):
    """A reason not to release, as one printable line."""


def parse_tag(tag: str) -> str:
    """Return the version named by a `vMAJOR.MINOR.PATCH` tag."""
    match = TAG.fullmatch(tag)
    if match is None:
        raise ReleaseError(f"tag {ascii(tag)} is not vMAJOR.MINOR.PATCH")
    return match.group(1)


def _read(root: Path, name: str) -> str:
    try:
        return (root / name).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ReleaseError(f"{name}: cannot be read ({type(error).__name__})") from None


def package_version(root: Path) -> str:
    """Return the package's `__version__`, bound once to a literal, without importing it."""
    try:
        tree = ast.parse(_read(root, INIT))
    except (SyntaxError, ValueError):
        raise ReleaseError(f"{INIT}: does not parse") from None
    literals = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    ]
    if _bindings(tree) != 1 or len(literals) != 1:
        raise ReleaseError(f"{INIT}: expected one literal __version__ assignment and no other")
    return str(literals[0])


def _bindings(tree: ast.Module) -> int:
    """Count the places that assign, change, delete, define or import `__version__`.

    Not seen: writes through `globals()`, an `except ... as` name and `import *`. Review has
    to catch those.
    """
    nodes = list(ast.walk(tree))
    stored = [
        n
        for n in nodes
        if isinstance(n, ast.Name) and n.id == "__version__" and not isinstance(n.ctx, ast.Load)
    ]
    imported = [
        n for n in nodes if isinstance(n, ast.alias) and "__version__" in (n.name, n.asname)
    ]
    defined = [
        n
        for n in nodes
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and n.name == "__version__"
    ]
    return len(stored) + len(imported) + len(defined)


def _lookup(value: object, *keys: str) -> object:
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def pyproject_version(root: Path, package: str) -> str:
    """Return the version pyproject.toml declares, directly or through the package."""
    try:
        data = tomllib.loads(_read(root, PYPROJECT))
    except tomllib.TOMLDecodeError:
        raise ReleaseError(f"{PYPROJECT}: does not parse") from None
    project = data.get("project")
    if not isinstance(project, dict):
        raise ReleaseError(f"{PYPROJECT}: project is not a table")
    if "version" in project:
        return str(project["version"])
    listed = project.get("dynamic")
    source = _lookup(data, "tool", "setuptools", "dynamic", "version")
    if isinstance(listed, list) and "version" in listed and source == {"attr": VERSION_ATTR}:
        return package
    raise ReleaseError(f"{PYPROJECT}: version is neither static nor read from {VERSION_ATTR}")


def _require_date(heading_rest: str, version: str) -> None:
    match = DATED.fullmatch(heading_rest.rstrip())
    try:
        if match is None:
            raise ValueError
        date.fromisoformat(match.group(1))
    except ValueError:
        raise ReleaseError(
            f"{CHANGELOG}: the {version} heading needs a release date, as `- YYYY-MM-DD`"
        ) from None


def _scan(markdown: str) -> list[tuple[str, int]]:
    """Pair each line with its heading level; 0 for other lines, fenced code and comments."""
    scanned, fence, comment = [], "", False
    for line in markdown.split("\n"):
        marker = FENCE.match(line)
        level = 0
        if comment:
            comment = "-->" not in line
        elif fence:
            if marker and marker.group(1).startswith(fence) and not marker.group(2).strip():
                fence = ""
        elif COMMENT_START.match(line):
            comment = "-->" not in line
        elif marker and not (marker.group(1)[0] == "`" and "`" in marker.group(2)):
            fence = marker.group(1)
        else:
            heading = HEADING.match(line)
            level = len(heading.group(1)) if heading else 0
        scanned.append((line.removesuffix("\r"), level))
    if fence:
        raise ReleaseError(f"{CHANGELOG}: a code fence is never closed")
    if comment:
        raise ReleaseError(f"{CHANGELOG}: a comment is never closed")
    return scanned


def _has_words(section: list[tuple[str, int]]) -> bool:
    """Tell whether anything but headings, comments, rules and link definitions is there."""
    text = COMMENT.sub("", "\n".join(line for line, level in section if not level))
    return any(
        line.strip() and not RULE.fullmatch(line) and not LINK_DEFINITION.fullmatch(line)
        for line in text.split("\n")
    )


def _releases(lines: list[tuple[str, int]]) -> list[tuple[int, str, str]]:
    """Return the line index, version and heading remainder of each release section."""
    found = []
    for index, (line, level) in enumerate(lines):
        match = RELEASE.match(line.strip()) if level == 2 else None
        if match:
            found.append((index, match.group(1), match.group(2)))
    return found


def release_notes(changelog: str, version: str) -> str:
    """Return the body of the dated changelog section for a version."""
    lines = _scan(changelog)
    found = [release for release in _releases(lines) if release[1] == version]
    if not found:
        raise ReleaseError(f"{CHANGELOG}: no section for {version}")
    if len(found) > 1:
        raise ReleaseError(f"{CHANGELOG}: more than one section for {version}")
    index, _, rest = found[0]
    _require_date(rest, version)
    start = index + 1
    end = next((i for i in range(start, len(lines)) if lines[i][1] in (1, 2)), len(lines))
    section = lines[start:end]
    if not _has_words(section):
        raise ReleaseError(f"{CHANGELOG}: the {version} section is empty or only headings")
    return "\n".join(line for line, _ in section).strip("\n").rstrip() + "\n"


def check_release(root: Path, tag: str) -> str:
    """Require the tag and every version source to agree, and return the release notes."""
    version = parse_tag(tag)
    package = package_version(root)
    sources = {INIT: package, PYPROJECT: pyproject_version(root, package)}
    for name, stated in sources.items():
        if stated != version:
            raise ReleaseError(f"{name}: version {ascii(stated)} does not match tag v{version}")
    changelog = _read(root, CHANGELOG)
    notes = release_notes(changelog, version)
    if _releases(_scan(changelog))[0][1] != version:
        raise ReleaseError(f"{CHANGELOG}: the top release section is not {version}")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="checkout to check")
    parser.add_argument("--notes-out", type=Path, help="file to write the release notes to")
    args = parser.parse_args(argv)
    try:
        notes = check_release(args.root, os.environ.get("RELEASE_TAG", ""))
        if args.notes_out:
            args.notes_out.write_text(notes, encoding="utf-8")
    except ReleaseError as error:
        print(f"release check: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        name = args.notes_out.name
        print(f"release check: {name}: cannot be written ({type(error).__name__})", file=sys.stderr)
        return 1
    print("release check: tag, versions and changelog agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
