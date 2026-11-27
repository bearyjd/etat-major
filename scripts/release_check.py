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
SECTION = re.compile(r"^## ", re.MULTILINE)
RELEASE = re.compile(rf"^## \[({VERSION})\](.*)$", re.MULTILINE)
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
    """Return the single literal `__version__` of the package, without importing it."""
    try:
        tree = ast.parse(_read(root, INIT))
    except (SyntaxError, ValueError):
        raise ReleaseError(f"{INIT}: does not parse") from None
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    ]
    if len(values) != 1 or not isinstance(values[0], ast.Constant):
        raise ReleaseError(f"{INIT}: expected one literal __version__ assignment")
    return str(values[0].value)


def pyproject_version(root: Path, package: str) -> str:
    """Return the version pyproject.toml declares, directly or through the package."""
    try:
        data = tomllib.loads(_read(root, PYPROJECT))
    except tomllib.TOMLDecodeError:
        raise ReleaseError(f"{PYPROJECT}: does not parse") from None
    project = data.get("project", {})
    if "version" in project:
        return str(project["version"])
    dynamic = data.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version")
    if "version" in project.get("dynamic", []) and dynamic == {"attr": VERSION_ATTR}:
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


def release_notes(changelog: str, version: str) -> str:
    """Return the body of the dated changelog section for a version."""
    found = [match for match in RELEASE.finditer(changelog) if match.group(1) == version]
    if not found:
        raise ReleaseError(f"{CHANGELOG}: no section for {version}")
    if len(found) > 1:
        raise ReleaseError(f"{CHANGELOG}: more than one section for {version}")
    _require_date(found[0].group(2), version)
    following = SECTION.search(changelog, found[0].end())
    body = changelog[found[0].end() : following.start() if following else None].strip()
    if not body:
        raise ReleaseError(f"{CHANGELOG}: the {version} section is empty")
    return body + "\n"


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
    top = RELEASE.search(changelog)
    if top is None or top.group(1) != version:
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
