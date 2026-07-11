import { afterEach, describe, expect, it, vi } from "vitest";

import { aiSettingsApi } from "./aiSettings";

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
});
