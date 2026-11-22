from pathlib import Path

import pytest

from etat_major.floorplan import FloorplanIndex


def test_overlay_classifies_file_ids():
    from etat_major.floorplan import load_plan
    from etat_major.overlay import classify_files

    plan = load_plan(Path(__file__).parent / "fixtures" / "floorplan" / "plan.json")
    graph = FloorplanIndex(
        frozenset({"ignored"}), frozenset({"src/etat_major/wiring.py", "old.py"})
    )
    classes = classify_files(plan, graph)
    assert classes == {
        "f:src/etat_major/wiring.py": "built",
        "f:src/etat_major/repo_index.py": "planned-only",
        "f:tests/test_wiring.py": "planned-only",
        "f:old.py": "existing",
    }
    with pytest.raises(TypeError):
        classes["f:old.py"] = "built"


def test_overlay_uses_renamed_graph_id():
    from etat_major.floorplan import load_plan
    from etat_major.overlay import classify_files

    plan = load_plan(Path(__file__).parent / "fixtures" / "floorplan" / "plan.json")
    graph = FloorplanIndex(frozenset(), frozenset({"adapter.py"}))
    assert classify_files(plan, graph, {"src/etat_major/wiring.py": "adapter.py"}) == {
        "f:adapter.py": "built",
        "f:src/etat_major/repo_index.py": "planned-only",
        "f:tests/test_wiring.py": "planned-only",
    }
