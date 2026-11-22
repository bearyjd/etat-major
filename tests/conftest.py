import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
DEMO = FIXTURES / "demo-workspace"
GRAPH = FIXTURES / "floorplan" / "graph.json"


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    """A writable copy of the demo workspace."""
    dest = tmp_path / "workspace"
    shutil.copytree(DEMO, dest)
    return dest


@pytest.fixture
def graph_file(tmp_path: Path) -> Path:
    """A writable copy of the recorded Floorplan graph."""
    dest = tmp_path / "graph.json"
    shutil.copy(GRAPH, dest)
    return dest
