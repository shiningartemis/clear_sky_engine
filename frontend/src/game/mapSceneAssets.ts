export interface DestroyableSceneObject {
  destroy(): void;
}

export interface TextureStore {
  remove(key: string): unknown;
}

export interface SceneAssetState<
  TBackground extends DestroyableSceneObject,
  TMarker extends DestroyableSceneObject,
  TOverlay extends DestroyableSceneObject,
  TImage,
> {
  background: TBackground | null;
  marker: TMarker | null;
  locationOverlays: TOverlay[];
  backgroundImage: TImage | null;
  markerImage: TImage | null;
  backgroundTextureKey: string | null;
  markerTextureKey: string | null;
}

export function clearFailedMapAssets<
  TBackground extends DestroyableSceneObject,
  TMarker extends DestroyableSceneObject,
  TOverlay extends DestroyableSceneObject,
  TImage,
>(
  assets: SceneAssetState<TBackground, TMarker, TOverlay, TImage>,
  textures: TextureStore,
): SceneAssetState<TBackground, TMarker, TOverlay, TImage> {
  assets.background?.destroy();
  assets.marker?.destroy();
  for (const overlay of assets.locationOverlays) overlay.destroy();
  if (assets.backgroundTextureKey) textures.remove(assets.backgroundTextureKey);
  if (assets.markerTextureKey) textures.remove(assets.markerTextureKey);
  return {
    background: null,
    marker: null,
    locationOverlays: [],
    backgroundImage: null,
    markerImage: null,
    backgroundTextureKey: null,
    markerTextureKey: null,
  };
}

export function clearFailedMarkerAsset<
  TBackground extends DestroyableSceneObject,
  TMarker extends DestroyableSceneObject,
  TOverlay extends DestroyableSceneObject,
  TImage,
>(
  assets: SceneAssetState<TBackground, TMarker, TOverlay, TImage>,
  textures: TextureStore,
): SceneAssetState<TBackground, TMarker, TOverlay, TImage> {
  assets.marker?.destroy();
  if (assets.markerTextureKey) textures.remove(assets.markerTextureKey);
  return {
    ...assets,
    marker: null,
    markerImage: null,
    markerTextureKey: null,
  };
}
