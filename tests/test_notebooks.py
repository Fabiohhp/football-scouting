"""The notebooks are committed as run by `make notebooks`: no data needed to check them."""

import json

import pytest

from football_scouting.config import PROJECT_ROOT

NOTEBOOKS = sorted((PROJECT_ROOT / "notebooks").glob("*.ipynb"))


def test_the_notebooks_are_found():
    assert len(NOTEBOOKS) >= 8


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_a_notebook_ran_top_to_bottom_without_errors_or_warnings(path):
    code = [c for c in json.loads(path.read_text())["cells"] if c["cell_type"] == "code"]
    assert [c["execution_count"] for c in code] == list(range(1, len(code) + 1))
    outputs = [o for c in code for o in c["outputs"]]
    assert not [o for o in outputs if o["output_type"] == "error"]
    assert not [o for o in outputs if o.get("name") == "stderr"]  # warnings go to stderr
