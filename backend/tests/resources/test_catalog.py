import json
import os
from inspect import signature
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.assets import create_asset_router
from app.resources import bootstrap as resource_bootstrap
from app.resources.bootstrap import ensure_default_maps
from app.resources.catalog import (
    AssetNotFoundError,
    InvalidMapManifestError,
    InvalidResourceNameError,
    ResourceCatalog,
)

JPEG_BYTES = b"\xff\xd8\xff\xe0"
PNG_BYTES = b"\x89PNG\r\n\x1a\n"
GIF87A_BYTES = b"GIF87a"
GIF89A_BYTES = b"GIF89a"
WEBP_BYTES = b"RIFF\x04\x00\x00\x00WEBP"
AVIF_BYTES = b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifmif1"
BMP_BYTES = b"BM"


def _write_manifest(defaults: Path, scenes: list[dict[str, object]]) -> None:
    defaults.mkdir(parents=True, exist_ok=True)
    (defaults / "map_manifest.json").write_text(
        json.dumps({"version": 1, "scenes": scenes}, ensure_ascii=False),
        encoding="utf-8",
    )


def _scene(
    scene_id: str = "the_world_map",
    *,
    display_name: str = "总地图",
    file_stem: str = "总地图",
) -> dict[str, object]:
    return {
        "scene_id": scene_id,
        "display_name": display_name,
        "kind": "the_world_map",
        "file_stem": file_stem,
        "order": 0,
        "anchor": None,
    }


def _make_directory_link_or_skip(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"当前环境不能创建目录符号链接: {error}")


def test_character_asset_priority_is_deterministic(tmp_path: Path) -> None:
    role_dir = tmp_path / "characters" / "天"
    role_dir.mkdir(parents=True)
    (role_dir / "天.png").write_bytes(PNG_BYTES)
    (role_dir / "天.jpg").write_bytes(JPEG_BYTES)

    asset = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", tmp_path).resolve_portrait(
        "天"
    )

    assert asset.path.name == "天.jpg"
    assert asset.media_type == "image/jpeg"


def test_map_asset_prefers_jpg_before_png(tmp_path: Path) -> None:
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "总地图.png").write_bytes(PNG_BYTES)
    (maps / "总地图.jpg").write_bytes(JPEG_BYTES)

    asset = ResourceCatalog(maps, tmp_path / "characters", tmp_path).resolve_map("总地图")

    assert asset.path.name == "总地图.jpg"


def test_generic_character_resolver_supports_future_description_stems(tmp_path: Path) -> None:
    role_dir = tmp_path / "characters" / "天"
    role_dir.mkdir(parents=True)
    (role_dir / "微笑.webp").write_bytes(WEBP_BYTES)
    catalog = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", tmp_path)

    asset = catalog.resolve_character_asset("天", "微笑")

    assert asset.path.name == "微笑.webp"
    assert asset.media_type == "image/webp"


@pytest.mark.parametrize(
    ("extension", "content"),
    [(".jpg", b"<html>not an image</html>"), (".png", b"arbitrary bytes")],
)
def test_renamed_non_image_content_is_rejected(
    tmp_path: Path, extension: str, content: bytes
) -> None:
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / f"总地图{extension}").write_bytes(content)
    catalog = ResourceCatalog(maps, tmp_path / "characters", tmp_path)

    with pytest.raises(AssetNotFoundError):
        catalog.resolve_map("总地图")


@pytest.mark.parametrize(
    ("extension", "content", "expected_media_type"),
    [
        (".jpg", JPEG_BYTES, "image/jpeg"),
        (".jpeg", JPEG_BYTES, "image/jpeg"),
        (".png", PNG_BYTES, "image/png"),
        (".gif", GIF87A_BYTES, "image/gif"),
        (".gif", GIF89A_BYTES, "image/gif"),
        (".webp", WEBP_BYTES, "image/webp"),
        (".avif", AVIF_BYTES, "image/avif"),
        (".bmp", BMP_BYTES, "image/bmp"),
    ],
)
def test_every_allowed_character_type_requires_a_verified_signature(
    tmp_path: Path,
    extension: str,
    content: bytes,
    expected_media_type: str,
) -> None:
    role_dir = tmp_path / "characters" / "天"
    role_dir.mkdir(parents=True)
    (role_dir / f"天{extension}").write_bytes(content)
    catalog = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", tmp_path)

    asset = catalog.resolve_portrait("天")

    assert asset.media_type == expected_media_type


