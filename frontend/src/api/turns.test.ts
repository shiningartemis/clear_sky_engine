import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./health";
import { turnsApi } from "./turns";

const encoder = new TextEncoder();

function ndjsonResponse(chunks: readonly string[]): Response {
  let index = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      const chunk = chunks[index];
      index += 1;
      if (chunk === undefined) {
        controller.close();
        return;
      }
      controller.enqueue(encoder.encode(chunk));
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "application/x-ndjson" },
  });
}

const nodeStarted = {
  run_id: "run-1",
  kind: "node_started",
  location_id: "the_home",
  node: "location_simulation",
  attempt: 1,
  max_attempts: 3,
  retrying: false,
  completed_maps: 0,
  total_maps: 1,
  elapsed_ms: 2,
} as const;

const completed = {
  run_id: "run-1",
  kind: "run_succeeded",
  location_id: null,
  node: null,
  attempt: null,
  max_attempts: 3,
  retrying: false,
  completed_maps: 1,
  total_maps: 1,
  elapsed_ms: 8,
  turn: {
    turn_id: 9,
    day: 2,
    time_slot: "midday",
    player_intent: "去学校",
    roles: [{ role_id: 1, content: "天出发了。", offline: false }],
    events: [
      {
        event_id: 3,
        location_id: "the_school",
        event_type: "encounter",
        fact: { visible: true },
      },
    ],
    state_changes: [
      {
        role_id: 1,
        attribute_key: "energy",
        operation: "decrement",
        old_value: 10,
        operand: 1,
        new_value: 9,
        reason: "走路",
      },
    ],
  },
} as const;

describe("turnsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("在任意分块、空行和重复终态中只交付完整事件", async () => {
    const payload = `${JSON.stringify(nodeStarted)}\n\n${JSON.stringify(completed)}\n${JSON.stringify(completed)}\n`;
    const chunks = [
      payload.slice(0, 7),
      payload.slice(7, 137),
      payload.slice(137),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(ndjsonResponse(chunks)),
    );
    const events: unknown[] = [];

    await turnsApi.stream("run-1", new AbortController().signal, (event) => {
      events.push(event);
    });

    expect(events).toEqual([nodeStarted, completed]);
  });

  it("接受没有末尾换行的最后一条终态事件", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(ndjsonResponse([JSON.stringify(completed)])),
    );
    const events: unknown[] = [];

    await turnsApi.stream("run-1", new AbortController().signal, (event) => {
      events.push(event);
    });

    expect(events).toEqual([completed]);
  });

  it.each([
    ["空 EOF", []],
    ["末尾有换行的非终态", [`${JSON.stringify(nodeStarted)}\n`]],
    ["末尾无换行的非终态", [JSON.stringify(nodeStarted)]],
  ])("将 %s 视为断线", async (_caseName, chunks) => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(ndjsonResponse(chunks)),
    );

    await expect(
      turnsApi.stream("run-1", new AbortController().signal, vi.fn()),
    ).rejects.toEqual(new ApiError("轮次进度流意外断开。", 200));
  });

  it("拒绝无效 JSON 行和 HTTP 错误", async () => {
    const signal = new AbortController().signal;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(ndjsonResponse(["{bad}\n"])),
    );
    await expect(turnsApi.stream("run-1", signal, vi.fn())).rejects.toEqual(
      new ApiError("轮次进度流格式无效。", 200),
    );

    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response("offline", { status: 503 })),
    );
    await expect(turnsApi.stream("run-1", signal, vi.fn())).rejects.toEqual(
      new ApiError("轮次请求失败。", 503),
    );
  });

  it("拒绝未通过运行时结构校验的事件", async () => {
    const invalidEvent = { ...nodeStarted, elapsed_ms: "unknown" };
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          ndjsonResponse([`${JSON.stringify(invalidEvent)}\n`]),
        ),
    );

    await expect(
      turnsApi.stream("run-1", new AbortController().signal, vi.fn()),
    ).rejects.toEqual(new ApiError("轮次进度流格式无效。", 200));
  });

  it("保留读取流断线错误，让调用方结束活动 run", async () => {
    const disconnected = new TypeError("network disconnected");
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(disconnected);
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(new Response(stream)),
    );

    await expect(
      turnsApi.stream("run-1", new AbortController().signal, vi.fn()),
    ).rejects.toBe(disconnected);
  });

  it("传递 AbortSignal 并保留 fetch 的取消语义", async () => {
    const controller = new AbortController();
    const abortError = new DOMException("已取消", "AbortError");
    const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(abortError);
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      turnsApi.stream("run-1", controller.signal, vi.fn()),
    ).rejects.toBe(abortError);
    expect(fetchMock).toHaveBeenCalledWith("/api/turn-runs/run-1/stream", {
      headers: { Accept: "application/x-ndjson" },
      signal: controller.signal,
    });
  });

  it("创建、取消和读取历史都校验后端 DTO", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ run_id: "run-1", status: "pending" }), {
          status: 202,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ run_id: "run-1", status: "cancelled" }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([completed.turn]), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(turnsApi.create(4, "去学校")).resolves.toEqual({
      run_id: "run-1",
      status: "pending",
    });
    await expect(turnsApi.cancel("run-1")).resolves.toEqual({
      run_id: "run-1",
      status: "cancelled",
    });
    await expect(turnsApi.listTurns(4)).resolves.toEqual([completed.turn]);
  });
});
