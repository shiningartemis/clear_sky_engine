from pathlib import Path

from app.config import AppConfig, AppPaths


def test_app_paths_are_derived_from_local_app_data(tmp_path: Path) -> None:
    paths = AppPaths.from_local_app_data(tmp_path)

    assert paths.root == tmp_path / "ClearSkyEngine"
    assert paths.database_path == paths.root / "data" / "app.db"
    assert paths.maps_dir == paths.root / "content" / "maps"
    assert paths.logs_dir == paths.root / "logs"
    assert paths.backups_dir == paths.root / "backups"


def test_app_paths_create_all_writable_directories(tmp_path: Path) -> None:
    paths = AppPaths.from_local_app_data(tmp_path)

    paths.create_directories()

    assert paths.database_path.parent.is_dir()
    assert paths.maps_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.backups_dir.is_dir()


def test_app_config_uses_project_version_and_paths(tmp_path: Path) -> None:
    config = AppConfig.for_local_app_data(tmp_path)

    assert config.app_version == "0.1.0"
    assert config.paths.root == tmp_path / "ClearSkyEngine"
