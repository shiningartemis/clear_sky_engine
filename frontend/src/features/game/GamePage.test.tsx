import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { GameViewResponse, WorldsApi } from "../../api/worlds";
import type {
  GameBridgePort,
  GameEvent,
  GameViewState,
} from "../../game/types";
import { GamePage } from "./GamePage";

vi.mock("../../game/PhaserGame", () => ({
  createDefaultGameBridge: vi.fn(),
}));

function gameView(
  sceneId: GameViewResponse["scene_id"] = "the_world_map",
  playerLocationId = "the_home",
): GameViewResponse {
  return {
    world_id: 4,
    scene_id: sceneId,
    background_url: `/maps/${sceneId}.jpg`,
    fallback_background_url: "/maps/fallback.jpg",
    player_marker_url: "/portraits/player.png",
    player_location_id: playerLocationId,
    locations: [
      {
        scene_id: "the_home",
        display_name: "家",
        order: 0,
        anchor_x: 0.2,
        anchor_y: 0.5,
      },
      {
        scene_id: "the_school",
        display_name: "学校",
        order: 5,
        anchor_x: 0.8,
        anchor_y: 0.5,
      },
    ],
    visible_roles:
      sceneId === "the_world_map"
        ? []
        : [
            {
              world_id: 4,
              role_id: 9,
              name: "天",
              kind: "player",
              enabled: true,
              effective_attributes: {},
              portrait_url: "/portraits/player.png",
              version: 1,
              updated_at: "2026-07-14T00:00:00Z",
            },
          ],
  };
}

function createWorldsApi(overrides: Partial<WorldsApi> = {}): WorldsApi {
  return {
    listWorlds: vi.fn(),
    createWorld: vi.fn(),
    deleteWorld: vi.fn(),
    listWorldRoles: vi.fn(),
    addNpc: vi.fn(),
    setNpcEnabled: vi.fn(),
    removeNpc: vi.fn(),
    replaceLocationRules: vi.fn(),
    selectLocation: vi.fn(),
    getGameView: vi.fn().mockResolvedValue(gameView()),
    ...overrides,
  };
}

function deferred<T>() {
  let resolvePromise: ((value: T) => void) | undefined;
  let rejectPromise: ((reason?: unknown) => void) | undefined;
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return {
    promise,
    resolve(value: T) {
      resolvePromise?.(value);
    },
    reject(reason?: unknown) {
      rejectPromise?.(reason);
    },
  };
}

class FakeBridge implements GameBridgePort {
  readonly mount = vi.fn();
  readonly update = vi.fn<(state: GameViewState) => void>();
  readonly destroy = vi.fn();
  private listener: ((event: GameEvent) => void) | undefined;

  subscribe(listener: (event: GameEvent) => void): () => void {
    this.listener = listener;
    return vi.fn(() => {
      this.listener = undefined;
    });
  }

  emit(event: GameEvent): void {
    this.listener?.(event);
  }
}

function renderGame(
  api: WorldsApi,
  bridge = new FakeBridge(),
  path = "/worlds/4/game",
) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/worlds/:worldId/game"
          element={<GamePage api={api} createBridge={() => bridge} />}
        />
      </Routes>
    </MemoryRouter>,
  );
  return bridge;
}

