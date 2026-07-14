import Phaser from "phaser";

import { GameBridge } from "./GameBridge";
import {
  calculateCoverTransform,
  type GameEvent,
  type GameViewState,
  isValidMapAspectRatio,
  type MarkerPosition,
  moveLocationMarker,
  projectAnchor,
} from "./types";
import {
  createWorldMapState,
  reduceWorldMap,
  type WorldMapAction,
  type WorldMapState,
} from "./worldMapState";

const LOGICAL_WIDTH = 1920;
const LOGICAL_HEIGHT = 1080;
const MARKER_SIZE = 96;
const MOVE_STEP = 24;

interface LoadedImage {
  element: HTMLImageElement;
  width: number;
  height: number;
}

async function decodeImage(url: string): Promise<LoadedImage> {
  const element = new Image();
  element.src = url;
  await element.decode();
  if (element.naturalWidth <= 0 || element.naturalHeight <= 0) {
    throw new Error("地图图片没有有效尺寸。");
  }
  return {
    element,
    width: element.naturalWidth,
    height: element.naturalHeight,
  };
}

async function loadBackground(state: GameViewState): Promise<LoadedImage> {
  try {
    const primary = await decodeImage(state.backgroundUrl);
    if (!isValidMapAspectRatio(primary.width, primary.height)) {
      throw new Error("地图图片不是 16:9。");
    }
    return primary;
  } catch {
    // 用户替换图损坏或比例越界时必须回退，避免将错误资源拉伸成有效地图。
    return decodeImage(state.fallbackBackgroundUrl);
  }
}

export class MapScene extends Phaser.Scene {
  private readonly emitEvent: (event: GameEvent) => void;
  private view: GameViewState | null = null;
  private worldMapState: WorldMapState | null = null;
  private localMarker: MarkerPosition = { x: 960, y: 540 };
  private background: Phaser.GameObjects.Image | null = null;
  private marker: Phaser.GameObjects.Image | null = null;
  private backgroundImage: LoadedImage | null = null;
  private markerImage: LoadedImage | null = null;
  private locationLabels: Phaser.GameObjects.Text[] = [];
  private assetGeneration = 0;
  private textureSequence = 0;
  private backgroundTextureKey: string | null = null;
  private markerTextureKey: string | null = null;
  private ready = false;
  private stopped = false;

  constructor(emit: (event: GameEvent) => void) {
    super("map");
    this.emitEvent = emit;
  }