def test_media_type_comes_from_content_instead_of_extension(tmp_path: Path) -> None:
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "总地图.jpg").write_bytes(PNG_BYTES)
    catalog = ResourceCatalog(maps, tmp_path / "characters", tmp_path)

    asset = catalog.resolve_map("总地图")

    assert asset.path.name == "总地图.jpg"
    assert asset.media_type == "image/png"


def test_missing_asset_is_reported(tmp_path: Path) -> None:
    maps = tmp_path / "maps"
    maps.mkdir()
    catalog = ResourceCatalog(maps, tmp_path / "characters", tmp_path)

    with pytest.raises(AssetNotFoundError, match="总地图"):
        catalog.resolve_map("总地图")


@pytest.mark.parametrize("name", ["..", ".", "../逃逸", "子目录/图片", r"子目录\图片"])
def test_parent_or_nested_paths_are_rejected(tmp_path: Path, name: str) -> None:
    catalog = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", tmp_path)

    with pytest.raises(InvalidResourceNameError):
        catalog.resolve_character_asset("天", name)

    with pytest.raises(InvalidResourceNameError):
        catalog.resolve_character_asset(name, "天")


def test_svg_is_never_selected_as_character_asset(tmp_path: Path) -> None:
    role_dir = tmp_path / "characters" / "天"
    role_dir.mkdir(parents=True)
    (role_dir / "天.svg").write_text("<svg/>", encoding="utf-8")
    catalog = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", tmp_path)

    with pytest.raises(AssetNotFoundError):
        catalog.resolve_portrait("天")


def test_file_symlink_cannot_escape_the_character_directory(tmp_path: Path) -> None:
    role_dir = tmp_path / "characters" / "天"
    role_dir.mkdir(parents=True)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(JPEG_BYTES)
    link = role_dir / "天.jpg"
    try:
        os.symlink(outside, link)
    except OSError as error:
        pytest.skip(f"当前环境不能创建符号链接: {error}")

    catalog = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", tmp_path)

    with pytest.raises(InvalidResourceNameError):
        catalog.resolve_portrait("天")


def test_catalog_rejects_maps_root_linked_outside_content_tree(tmp_path: Path) -> None:
    content = tmp_path / "content"
    characters = content / "characters"
    characters.mkdir(parents=True)
    outside_maps = tmp_path / "outside-maps"
    outside_maps.mkdir()
    (outside_maps / "总地图.png").write_bytes(PNG_BYTES)
    linked_maps = content / "maps"
    _make_directory_link_or_skip(outside_maps, linked_maps)

    with pytest.raises(InvalidResourceNameError):
        catalog = ResourceCatalog(linked_maps, characters, tmp_path)
        catalog.resolve_map("总地图")


def test_catalog_rejects_character_root_with_linked_ancestor(tmp_path: Path) -> None:
    application_root = tmp_path / "application"
    application_root.mkdir()
    outside_content = tmp_path / "outside-content"
    role_dir = outside_content / "characters" / "天"
    role_dir.mkdir(parents=True)
    (outside_content / "maps").mkdir()
    (role_dir / "天.jpg").write_bytes(JPEG_BYTES)
    linked_content = application_root / "content"
    _make_directory_link_or_skip(outside_content, linked_content)

    with pytest.raises(InvalidResourceNameError):
        catalog = ResourceCatalog(linked_content / "maps", linked_content / "characters", tmp_path)
        catalog.resolve_portrait("天")


