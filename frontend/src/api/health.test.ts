import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchHealth } from "./health";

describe("fetchHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the typed backend health response", async () => {
    const payload = {
      status: "ok",
      app_version: "0.1.0",
      database: "ok",
      sqlite_version: "3.53.1",
    } as const;
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchHealth()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/health", {
      headers: { Accept: "application/json" },
      signal: undefined,
    });
  });

  it("raises an ApiError when the backend is unavailable", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(new Response("unavailable", { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchHealth()).rejects.toEqual(
      new ApiError("后端健康检查失败。", 503),
    );
  });
});
