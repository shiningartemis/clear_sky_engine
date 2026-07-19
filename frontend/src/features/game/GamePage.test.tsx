import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type {
  TurnResponse,
  TurnRunClient,
  TurnRunEvent,
} from "../../api/turns";
import type { GameViewResponse, WorldsApi } from "../../api/worlds";
import { TurnRunNavigationProvider } from "../../app/TurnRunContext";
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
  worldId = 4,
): GameViewResponse {
  return {
    world_id: worldId,
    scene_id: sceneId,
    day: 1,
    weekday: "monday",
    time_slot: "morning",
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
              world_id: worldId,
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
    listWorldRoles: vi.fn().mockResolvedValue([
      {
        world_id: 4,
        role_id: 9,
        name: "天",
        kind: "player",
        enabled: true,
        effective_attributes: {},
        portrait_url: "/portraits/player.png",
        version: 1,
        updated_at: "2026-07-18T00:00:00Z",
      },
    ]),
    addNpc: vi.fn(),
    setNpcEnabled: vi.fn(),
    removeNpc: vi.fn(),
    replaceLocationRules: vi.fn(),
    selectLocation: vi.fn(),
    getGameView: vi.fn().mockResolvedValue(gameView()),
    ...overrides,
  };
}

function createTurnsApi(overrides: Partial<TurnRunClient> = {}): TurnRunClient {
  return {
    create: vi.fn(),
    stream: vi.fn(),
    cancel: vi.fn(),
    listTurns: vi.fn().mockResolvedValue([]),
    ...overrides,
  };
}

function completedTurn(playerIntent: string): TurnResponse {
  return {
    turn_id: 2,
    day: 1,
    time_slot: "midday",
    player_intent: playerIntent,
    roles: [{ role_id: 9, content: "天开始行动。", offline: false }],
    events: [],
    state_changes: [],
  };
}

