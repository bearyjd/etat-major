import re
from importlib import metadata

import etat_major


def test_package_exposes_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", etat_major.__version__)


def test_version_matches_installed_metadata():
    assert etat_major.__version__ == metadata.version("etat-major")
