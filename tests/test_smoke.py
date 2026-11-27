import json
import re
from importlib import metadata
from pathlib import Path

import pytest

import etat_major

ROOT = Path(__file__).resolve().parents[1]


def installed_from_this_checkout() -> metadata.Distribution | None:
    """The installed distribution, only when it was installed from this source tree."""
    try:
        found = metadata.distribution("etat-major")
    except metadata.PackageNotFoundError:
        return None
    origin = json.loads(found.read_text("direct_url.json") or "{}")
    return found if origin.get("url") == ROOT.as_uri() else None


def test_package_exposes_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", etat_major.__version__)


def test_version_matches_installed_metadata():
    found = installed_from_this_checkout()
    if found is None:
        pytest.skip("etat-major is not installed from this checkout")
    assert found.version == etat_major.__version__
