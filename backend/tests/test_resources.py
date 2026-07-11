from pathlib import Path

from app.resources import resource_root


def test_resource_root_uses_an_explicit_frozen_directory(tmp_path: Path) -> None:
    assert resource_root(tmp_path) == tmp_path


def test_resource_root_defaults_to_repository_root() -> None:
    assert (resource_root() / "alembic.ini").is_file()
    assert (resource_root() / "backend" / "migrations").is_dir()
