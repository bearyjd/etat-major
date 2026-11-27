"""Every place that states the package version must state the same one."""

import re
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import etat_major
from etat_major.cli import main

ROOT = Path(__file__).resolve().parents[1]
RELEASE_HEADING = re.compile(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]", re.MULTILINE)


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_takes_its_version_from_the_package():
    data = pyproject()
    assert "version" not in data["project"]
    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "etat_major.__version__"}


def test_version_output_states_the_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"etat-major {etat_major.__version__}\n"


def test_version_output_ignores_stale_installed_metadata(monkeypatch, capsys):
    monkeypatch.setattr(metadata, "version", lambda _name: "0.0.0")
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out == f"etat-major {etat_major.__version__}\n"


def test_top_changelog_release_is_the_package_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = RELEASE_HEADING.findall(text)
    assert headings, "CHANGELOG.md has no release heading"
    assert headings[0] == etat_major.__version__
