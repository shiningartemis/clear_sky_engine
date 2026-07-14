import { describe, expect, it, vi } from "vitest";

import {
  clearFailedMapAssets,
  clearFailedMarkerAsset,
  type SceneAssetState,
} from "./mapSceneAssets";

function destroyable() {
  return { destroy: vi.fn() };
}

function populatedAssets(): SceneAssetState<
  ReturnType<typeof destroyable>,
  ReturnType<typeof destroyable>,
  ReturnType<typeof destroyable>,
  { width: number; height: number }
> {
  return {
    background: destroyable(),
    marker: destroyable(),
    locationOverlays: [destroyable(), destroyable(), destroyable()],
    backgroundImage: { width: 1920, height: 1080 },
    markerImage: { width: 600, height: 900 },
    backgroundTextureKey: "old-background",
    markerTextureKey: "old-marker",
  };
}

describe("map scene final asset failure cleanup", () => {
  it("removes every old scene object and texture after background and fallback both fail", () => {
    const assets = populatedAssets();
    const remove = vi.fn();

    const cleared = clearFailedMapAssets(assets, { remove });

    expect(assets.background?.destroy).toHaveBeenCalledTimes(1);
    expect(assets.marker?.destroy).toHaveBeenCalledTimes(1);
    for (const overlay of assets.locationOverlays) {
      expect(overlay.destroy).toHaveBeenCalledTimes(1);
    }
    expect(remove).toHaveBeenCalledTimes(2);
    expect(remove).toHaveBeenNthCalledWith(1, "old-background");
    expect(remove).toHaveBeenNthCalledWith(2, "old-marker");
    expect(cleared).toEqual({
      background: null,
      marker: null,
      locationOverlays: [],
      backgroundImage: null,
      markerImage: null,
      backgroundTextureKey: null,
      markerTextureKey: null,
    });
  });

  it("removes the old marker texture after marker decoding fails without clearing the new background", () => {
    const assets = populatedAssets();
    const remove = vi.fn();

    const cleared = clearFailedMarkerAsset(assets, { remove });

    expect(assets.marker?.destroy).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith("old-marker");
    expect(cleared.marker).toBeNull();
    expect(cleared.markerImage).toBeNull();
    expect(cleared.markerTextureKey).toBeNull();
    expect(cleared.background).toBe(assets.background);
    expect(cleared.backgroundTextureKey).toBe("old-background");
    expect(cleared.locationOverlays).toBe(assets.locationOverlays);
    expect(assets.background?.destroy).not.toHaveBeenCalled();
    for (const overlay of assets.locationOverlays) {
      expect(overlay.destroy).not.toHaveBeenCalled();
    }
  });
});
