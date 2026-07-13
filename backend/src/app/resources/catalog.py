"""地图与角色图片的安全资源目录。"""

import os
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


def safe_content_root(root: Path) -> Path:
    """校验用户内容根的词法祖先，禁止 reparse 点把读写重定向到树外。"""

    lexical_root = Path(os.path.abspath(root))
    # 必须在 resolve 前检查；否则符号链接和 Windows junction 的来源信息会永久丢失。
    for component in (lexical_root, *lexical_root.parents):
        if component == component.parent:
            continue
        if component.is_symlink() or os.path.isjunction(component):
            raise InvalidResourceNameError(f"用户内容目录不得经过链接或 junction: {component}")
    return lexical_root


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


def _verified_image_media_type(path: Path) -> str | None:
    """只依据文件内容识别白名单图片，扩展名不能替代安全边界校验。"""

    try:
        with path.open("rb") as image_file:
            header = image_file.read(64)
            if header.startswith(b"\xff\xd8\xff"):
                return "image/jpeg"
            if header.startswith(b"\x89PNG\r\n\x1a\n"):
                return "image/png"
            if header.startswith((b"GIF87a", b"GIF89a")):
                return "image/gif"
            if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
                return "image/webp"
            if header.startswith(b"BM"):
                return "image/bmp"
            if len(header) >= 16 and header[4:8] == b"ftyp":
                box_size = int.from_bytes(header[:4], byteorder="big")
                if 16 <= box_size <= 4096:
                    image_file.seek(0)
                    file_type_box = image_file.read(box_size)
                    if len(file_type_box) == box_size:
                        brands = [file_type_box[8:12]]
                        brands.extend(
                            file_type_box[offset : offset + 4] for offset in range(16, box_size, 4)
                        )
                        if any(brand in {b"avif", b"avis"} for brand in brands):
                            return "image/avif"
    except OSError:
        return None
    return None


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
        media_type = _verified_image_media_type(candidate)
        if media_type is None:
            continue
        return ResolvedAsset(path=candidate, media_type=media_type)
    raise AssetNotFoundError(f"找不到图片资源: {file_stem}")


class ResourceCatalog:
    """只扫描 LocalAppData 内容目录，不建立第二份资源索引。"""

    def __init__(self, maps_dir: Path, characters_dir: Path, default_maps_dir: Path) -> None:
        self._maps_dir = safe_content_root(maps_dir)
        self._characters_dir = safe_content_root(characters_dir)
        self._default_maps_dir = default_maps_dir.resolve()

    def load_map_manifest(self) -> MapManifest:
        manifest_path = safe_child(self._default_maps_dir, "map_manifest.json")
        try:
            content = manifest_path.read_text(encoding="utf-8")
            return MapManifest.model_validate_json(content)
        except (OSError, ValidationError, ValueError) as error:
            raise InvalidMapManifestError(f"map_manifest.json 无效: {error}") from None

    def resolve_map(self, file_stem: str, *, default_only: bool = False) -> ResolvedAsset:
        root = self._default_maps_dir if default_only else safe_content_root(self._maps_dir)
        return resolve_named_asset(root, file_stem, MAP_EXTENSIONS)

    def resolve_character_asset(self, role_name: str, file_stem: str) -> ResolvedAsset:
        role_dir = safe_child(safe_content_root(self._characters_dir), role_name)
        return resolve_named_asset(role_dir, file_stem, CHARACTER_EXTENSIONS)

    def resolve_portrait(self, role_name: str) -> ResolvedAsset:
        return self.resolve_character_asset(role_name, role_name)

    def list_character_folders(self) -> list[str]:
        characters_dir = safe_content_root(self._characters_dir)
        if not characters_dir.is_dir():
            return []
        folders: list[str] = []
        for path in characters_dir.iterdir():
            if path.is_symlink() or not path.is_dir():
                continue
            if path.resolve().parent == characters_dir:
                folders.append(path.name)
        return sorted(folders)
