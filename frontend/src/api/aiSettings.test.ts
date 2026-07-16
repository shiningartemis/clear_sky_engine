import { afterEach, describe, expect, it, vi } from "vitest";

import { aiSettingsApi, parseJsonObjectEditor } from "./aiSettings";

const taskSetting = {
  task_key: "location_simulation",
  model_id: 8,
  temperature: 0.7,
  max_output_tokens: 2048,
  reasoning_effort: "high",
  timeout_seconds: 90,
  extra_prompt: "保持客观",
  structured_output_mode: "auto",
  provider_options: { top_p: 0.9, nested: { enabled: true } },
  memory_target_chars: null,
  memory_max_chars: null,
  version: 2,
  updated_at: "2026-07-16T00:00:00Z",
} as const;

describe("aiSettingsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the typed connection-test endpoint", async () => {
    const payload = {
      success: true,
      provider_type: "deepseek",
      remote_model: "deepseek-v4-flash",
      capabilities: { reasoning: true },
      diagnostic: "连接成功",
      error_category: null,
      usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
    } as const;
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(aiSettingsApi.testConnection(3, 8)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/providers/3/test-connection", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ model_id: 8 }),
    });
  });

  it("accepts model responses without legacy defaults", async () => {
    const payload = [
      {
        id: 8,
        provider_id: 3,
        display_name: "DeepSeek V4 Flash",
        remote_model: "deepseek-v4-flash",
        capabilities: { reasoning: true },
        enabled: true,
        created_at: "2026-07-16T00:00:00Z",
        updated_at: "2026-07-16T00:00:00Z",
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(aiSettingsApi.listModels()).resolves.toEqual(payload);
  });

  it("lists the two fixed task settings through the typed endpoint", async () => {
    const attributeSetting = {
      ...taskSetting,
      task_key: "attribute_memory_analysis",
      memory_target_chars: 20,
      memory_max_chars: 50,
    } as const;
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify([taskSetting, attributeSetting]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(aiSettingsApi.listTaskSettings()).resolves.toEqual([
      taskSetting,
      attributeSetting,
    ]);
    expect(fetchMock).toHaveBeenCalledWith("/api/ai-task-settings", {
      headers: { Accept: "application/json" },
      signal: undefined,
    });
  });

  it("updates one fixed task setting without converting provider JSON", async () => {
    const payload = {
      model_id: 8,
      temperature: 0.4,
      max_output_tokens: null,
      reasoning_effort: null,
      timeout_seconds: 120,
      extra_prompt: "仅返回事实",
      structured_output_mode: "prompt",
      provider_options: { custom_body: { threshold: 3 } },
      memory_target_chars: null,
      memory_max_chars: null,
    } as const;
    const response = { ...taskSetting, ...payload, version: 3 };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      aiSettingsApi.updateTaskSetting("location_simulation", payload),
    ).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ai-task-settings/location_simulation",
      {
        method: "PUT",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      },
    );
  });

  it("parses nested JSON objects without asserting unknown values", () => {
    expect(
      parseJsonObjectEditor('{"top_p":0.8,"nested":{"enabled":true}}'),
    ).toEqual({
      value: { top_p: 0.8, nested: { enabled: true } },
      error: null,
    });
  });

  it("reports syntax errors with actionable line and column", () => {
    const result = parseJsonObjectEditor('{\n  "top_p": 0.8,\n}');

    expect(result.value).toBeNull();
    expect(result.error).toMatchObject({ line: 3, column: 1 });
    expect(result.error?.message).toContain("JSON 语法错误");
  });

  it("rejects a non-object JSON root at the first character", () => {
    expect(parseJsonObjectEditor('["not", "an", "object"]')).toEqual({
      value: null,
      error: {
        message: "根节点必须是 JSON 对象。",
        line: 1,
        column: 1,
      },
    });
  });
});