  create(): void {
    this.ready = true;
    this.stopped = false;
    this.input.keyboard?.on("keydown", this.handleKeyDown);
    this.input.on("pointerdown", this.handlePointerDown);
    this.scale.on("resize", this.handleResize);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, this.shutdown, this);
    if (this.view) void this.loadViewAssets(this.view);
  }

  updateView(state: GameViewState): void {
    this.view = state;
    this.localMarker = { x: 960, y: 540 };
    const orderedLocationIds = [...state.locations]
      .sort((left, right) => left.order - right.order)
      .map((location) => location.sceneId);
    this.worldMapState = createWorldMapState(
      orderedLocationIds,
      state.playerLocationId,
    );
    if (this.ready) void this.loadViewAssets(state);
  }

  private async loadViewAssets(state: GameViewState): Promise<void> {
    const generation = this.assetGeneration + 1;
    this.assetGeneration = generation;
    const [backgroundImage, markerImage] = await Promise.all([
      loadBackground(state).catch(() => null),
      decodeImage(state.playerMarkerUrl).catch(() => null),
    ]);
    if (
      this.stopped ||
      generation !== this.assetGeneration ||
      this.view !== state
    )
      return;

    if (backgroundImage) {
      this.installBackground(backgroundImage);
    } else {
      this.background?.destroy();
      this.background = null;
      this.backgroundImage = null;
    }
    if (markerImage) {
      this.installMarker(markerImage);
    } else {
      this.marker?.destroy();
      this.marker = null;
      this.markerImage = null;
    }
    this.renderLayout();
  }

  private installBackground(image: LoadedImage): void {
    this.background?.destroy();
    if (this.backgroundTextureKey)
      this.textures.remove(this.backgroundTextureKey);
    const key = `map-background-${this.textureSequence}`;
    this.textureSequence += 1;
    this.textures.addImage(key, image.element);
    this.backgroundTextureKey = key;
    this.backgroundImage = image;
    this.background = this.add.image(0, 0, key).setOrigin(0).setDepth(0);
  }

  private installMarker(image: LoadedImage): void {
    this.marker?.destroy();
    if (this.markerTextureKey) this.textures.remove(this.markerTextureKey);
    const key = `player-marker-${this.textureSequence}`;
    this.textureSequence += 1;
    this.textures.addImage(key, image.element);
    this.markerTextureKey = key;
    this.markerImage = image;
    this.marker = this.add.image(0, 0, key).setDepth(2);
  }

  private renderLayout(): void {
    const view = this.view;
    const backgroundImage = this.backgroundImage;
    if (!view || !backgroundImage) return;
    const viewportWidth = this.scale.gameSize.width;
    const viewportHeight = this.scale.gameSize.height;
    const transform = calculateCoverTransform(
      backgroundImage.width,
      backgroundImage.height,
      viewportWidth,
      viewportHeight,
    );
    this.background
      ?.setPosition(transform.offsetX, transform.offsetY)
      .setScale(transform.scale);

    for (const label of this.locationLabels) label.destroy();
    this.locationLabels = [];
    if (view.sceneId === "the_world_map") {
      for (const location of view.locations) {
        const point = projectAnchor(
          location.anchor,
          backgroundImage,
          transform,
        );
        this.locationLabels.push(
          this.add
            .text(point.x, point.y + 58, location.displayName, {
              color: "#edf6ff",
              fontFamily: "Segoe UI, sans-serif",
              fontSize: "18px",
              backgroundColor: "rgba(7, 19, 34, 0.78)",
              padding: { x: 10, y: 5 },
            })
            .setOrigin(0.5)
            .setDepth(1),
        );
      }
    }

    const markerPoint = this.markerPoint(view, backgroundImage, transform);
    const logicalScale = Math.min(
      viewportWidth / LOGICAL_WIDTH,
      viewportHeight / LOGICAL_HEIGHT,
    );
    if (this.marker && this.markerImage) {
      const containScale =
        (MARKER_SIZE * logicalScale) /
        Math.max(this.markerImage.width, this.markerImage.height);
      this.marker
        .setPosition(markerPoint.x, markerPoint.y)
        .setScale(containScale);
    }
  }

  private markerPoint(
    view: GameViewState,
    backgroundImage: LoadedImage,
    transform: ReturnType<typeof calculateCoverTransform>,
  ): Readonly<{ x: number; y: number }> {
    if (view.sceneId === "the_world_map") {
      const selectedLocationId =
        this.worldMapState?.selectedLocationId ?? view.playerLocationId;
      const selected = view.locations.find(
        (location) => location.sceneId === selectedLocationId,
      );
      if (selected)
        return projectAnchor(selected.anchor, backgroundImage, transform);
    }
    return {
      x: (this.localMarker.x / LOGICAL_WIDTH) * this.scale.gameSize.width,
      y: (this.localMarker.y / LOGICAL_HEIGHT) * this.scale.gameSize.height,
    };
  }

  private dispatchWorldMap(action: WorldMapAction): void {
    if (!this.worldMapState) return;
    this.worldMapState = reduceWorldMap(this.worldMapState, action);
    this.renderLayout();
    if (this.worldMapState.pendingEvent) {
      this.emitEvent(this.worldMapState.pendingEvent);
    }
  }

  private readonly handleKeyDown = (event: KeyboardEvent): void => {
    const view = this.view;
    if (!view) return;
    const key = event.key.toLowerCase();
    if (view.sceneId === "the_world_map") {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        this.dispatchWorldMap({ type: "move", direction: -1 });
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        this.dispatchWorldMap({ type: "move", direction: 1 });
      }
      if (event.key === "Enter") {
        event.preventDefault();
        this.dispatchWorldMap({ type: "enter" });
      }
      return;
    }

    const delta =
      event.key === "ArrowLeft" || key === "a"
        ? { x: -MOVE_STEP, y: 0 }
        : event.key === "ArrowRight" || key === "d"
          ? { x: MOVE_STEP, y: 0 }
          : event.key === "ArrowUp" || key === "w"
            ? { x: 0, y: -MOVE_STEP }
            : event.key === "ArrowDown" || key === "s"
              ? { x: 0, y: MOVE_STEP }
              : null;
    if (delta) {
      // 地点内微移动只改变 Canvas 局部位置，不产生世界地点或时间事件。
      event.preventDefault();
      this.localMarker = moveLocationMarker(this.localMarker, delta);
      this.renderLayout();
    }
  };

  private readonly handlePointerDown = (
    pointer: Phaser.Input.Pointer,
  ): void => {
    const view = this.view;
    const backgroundImage = this.backgroundImage;
    if (view?.sceneId !== "the_world_map" || !backgroundImage) return;
    const transform = calculateCoverTransform(
      backgroundImage.width,
      backgroundImage.height,
      this.scale.gameSize.width,
      this.scale.gameSize.height,
    );
    const logicalScale = Math.min(
      this.scale.gameSize.width / LOGICAL_WIDTH,
      this.scale.gameSize.height / LOGICAL_HEIGHT,
    );
    const hitRadius = MARKER_SIZE * logicalScale;
    const selected = view.locations.find((location) => {
      // 点击区与绘制必须共用同一投影，非 16:9 视口裁切后才不会错位。
      const point = projectAnchor(location.anchor, backgroundImage, transform);
      return Math.hypot(pointer.x - point.x, pointer.y - point.y) <= hitRadius;
    });
    if (selected) {
      this.dispatchWorldMap({ type: "select", locationId: selected.sceneId });
    }
  };

  private readonly handleResize = (): void => {
    this.renderLayout();
  };

  private shutdown(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.ready = false;
    this.assetGeneration += 1;
    this.input.keyboard?.off("keydown", this.handleKeyDown);
    this.input.off("pointerdown", this.handlePointerDown);
    this.scale.off("resize", this.handleResize);
    for (const label of this.locationLabels) label.destroy();
    this.locationLabels = [];
  }
}

export function createDefaultGameBridge(): GameBridge {
  return new GameBridge((container, emit) => {
    const scene = new MapScene(emit);
    const game = new Phaser.Game({
      type: Phaser.AUTO,
      parent: container,
      width: LOGICAL_WIDTH,
      height: LOGICAL_HEIGHT,
      backgroundColor: "#08111f",
      scene,
      scale: {
        mode: Phaser.Scale.RESIZE,
        autoCenter: Phaser.Scale.CENTER_BOTH,
      },
    });
    return {
      destroy(removeCanvas) {
        game.destroy(removeCanvas);
      },
      update(state) {
        scene.updateView(state);
      },
    };
  });
}
