"""地图与角色图片的安全资源目录。"""

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MAP_EXTENSIONS = (".jpg", ".png")
CHARACTER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp")


class ResourceCatalogError(ValueError):
    """资源目录无法安全满足请求。"""


class InvalidResourceNameError(ResourceCatalogError):
    """资源名称可能跨越约定的单层目录。"""


class AssetNotFoundError(ResourceCatalogError):
    """声明的扩展名优先级中没有可用图片。"""


class InvalidMapManifestError(ResourceCatalogError):
    """随包地图清单不符合稳定资源契约。"""


class MapAnchor(BaseModel):
    """总地图上的归一化地点坐标，不依赖图片像素。"""

    model_config = ConfigDict(frozen=True, strict=True)

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class MapScene(BaseModel):
    """单个稳定场景与中文文件主体之间的映射。"""

    model_config = ConfigDict(frozen=True, strict=True)

    scene_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    kind: Literal["the_world_map", "location"]
    file_stem: str = Field(min_length=1)
    order: int = Field(ge=0)
    anchor: MapAnchor | None


class MapManifest(BaseModel):
    """第一版唯一地图事实来源。"""

    model_config = ConfigDict(frozen=True, strict=True)

    version: int = Field(ge=1)
    scenes: list[MapScene]

    @model_validator(mode="after")
    def validate_stable_identifiers(self) -> Self:
        scene_ids = [scene.scene_id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("map_manifest.json 中存在重复 scene_id")
        return self


@dataclass(frozen=True)
class ResolvedAsset:
    path: Path
    media_type: str


def _validate_component(name: str) -> None:
    """名称只能是一个目录层级，避免 URL 参数成为任意文件路径。"""

    if not name or name in {".", ".."} or Path(name).name != name:
        raise InvalidResourceNameError(f"资源名称不是安全的单层名称: {name!r}")
    if "/" in name or "\\" in name:
        raise InvalidResourceNameError(f"资源名称不得包含路径分隔符: {name!r}")


def safe_child(root: Path, name: str) -> Path:
    """返回根目录的直接子路径，并拒绝目录或文件符号链接。"""

    _validate_component(name)
    resolved_root = root.resolve()
    candidate = resolved_root / name
    # 用户可替换图片但不能借符号链接读取内容目录之外的文件。
    if candidate.is_symlink():
        raise InvalidResourceNameError(f"资源符号链接不受支持: {name!r}")
    resolved_candidate = candidate.resolve()
    if resolved_candidate.parent != resolved_root:
        raise InvalidResourceNameError(f"资源路径离开了约定目录: {name!r}")
    return resolved_candidate


def resolve_named_asset(root: Path, file_stem: str, extensions: tuple[str, ...]) -> ResolvedAsset:
    """严格按长期扩展名契约选择第一张普通图片文件。"""

    _validate_component(file_stem)
    resolved_root = root.resolve()
    for extension in extensions:
        candidate = safe_child(resolved_root, f"{file_stem}{extension}")
        if not candidate.is_file():
            continue
        # safe_child 已拒绝链接；再次比较真实父目录，防止检查和读取间明显逃逸。
        if candidate.resolve().parent != resolved_root:
            raise InvalidResourceNameError(f"资源文件离开了约定目录: {file_stem!r}")
        media_type, _ = mimetypes.guess_type(candidate.name)
        if media_type is None or not media_type.startswith("image/"):
            continue
        if media_type in {"image/svg+xml", "text/html"}:
            continue
        return ResolvedAsset(path=candidate, media_type=media_type)
    raise AssetNotFoundError(f"找不到图片资源: {file_stem}")


class ResourceCatalog:
    """只扫描 LocalAppData 内容目录，不建立第二份资源索引。"""

    def __init__(self, maps_dir: Path, characters_dir: Path, default_maps_dir: Path) -> None:
        self._maps_dir = maps_dir.resolve()
        self._characters_dir = characters_dir.resolve()
        self._default_maps_dir = default_maps_dir.resolve()

    def load_map_manifest(self) -> MapManifest:
        manifest_path = safe_child(self._default_maps_dir, "map_manifest.json")
        try:
            content = manifest_path.read_text(encoding="utf-8")
            return MapManifest.model_validate_json(content)
        except (OSError, ValidationError, ValueError) as error:
            raise InvalidMapManifestError(f"map_manifest.json 无效: {error}") from None

    def resolve_map(self, file_stem: str, *, default_only: bool = False) -> ResolvedAsset:
        root = self._default_maps_dir if default_only else self._maps_dir
        return resolve_named_asset(root, file_stem, MAP_EXTENSIONS)

    def resolve_character_asset(self, role_name: str, file_stem: str) -> ResolvedAsset:
        role_dir = safe_child(self._characters_dir, role_name)
        return resolve_named_asset(role_dir, file_stem, CHARACTER_EXTENSIONS)

    def resolve_portrait(self, role_name: str) -> ResolvedAsset:
        return self.resolve_character_asset(role_name, role_name)

    def list_character_folders(self) -> list[str]:
        if not self._characters_dir.is_dir():
            return []
        folders: list[str] = []
        for path in self._characters_dir.iterdir():
            if path.is_symlink() or not path.is_dir():
                continue
            if path.resolve().parent == self._characters_dir:
                folders.append(path.name)
        return sorted(folders)