function terminalEvent(
  kind: "run_succeeded" | "run_failed" | "run_cancelled",
  playerIntent: string,
): TurnRunEvent {
  return {
    run_id: "run-1",
    kind,
    location_id: null,
    node: null,
    attempt: null,
    max_attempts: 3,
    retrying: false,
    completed_maps: kind === "run_succeeded" ? 1 : 0,
    total_maps: 1,
    elapsed_ms: 120,
    error: kind === "run_failed" ? "模型暂时不可用。" : undefined,
    turn: kind === "run_succeeded" ? completedTurn(playerIntent) : undefined,
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
  readonly setInputLocked = vi.fn((locked: boolean) => {
    this.inputLocked = locked;
  });
  private listener: ((event: GameEvent) => void) | undefined;
  private inputLocked = false;

  subscribe(listener: (event: GameEvent) => void): () => void {
    this.listener = listener;
    return vi.fn(() => {
      this.listener = undefined;
    });
  }

  emit(event: GameEvent): void {
    if (this.inputLocked) return;
    this.listener?.(event);
  }
}

function renderGame(
  api: WorldsApi,
  bridge = new FakeBridge(),
  path = "/worlds/4/game",
  turnApi = createTurnsApi(),
) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <TurnRunNavigationProvider>
        <Routes>
          <Route
            path="/worlds/:worldId/game"
            element={
              <GamePage
                api={api}
                turnApi={turnApi}
                createBridge={() => bridge}
              />
            }
          />
        </Routes>
      </TurnRunNavigationProvider>
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
    expect(screen.getByLabelText("世界时间")).toHaveTextContent(
      "Day 1 · 星期一 · 晨间",
    );
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

  it("只在进入地点后显示自由意图，并允许提交目标缺席的尝试", async () => {
    const user = userEvent.setup();
    let onEvent: ((event: TurnRunEvent) => void) | undefined;
    const pendingStream = deferred<void>();
    const turnApi = createTurnsApi({
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn((_runId, _signal, listener) => {
        onEvent = listener;
        return pendingStream.promise;
      }),
    });
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_home")),
    });
    const bridge = renderGame(api, new FakeBridge(), undefined, turnApi);

    await screen.findByLabelText("游戏地图");
    expect(screen.queryByLabelText("主角准备尝试什么")).not.toBeInTheDocument();
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "寻找不在当前地点的安可儿");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));

    expect(turnApi.create).toHaveBeenCalledWith(4, "寻找不在当前地点的安可儿");
    expect(intent).toBeDisabled();
    expect(screen.getByRole("button", { name: "提交尝试" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "地图" })).toBeDisabled();
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(true);

    await act(async () => {
      onEvent?.(terminalEvent("run_cancelled", "寻找不在当前地点的安可儿"));
      pendingStream.resolve(undefined);
      await pendingStream.promise;
    });
  });

  it("成功后刷新权威 game view、清空意图、插入服务端 turn 并滚动", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    let onEvent: ((event: TurnRunEvent) => void) | undefined;
    const pendingStream = deferred<void>();
    const pendingHistory = deferred<TurnResponse[]>();
    const getGameView = vi
      .fn<WorldsApi["getGameView"]>()
      .mockResolvedValueOnce(gameView())
      .mockResolvedValueOnce(gameView("the_home"))
      .mockResolvedValueOnce({
        ...gameView("the_home"),
        time_slot: "midday",
      });
    const turnApi = createTurnsApi({
      listTurns: vi.fn(() => pendingHistory.promise),
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn((_runId, _signal, listener) => {
        onEvent = listener;
        return pendingStream.promise;
      }),
    });
    const bridge = renderGame(
      createWorldsApi({ getGameView }),
      new FakeBridge(),
      undefined,
      turnApi,
    );
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "调查走廊");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));

    await act(async () => {
      onEvent?.({
        run_id: "run-1",
        kind: "node_retrying",
        location_id: "the_home",
        node: "location_simulation",
        attempt: 2,
        max_attempts: 3,
        retrying: true,
        completed_maps: 0,
        total_maps: 1,
        elapsed_ms: 80,
      });
    });
    expect(screen.getByText(/家 · 地点推演 · 尝试 2\/3/)).toHaveTextContent(
      "自动重试",
    );

    await act(async () => {
      onEvent?.(terminalEvent("run_succeeded", "调查走廊"));
      pendingStream.resolve(undefined);
      await pendingStream.promise;
    });

    await waitFor(() => expect(getGameView).toHaveBeenCalledTimes(3));
    expect(getGameView).toHaveBeenLastCalledWith(
      4,
      "the_home",
      expect.any(AbortSignal),
    );
    expect(intent).toHaveValue("");
    expect(screen.getByText(/第 2 轮 .* 调查走廊/)).toBeInTheDocument();
    expect(screen.getByText("正在加载历轮故事…")).toBeInTheDocument();
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(false);

    await act(async () => {
      pendingHistory.reject(new Error("history unavailable"));
      await pendingHistory.promise.catch(() => undefined);
    });
    expect(screen.getByText(/第 2 轮 .* 调查走廊/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("无法加载历轮故事");
  });

  it("create 成功但 stream 失败时先取消服务端 run，再解锁并允许再次提交", async () => {
    const user = userEvent.setup();
    const pendingCleanup =
      deferred<Awaited<ReturnType<TurnRunClient["cancel"]>>>();
    const cancel = vi.fn(() => pendingCleanup.promise);
    const turnApi = createTurnsApi({
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn().mockRejectedValue(new Error("进度连接中断。")),
      cancel,
    });
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_home")),
    });
    const bridge = renderGame(api, new FakeBridge(), undefined, turnApi);
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "等待失败清理");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));

    await waitFor(() => expect(cancel).toHaveBeenCalledWith("run-1"));
    expect(intent).toBeDisabled();
    pendingCleanup.resolve({
      run_id: "run-1",
      status: "cancelled",
      turn_id: null,
      error: null,
    });

    expect(
      await screen.findByRole("button", { name: "再次提交" }),
    ).toBeEnabled();
    expect(intent).toHaveValue("等待失败清理");
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(false);
  });

  it("stream 失败但 cancel 返回 succeeded 时从历史恢复 turn 后再解锁", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const recoveredTurn = completedTurn("已在服务端提交");
    const listTurns = vi
      .fn<TurnRunClient["listTurns"]>()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([recoveredTurn]);
    const turnApi = createTurnsApi({
      listTurns,
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn().mockRejectedValue(new Error("进度连接中断。")),
      cancel: vi.fn().mockResolvedValue({
        run_id: "run-1",
        status: "succeeded",
        turn_id: 2,
        error: null,
      }),
    });
    const getGameView = vi
      .fn<WorldsApi["getGameView"]>()
      .mockResolvedValueOnce(gameView())
      .mockResolvedValueOnce(gameView("the_home"))
      .mockResolvedValueOnce({ ...gameView("the_home"), time_slot: "midday" });
    const bridge = renderGame(
      createWorldsApi({ getGameView }),
      new FakeBridge(),
      undefined,
      turnApi,
    );
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "已在服务端提交");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));

    expect(
      await screen.findByText(/第 2 轮 .* 已在服务端提交/),
    ).toBeInTheDocument();
    expect(intent).toHaveValue("");
    expect(listTurns).toHaveBeenCalledTimes(2);
    expect(getGameView).toHaveBeenCalledTimes(3);
    expect(scrollIntoView).toHaveBeenCalled();
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(false);
  });

  it("服务端已成功但历史同步失败时保持锁，重试成功后才释放", async () => {
    const user = userEvent.setup();
    const recoveredTurn = completedTurn("同步失败后恢复");
    const listTurns = vi
      .fn<TurnRunClient["listTurns"]>()
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new Error("history unavailable"))
      .mockRejectedValueOnce(new Error("history still unavailable"))
      .mockResolvedValueOnce([recoveredTurn]);
    const turnApi = createTurnsApi({
      listTurns,
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn().mockRejectedValue(new Error("进度连接中断。")),
      cancel: vi.fn().mockResolvedValue({
        run_id: "run-1",
        status: "succeeded",
        turn_id: 2,
        error: null,
      }),
    });
    const getGameView = vi
      .fn<WorldsApi["getGameView"]>()
      .mockResolvedValueOnce(gameView())
      .mockResolvedValueOnce(gameView("the_home"))
      .mockResolvedValueOnce({ ...gameView("the_home"), time_slot: "midday" });
    const bridge = renderGame(
      createWorldsApi({ getGameView }),
      new FakeBridge(),
      undefined,
      turnApi,
    );
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "同步失败后恢复");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));

    expect(
      await screen.findByRole("button", { name: "重试同步结果" }),
    ).toBeEnabled();
    expect(
      screen.getByText("轮次可能已成功，结果同步失败。"),
    ).toBeInTheDocument();
    expect(intent).toBeDisabled();
    expect(screen.getByRole("button", { name: "地图" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "再次提交" }),
    ).not.toBeInTheDocument();
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByRole("button", { name: "重试同步结果" }));

    expect(
      await screen.findByRole("button", { name: "重试同步结果" }),
    ).toBeEnabled();
    expect(
      screen.getByText("轮次可能已成功，结果同步失败。"),
    ).toBeInTheDocument();
    expect(intent).toBeDisabled();
    expect(screen.getByRole("button", { name: "地图" })).toBeDisabled();
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByRole("button", { name: "重试同步结果" }));

    expect(
      await screen.findByText(/第 2 轮 .* 同步失败后恢复/),
    ).toBeInTheDocument();
    expect(intent).toHaveValue("");
    expect(listTurns).toHaveBeenCalledTimes(4);
    expect(getGameView).toHaveBeenCalledTimes(3);
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(false);
  });

  it("cancel succeeded 缺少 turn_id 时进入恢复锁而不是普通失败", async () => {
    const user = userEvent.setup();
    const turnApi = createTurnsApi({
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn().mockRejectedValue(new Error("进度连接中断。")),
      cancel: vi.fn().mockResolvedValue({
        run_id: "run-1",
        status: "succeeded",
        turn_id: null,
        error: null,
      }),
    });
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_home")),
    });
    const bridge = renderGame(api, new FakeBridge(), undefined, turnApi);
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "缺少结果编号");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));

    expect(
      await screen.findByText("轮次可能已成功，结果同步失败。"),
    ).toBeInTheDocument();
    expect(intent).toBeDisabled();
    expect(screen.getByRole("button", { name: "地图" })).toBeDisabled();
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(true);
  });

  it("旧 run 终态不产生刷新滚动，并在当前流无终态时安全清理当前 run", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const cancel = vi.fn().mockResolvedValue({
      run_id: "run-1",
      status: "cancelled",
      turn_id: null,
      error: null,
    });
    const turnApi = createTurnsApi({
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn(async (_runId, _signal, onEvent) => {
        onEvent({
          ...terminalEvent("run_succeeded", "旧 run 结果"),
          run_id: "run-old",
        });
      }),
      cancel,
    });
    const getGameView = vi
      .fn<WorldsApi["getGameView"]>()
      .mockResolvedValueOnce(gameView())
      .mockResolvedValueOnce(gameView("the_home"));
    const bridge = renderGame(
      createWorldsApi({ getGameView }),
      new FakeBridge(),
      undefined,
      turnApi,
    );
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "当前 run 意图");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));

    expect(
      await screen.findByRole("button", { name: "再次提交" }),
    ).toBeEnabled();
    expect(intent).toHaveValue("当前 run 意图");
    expect(cancel).toHaveBeenCalledWith("run-1");
    expect(getGameView).toHaveBeenCalledTimes(2);
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(screen.queryByText(/旧 run 结果/)).not.toBeInTheDocument();
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(false);
  });

  it("初次清理返回错配 succeeded 时不恢复错误 turn 并保持当前 run 锁", async () => {
    const user = userEvent.setup();
    const recoveredTurn = completedTurn("不应恢复的旧结果");
    const listTurns = vi
      .fn<TurnRunClient["listTurns"]>()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([recoveredTurn]);
    const turnApi = createTurnsApi({
      listTurns,
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn().mockRejectedValue(new Error("进度连接中断。")),
      cancel: vi.fn().mockResolvedValue({
        run_id: "run-old",
        status: "succeeded",
        turn_id: 2,
        error: null,
      }),
    });
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_home")),
    });
    const bridge = renderGame(api, new FakeBridge(), undefined, turnApi);
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "当前 run 不能被旧响应覆盖");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));

    expect(
      await screen.findByText("轮次同步响应与当前轮次不匹配。"),
    ).toBeInTheDocument();
    expect(intent).toBeDisabled();
    expect(screen.getByRole("button", { name: "地图" })).toBeDisabled();
    expect(screen.queryByText(/不应恢复的旧结果/)).not.toBeInTheDocument();
    expect(listTurns).toHaveBeenCalledTimes(1);
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(true);
  });

  it("恢复重试收到错配 cancel 状态时继续保持锁并显示同步错误", async () => {
    const user = userEvent.setup();
    const cancel = vi
      .fn<TurnRunClient["cancel"]>()
      .mockResolvedValueOnce({
        run_id: "run-1",
        status: "succeeded",
        turn_id: null,
        error: null,
      })
      .mockResolvedValueOnce({
        run_id: "run-old",
        status: "succeeded",
        turn_id: 2,
        error: null,
      });
    const turnApi = createTurnsApi({
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn().mockRejectedValue(new Error("进度连接中断。")),
      cancel,
    });
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_home")),
    });
    const bridge = renderGame(api, new FakeBridge(), undefined, turnApi);
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "重试也必须校验 run");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));
    await user.click(
      await screen.findByRole("button", { name: "重试同步结果" }),
    );

    expect(
      await screen.findByText("轮次同步响应与当前轮次不匹配。"),
    ).toBeInTheDocument();
    expect(intent).toBeDisabled();
    expect(screen.getByRole("button", { name: "地图" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重试同步结果" })).toBeEnabled();
    expect(cancel).toHaveBeenCalledTimes(2);
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(true);
  });

  it("cancel 返回 cancelled 时中止悬挂 stream，并立即按权威终态解锁", async () => {
    const user = userEvent.setup();
    let streamSignal: AbortSignal | undefined;
    const turnApi = createTurnsApi({
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn((_runId, signal) => {
        streamSignal = signal;
        return new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }),
      cancel: vi.fn().mockResolvedValue({
        run_id: "run-1",
        status: "cancelled",
        turn_id: null,
        error: null,
      }),
    });
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_home")),
    });
    const bridge = renderGame(api, new FakeBridge(), undefined, turnApi);
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "取消悬挂轮次");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));
    await user.click(await screen.findByRole("button", { name: "取消轮次" }));

    expect(
      await screen.findByRole("button", { name: "再次提交" }),
    ).toBeEnabled();
    expect(intent).toHaveValue("取消悬挂轮次");
    expect(streamSignal?.aborted).toBe(true);
    expect(screen.getByRole("alert")).toHaveTextContent("轮次已取消");
  });

  it("cancel 拒绝时中止 stream、保留意图并以失败状态释放锁", async () => {
    const user = userEvent.setup();
    let streamSignal: AbortSignal | undefined;
    const turnApi = createTurnsApi({
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn((_runId, signal) => {
        streamSignal = signal;
        return new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }),
      cancel: vi.fn().mockRejectedValue(new Error("cancel unavailable")),
    });
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_home")),
    });
    const bridge = renderGame(api, new FakeBridge(), undefined, turnApi);
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "取消失败也要解锁");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));
    await user.click(await screen.findByRole("button", { name: "取消轮次" }));

    expect(
      await screen.findByRole("button", { name: "再次提交" }),
    ).toBeEnabled();
    expect(intent).toHaveValue("取消失败也要解锁");
    expect(streamSignal?.aborted).toBe(true);
    expect(screen.getByRole("alert")).toHaveTextContent("取消请求失败");
  });

  it("cancel 返回 succeeded 时不等待丢失的 stream，立即按 turn_id 恢复权威结果", async () => {
    const user = userEvent.setup();
    let streamSignal: AbortSignal | undefined;
    const recoveredTurn = completedTurn("读取成功结果");
    const listTurns = vi
      .fn<TurnRunClient["listTurns"]>()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([recoveredTurn]);
    const turnApi = createTurnsApi({
      listTurns,
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn((_runId, signal) => {
        streamSignal = signal;
        return new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }),
      cancel: vi.fn().mockResolvedValue({
        run_id: "run-1",
        status: "succeeded",
        turn_id: 2,
        error: null,
      }),
    });
    const api = createWorldsApi({
      getGameView: vi
        .fn()
        .mockResolvedValueOnce(gameView())
        .mockResolvedValueOnce(gameView("the_home"))
        .mockResolvedValueOnce({
          ...gameView("the_home"),
          time_slot: "midday",
        }),
    });
    const bridge = renderGame(api, new FakeBridge(), undefined, turnApi);
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "读取成功结果");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));
    await user.click(await screen.findByRole("button", { name: "取消轮次" }));

    expect(
      await screen.findByText(/第 2 轮 .* 读取成功结果/),
    ).toBeInTheDocument();
    expect(intent).toHaveValue("");
    expect(listTurns).toHaveBeenCalledTimes(2);
    expect(api.getGameView).toHaveBeenCalledTimes(3);
    expect(streamSignal?.aborted).toBe(true);
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(false);
    expect(screen.queryByText(/轮次已取消/)).not.toBeInTheDocument();
  });

  it.each([
    ["run_failed", "模型暂时不可用。"],
    ["run_cancelled", "轮次已取消，可以修改意图后再次提交。"],
  ] as const)("%s 不新增卡片、不刷新世界并保留冻结意图", async (kind, message) => {
    const user = userEvent.setup();
    let onEvent: ((event: TurnRunEvent) => void) | undefined;
    const pendingStream = deferred<void>();
    const getGameView = vi
      .fn<WorldsApi["getGameView"]>()
      .mockResolvedValueOnce(gameView())
      .mockResolvedValueOnce(gameView("the_home"));
    const turnApi = createTurnsApi({
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn((_runId, _signal, listener) => {
        onEvent = listener;
        return pendingStream.promise;
      }),
      cancel: vi.fn().mockResolvedValue({
        run_id: "run-1",
        status: "running",
        turn_id: null,
        error: null,
      }),
    });
    const bridge = renderGame(
      createWorldsApi({ getGameView }),
      new FakeBridge(),
      undefined,
      turnApi,
    );
    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const intent = await screen.findByLabelText("主角准备尝试什么");
    await user.type(intent, "继续观察");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));
    if (kind === "run_cancelled") {
      await user.click(screen.getByRole("button", { name: "取消轮次" }));
      expect(turnApi.cancel).toHaveBeenCalledWith("run-1");
    }

    await act(async () => {
      onEvent?.(terminalEvent(kind, "继续观察"));
      pendingStream.resolve(undefined);
      await pendingStream.promise;
    });

    expect(intent).toHaveValue("继续观察");
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: "再次提交" })).toBeEnabled();
    expect(screen.getByText("还没有成功轮次")).toBeInTheDocument();
    expect(getGameView).toHaveBeenCalledTimes(2);
  });

  it("路由参数切换世界时清空旧状态，并忽略旧 run 的迟到终态", async () => {
    const user = userEvent.setup();
    let onOldEvent: ((event: TurnRunEvent) => void) | undefined;
    const pendingOldStream = deferred<void>();
    const getGameView = vi.fn<WorldsApi["getGameView"]>(
      (requestedWorldId, sceneId) =>
        Promise.resolve(gameView(sceneId, "the_home", requestedWorldId)),
    );
    const listWorldRoles = vi.fn<WorldsApi["listWorldRoles"]>(
      (requestedWorldId) =>
        Promise.resolve([
          {
            world_id: requestedWorldId,
            role_id: 9,
            name: requestedWorldId === 4 ? "旧世界主角" : "新世界主角",
            kind: "player",
            enabled: true,
            effective_attributes: {},
            portrait_url: "/portraits/player.png",
            version: 1,
            updated_at: "2026-07-18T00:00:00Z",
          },
        ]),
    );
    const turnApi = createTurnsApi({
      listTurns: vi.fn<TurnRunClient["listTurns"]>((requestedWorldId) =>
        Promise.resolve([
          completedTurn(requestedWorldId === 4 ? "旧世界历史" : "新世界历史"),
        ]),
      ),
      create: vi.fn().mockResolvedValue({ run_id: "run-1", status: "pending" }),
      stream: vi.fn((_runId, _signal, listener) => {
        onOldEvent = listener;
        return pendingOldStream.promise;
      }),
    });
    const api = createWorldsApi({ getGameView, listWorldRoles });
    const bridge = new FakeBridge();
    render(
      <MemoryRouter initialEntries={["/worlds/4/game"]}>
        <TurnRunNavigationProvider>
          <Link to="/worlds/5/game">切换到世界 5</Link>
          <Routes>
            <Route
              path="/worlds/:worldId/game"
              element={
                <GamePage
                  api={api}
                  turnApi={turnApi}
                  createBridge={() => bridge}
                />
              }
            />
          </Routes>
        </TurnRunNavigationProvider>
      </MemoryRouter>,
    );

    await screen.findByLabelText("游戏地图");
    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const oldIntent = await screen.findByLabelText("主角准备尝试什么");
    expect(
      await screen.findByText(/第 2 轮 .* 旧世界历史/),
    ).toBeInTheDocument();
    expect(screen.getByText(/主角独立纪事 .* 旧世界主角/)).toBeInTheDocument();
    await user.type(oldIntent, "旧世界意图");
    await user.click(screen.getByRole("button", { name: "提交尝试" }));
    await act(async () => {
      onOldEvent?.({
        run_id: "run-1",
        kind: "node_retrying",
        location_id: "the_home",
        node: "location_simulation",
        attempt: 2,
        max_attempts: 3,
        retrying: true,
        completed_maps: 0,
        total_maps: 1,
        elapsed_ms: 80,
      });
    });
    expect(screen.getByText(/家 · 地点推演 · 尝试 2\/3/)).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "切换到世界 5" }));
    await waitFor(() =>
      expect(getGameView).toHaveBeenCalledWith(
        5,
        "the_world_map",
        expect.any(AbortSignal),
      ),
    );
    const callCountAfterWorldSwitch = getGameView.mock.calls.length;
    await act(async () => {
      onOldEvent?.(terminalEvent("run_succeeded", "旧世界迟到终态"));
      pendingOldStream.resolve(undefined);
      await pendingOldStream.promise;
    });
    expect(
      getGameView.mock.calls
        .slice(callCountAfterWorldSwitch)
        .some(([requestedWorldId]) => requestedWorldId === 4),
    ).toBe(false);

    act(() => bridge.emit({ type: "enter_location", locationId: "the_home" }));
    const newIntent = await screen.findByLabelText("主角准备尝试什么");
    expect(newIntent).toHaveValue("");
    expect(
      await screen.findByText(/第 2 轮 .* 新世界历史/),
    ).toBeInTheDocument();
    expect(screen.getByText(/主角独立纪事 .* 新世界主角/)).toBeInTheDocument();
    expect(screen.queryByText(/旧世界历史/)).not.toBeInTheDocument();
    expect(screen.queryByText(/旧世界迟到终态/)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("旧世界意图")).not.toBeInTheDocument();
    expect(screen.queryByText(/自动重试/)).not.toBeInTheDocument();
    expect(bridge.setInputLocked).toHaveBeenLastCalledWith(false);
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
        <TurnRunNavigationProvider>
          <Routes>
            <Route
              path="/worlds/:worldId/game"
              element={
                <GamePage
                  api={api}
                  turnApi={createTurnsApi()}
                  createBridge={() => invalidBridge}
                />
              }
            />
          </Routes>
        </TurnRunNavigationProvider>
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
