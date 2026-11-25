from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace

TOP_KEYS = {"project", "features", "components", "tasks", "sources", "issues", "version"}


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def test_project_json_gains_no_discover_key(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        payload = client.get("/project.json").json()
    assert set(payload) == TOP_KEYS
    assert not any("discover" in key for key in _keys(payload))
