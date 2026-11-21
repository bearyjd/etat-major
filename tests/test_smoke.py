import etat_major


def test_package_exposes_version():
    assert etat_major.__version__ == "0.1.0"
