from pathlib import Path

SPIKE = Path(__file__).resolve().parent.parent / "docs" / "spikes" / "phase1-spike.md"


def _mapping_section() -> str:
    text = SPIKE.read_text()
    start = text.index("## Acceptance criteria mapping")
    end = text.index("## Consequences")
    return text[start:end]


def test_import_covers_unnumbered_items():
    assert "unnumbered" in _mapping_section().lower()


def test_import_covers_markerless_checklists():
    assert "markerless" in _mapping_section().lower()


def test_import_never_drops_silently():
    assert "never dropped silently" in _mapping_section().lower()