describe("GamePage", () => {
  it("loads the world map and sends only backend view facts to Phaser", async () => {
    const api = createWorldsApi();
    const bridge = renderGame(api);

    expect(screen.getByText("正在加载地图…")).toBeInTheDocument();
    expect(await screen.findByLabelText("游戏地图")).toBeInTheDocument();
    expect(api.getGameView).toHaveBeenCalledWith(
      4,
      "the_world_map",
      expect.any(AbortSignal),
    );
    await waitFor(() =>
      expect(bridge.update).toHaveBeenCalledWith({
        sceneId: "the_world_map",
        backgroundUrl: "/maps/the_world_map.jpg",
        fallbackBackgroundUrl: "/maps/fallback.jpg",
        playerMarkerUrl: "/portraits/player.png",
        playerLocationId: "the_home",
        locations: [
          {
            sceneId: "the_home",
            displayName: "家",
            order: 0,
            anchor: { x: 0.2, y: 0.5 },
          },
          {
            sceneId: "the_school",
            displayName: "学校",
            order: 5,
            anchor: { x: 0.8, y: 0.5 },
          },
        ],
      }),
    );
    expect(screen.queryByLabelText("当前地点角色")).not.toBeInTheDocument();
  });

  it("selects a location and enters it through typed bridge events", async () => {
    const api = createWorldsApi({
      selectLocation: vi
        .fn()
        .mockResolvedValue(gameView("the_world_map", "the_school")),
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_school", "the_school")),
    });
    const bridge = renderGame(api);
    await screen.findByLabelText("游戏地图");

    await act(async () =>
      bridge.emit({ type: "select_location", locationId: "the_school" }),
    );
    expect(api.selectLocation).toHaveBeenCalledWith(4, "the_school");

    await act(async () =>
      bridge.emit({ type: "enter_location", locationId: "the_school" }),
    );
    expect(api.getGameView).toHaveBeenLastCalledWith(
      4,
      "the_school",
      expect.any(AbortSignal),
    );
    expect(await screen.findByLabelText("当前地点角色")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "天" })).toBeInTheDocument();
  });

  it("serializes location writes and unlocks after the authoritative response", async () => {
    const pendingSelection = deferred<GameViewResponse>();
    const selectLocation = vi
      .fn<WorldsApi["selectLocation"]>()
      .mockImplementationOnce(() => pendingSelection.promise)
      .mockResolvedValueOnce(gameView("the_world_map", "the_home"));
    const bridge = renderGame(createWorldsApi({ selectLocation }));
    await screen.findByLabelText("游戏地图");

    act(() =>
      bridge.emit({ type: "select_location", locationId: "the_school" }),
    );
    expect(screen.getByText("正在移动到所选地点…")).toBeInTheDocument();
    expect(screen.getByLabelText("地图画布")).toHaveAttribute(
      "aria-busy",
      "true",
    );

    act(() => bridge.emit({ type: "select_location", locationId: "the_home" }));
    expect(selectLocation).toHaveBeenCalledTimes(1);

    await act(async () => {
      pendingSelection.resolve(gameView("the_world_map", "the_school"));
      await pendingSelection.promise;
    });
    expect(await screen.findByLabelText("游戏地图")).toBeInTheDocument();

    act(() => bridge.emit({ type: "select_location", locationId: "the_home" }));
    expect(selectLocation).toHaveBeenCalledTimes(2);
  });

  it("unlocks location writes after a failed selection so the player can retry", async () => {
    const pendingSelection = deferred<GameViewResponse>();
    const selectLocation = vi
      .fn<WorldsApi["selectLocation"]>()
      .mockImplementationOnce(() => pendingSelection.promise)
      .mockResolvedValueOnce(gameView("the_world_map", "the_school"));
    const bridge = renderGame(createWorldsApi({ selectLocation }));
    await screen.findByLabelText("游戏地图");

    act(() =>
      bridge.emit({ type: "select_location", locationId: "the_school" }),
    );
    await act(async () => {
      pendingSelection.reject(new Error("conflict"));
      await pendingSelection.promise.catch(() => undefined);
    });
    expect(screen.getByText("无法移动到地点")).toBeInTheDocument();

    act(() =>
      bridge.emit({ type: "select_location", locationId: "the_school" }),
    );
    expect(selectLocation).toHaveBeenCalledTimes(2);
  });

  it("returns to the world map from the React overlay button", async () => {
    const user = userEvent.setup();
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView("the_home", "the_home"))
        .mockResolvedValueOnce(gameView()),
    });
    renderGame(api);

    await user.click(await screen.findByRole("button", { name: "地图" }));

    expect(api.getGameView).toHaveBeenLastCalledWith(
      4,
      "the_world_map",
      expect.any(AbortSignal),
    );
    expect(
      screen.queryByRole("button", { name: "地图" }),
    ).not.toBeInTheDocument();
  });

  it("shows invalid-world and retryable loading errors", async () => {
    const user = userEvent.setup();
    const getGameView = vi
      .fn<WorldsApi["getGameView"]>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(gameView());
    const api = createWorldsApi({ getGameView });
    const invalidBridge = new FakeBridge();
    const { unmount } = render(
      <MemoryRouter initialEntries={["/worlds/nope/game"]}>
        <Routes>
          <Route
            path="/worlds/:worldId/game"
            element={<GamePage api={api} createBridge={() => invalidBridge} />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("世界地址无效")).toBeInTheDocument();
    expect(getGameView).not.toHaveBeenCalled();
    expect(invalidBridge.mount).not.toHaveBeenCalled();
    unmount();

    renderGame(api);
    expect(await screen.findByText("无法加载地图")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByLabelText("游戏地图")).toBeInTheDocument();
    expect(getGameView).toHaveBeenCalledTimes(2);
  });
});
