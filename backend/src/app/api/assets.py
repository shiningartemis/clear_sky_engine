"""地图与阶段 3 默认角色立绘 API。"""

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.resources.catalog import (
    AssetNotFoundError,
    InvalidResourceNameError,
    MapScene,
    ResourceCatalog,
)


class MapAnchorResponse(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class MapAssetResponse(BaseModel):
    scene_id: str
    display_name: str
    kind: Literal["the_world_map", "location"]
    order: int
    anchor: MapAnchorResponse | None
    image_url: str
    fallback_image_url: str


class MapCatalogResponse(BaseModel):
    version: int
    scenes: list[MapAssetResponse]


class CharacterAssetResponse(BaseModel):
    role_name: str
    portrait_url: str


def _asset_not_found(error: AssetNotFoundError | InvalidResourceNameError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _file_response(path: str, media_type: str) -> FileResponse:
    # 同名图片可由用户直接替换，刷新浏览器时必须重新验证而不能长期缓存旧内容。
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})


def create_asset_router(catalog: ResourceCatalog) -> APIRouter:
    """manifest 在路由创建时一次性校验，运行期只解析受控 scene_id。"""

    router = APIRouter(prefix="/api")
    manifest = catalog.load_map_manifest()
    scenes_by_id = {scene.scene_id: scene for scene in manifest.scenes}

    def _scene_response(scene: MapScene) -> MapAssetResponse:
        image_url = f"/api/assets/maps/{scene.scene_id}"
        return MapAssetResponse(
            scene_id=scene.scene_id,
            display_name=scene.display_name,
            kind=scene.kind,
            order=scene.order,
            anchor=(
                MapAnchorResponse(x=scene.anchor.x, y=scene.anchor.y) if scene.anchor else None
            ),
            image_url=image_url,
            fallback_image_url=f"{image_url}?default=true",
        )

    def _list_maps() -> MapCatalogResponse:
        scenes = [
            _scene_response(scene) for scene in sorted(manifest.scenes, key=lambda item: item.order)
        ]
        return MapCatalogResponse(version=manifest.version, scenes=scenes)

    def _get_map(
        scene_id: str,
        default: bool = Query(default=False),
    ) -> FileResponse:
        scene = scenes_by_id.get(scene_id)
        if scene is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地图场景不存在")
        try:
            asset = catalog.resolve_map(scene.file_stem, default_only=default)
        except (AssetNotFoundError, InvalidResourceNameError) as error:
            raise _asset_not_found(error) from None
        return _file_response(str(asset.path), asset.media_type)

    def _list_character_assets() -> list[CharacterAssetResponse]:
        assets: list[CharacterAssetResponse] = []
        for role_name in catalog.list_character_folders():
            try:
                catalog.resolve_portrait(role_name)
            except AssetNotFoundError:
                continue
            encoded_role_name = quote(role_name, safe="")
            assets.append(
                CharacterAssetResponse(
                    role_name=role_name,
                    portrait_url=f"/api/assets/characters/{encoded_role_name}/default",
                )
            )
        return assets

    def _get_default_portrait(role_name: str) -> FileResponse:
        try:
            asset = catalog.resolve_portrait(role_name)
        except (AssetNotFoundError, InvalidResourceNameError) as error:
            raise _asset_not_found(error) from None
        return _file_response(str(asset.path), asset.media_type)

    router.add_api_route(
        "/assets/maps", _list_maps, methods=["GET"], response_model=MapCatalogResponse
    )
    router.add_api_route("/assets/maps/{scene_id}", _get_map, methods=["GET"])
    router.add_api_route(
        "/assets/characters",
        _list_character_assets,
        methods=["GET"],
        response_model=list[CharacterAssetResponse],
    )
    router.add_api_route(
        "/assets/characters/{role_name}/default", _get_default_portrait, methods=["GET"]
    )
    return router
