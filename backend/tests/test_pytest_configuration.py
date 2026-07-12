import tomllib
from pathlib import Path


def test_default_pytest_options_exclude_live_ai() -> None:
    project_root = Path(__file__).parents[2]
    with (project_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]

    assert '-m "not live_ai"' in addopts
