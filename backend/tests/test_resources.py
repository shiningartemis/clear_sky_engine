from pathlib import Path

from app.config import AppConfig
from app.main import create_app
from app.resources import resource_root

DEFAULT_MAP_NAMES = {
    "冒险者工会.png",
    "商店街.png",
    "地下城.png",
    "学校.png",
    "家.png",
    "总地图.png",
    "旅店.png",
}


def test_resource_root_uses_an_explicit_frozen_directory(tmp_path: Path) -> None:
    assert resource_root(tmp_path) == tmp_path


def test_resource_root_defaults_to_repository_root() -> None:
    assert (resource_root() / "alembic.ini").is_file()
    assert (resource_root() / "backend" / "migrations").is_dir()


def test_packaged_defaults_contain_exactly_the_seven_maps() -> None:
    maps_dir = (
        resource_root() / "backend" / "src" / "app" / "resources" / "default_content" / "maps"
    )

    image_names = {path.name for path in maps_dir.iterdir() if path.suffix.lower() != ".json"}

    assert image_names == DEFAULT_MAP_NAMES
    assert (maps_dir / "map_manifest.json").is_file()
    assert not {"天.jpg", "莫莉莉.png", "安可儿.png"} & image_names


def test_create_app_bootstraps_maps_from_the_selected_runtime_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    defaults = runtime_root / "backend" / "src" / "app" / "resources" / "default_content" / "maps"
    defaults.mkdir(parents=True)
    (defaults / "map_manifest.json").write_text('{"version":1,"scenes":[]}', encoding="utf-8")
    (defaults / "总地图.png").write_bytes(b"packaged")
    config = AppConfig.for_local_app_data(tmp_path / "local")

    app = create_app(config, resource_directory=runtime_root)

    assert app is not None
    assert (config.paths.maps_dir / "总地图.png").read_bytes() == b"packaged"


def test_pyinstaller_spec_includes_default_content() -> None:
    spec = (resource_root() / "clear_sky_engine.spec").read_text(encoding="utf-8")

    assert '"resources" / "default_content"' in spec
    assert '"backend/src/app/resources/default_content"' in spec