def test_default_map_bootstrap_rejects_target_linked_outside_content_tree(
    tmp_path: Path,
) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "总地图.png").write_bytes(PNG_BYTES)
    content = tmp_path / "content"
    content.mkdir()
    outside_maps = tmp_path / "outside-maps"
    outside_maps.mkdir()
    linked_maps = content / "maps"
    _make_directory_link_or_skip(outside_maps, linked_maps)

    with pytest.raises(InvalidResourceNameError):
        ensure_default_maps(defaults, linked_maps)

    assert not (outside_maps / "总地图.png").exists()


def test_default_maps_copy_only_missing_files(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    target = tmp_path / "maps"
    defaults.mkdir()
    target.mkdir()
    (defaults / "总地图.png").write_bytes(b"new")
    (defaults / "家.png").write_bytes(b"home")
    (defaults / "map_manifest.json").write_text("{}", encoding="utf-8")
    (target / "总地图.png").write_bytes(b"user")

    ensure_default_maps(defaults, target)

    assert (target / "总地图.png").read_bytes() == b"user"
    assert (target / "家.png").read_bytes() == b"home"
    assert not (target / "map_manifest.json").exists()


def test_default_map_bootstrap_public_signature_has_no_test_seam() -> None:
    assert list(signature(ensure_default_maps).parameters) == ["default_maps_dir", "maps_dir"]


def test_default_map_copy_race_preserves_new_user_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    defaults = tmp_path / "defaults"
    target = tmp_path / "maps"
    defaults.mkdir()
    target.mkdir()
    (defaults / "总地图.png").write_bytes(b"default")

    helper_name = "_copy_exclusive"
    copy_exclusive = getattr(resource_bootstrap, helper_name)
    assert callable(copy_exclusive)

    def create_user_file_then_copy(source: Path, destination: Path) -> None:
        destination.write_bytes(b"user")
        copy_exclusive(source, destination)

    monkeypatch.setattr(resource_bootstrap, helper_name, create_user_file_then_copy)

    ensure_default_maps(defaults, target)

    assert (target / "总地图.png").read_bytes() == b"user"


def test_duplicate_manifest_scene_ids_are_rejected(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    _write_manifest(defaults, [_scene(), _scene()])
    catalog = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", defaults)

    with pytest.raises(InvalidMapManifestError, match="scene_id"):
        catalog.load_map_manifest()


async def test_map_file_response_disables_browser_cache(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "总地图.png").write_bytes(PNG_BYTES)
    _write_manifest(defaults, [_scene()])
    catalog = ResourceCatalog(maps, tmp_path / "characters", defaults)
    app = FastAPI()
    app.include_router(create_asset_router(catalog))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/assets/maps/the_world_map")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["content-type"] == "image/png"


async def test_map_catalog_exposes_packaged_fallback_url(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    _write_manifest(defaults, [_scene()])
    catalog = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", defaults)
    app = FastAPI()
    app.include_router(create_asset_router(catalog))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/assets/maps")

    assert response.status_code == 200
    assert response.json() == {
        "version": 1,
        "scenes": [
            {
                "scene_id": "the_world_map",
                "display_name": "总地图",
                "kind": "the_world_map",
                "order": 0,
                "anchor": None,
                "image_url": "/api/assets/maps/the_world_map",
                "fallback_image_url": "/api/assets/maps/the_world_map?default=true",
            }
        ],
    }


async def test_phase_three_character_api_only_exposes_default_portrait(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    _write_manifest(defaults, [_scene()])
    role_dir = tmp_path / "characters" / "天"
    role_dir.mkdir(parents=True)
    (role_dir / "天.png").write_bytes(PNG_BYTES)
    (role_dir / "微笑.png").write_bytes(PNG_BYTES)
    catalog = ResourceCatalog(tmp_path / "maps", tmp_path / "characters", defaults)
    app = FastAPI()
    app.include_router(create_asset_router(catalog))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/assets/characters")

    assert response.status_code == 200
    payload = response.json()
    assert payload == [
        {
            "role_name": "天",
            "portrait_url": "/api/assets/characters/%E5%A4%A9/default",
        }
    ]
    assert "微笑" not in response.text
