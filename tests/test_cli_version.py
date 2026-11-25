from importlib import metadata

import pytest

import etat_major
from etat_major import cli
from etat_major.cli import main


def test_version_flag_prints_one_line_and_exits_0(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out == f"etat-major {metadata.version('etat-major')}\n"
    assert out == f"etat-major {etat_major.__version__}\n"


def test_version_falls_back_to_package_version_when_metadata_missing(monkeypatch, capsys):
    def missing(_name: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(cli.metadata, "version", missing)
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"etat-major {etat_major.__version__}\n"
