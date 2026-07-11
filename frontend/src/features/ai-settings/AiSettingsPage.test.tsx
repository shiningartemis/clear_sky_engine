import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type {
  AiSettingsApi,
  ConnectionTestResponse,
  ModelResponse,
  ProviderResponse,
} from "../../api/aiSettings";
import { AiSettingsPage } from "./AiSettingsPage";

const provider: ProviderResponse = {
  id: 1,
  name: "DeepSeek",
  provider_type: "deepseek",
  base_url: "https://api.deepseek.com",
  enabled: true,
  extra: {},
  has_api_key: true,
  created_at: "2026-07-11T00:00:00Z",
  updated_at: "2026-07-11T00:00:00Z",
};

const model: ModelResponse = {
  id: 2,
  provider_id: 1,
  display_name: "DeepSeek V4 Flash",
  remote_model: "deepseek-v4-flash",
  capabilities: { reasoning: true, json_output: true, tools: true },
  defaults: {},
  enabled: true,
  created_at: "2026-07-11T00:00:00Z",
  updated_at: "2026-07-11T00:00:00Z",
};

function createApi(overrides: Partial<AiSettingsApi> = {}): AiSettingsApi {
  return {
    listProviders: vi.fn().mockResolvedValue([]),
    listModels: vi.fn().mockResolvedValue([]),
    createProvider: vi.fn(),
    updateProvider: vi.fn(),
    deleteProvider: vi.fn(),
    createModel: vi.fn(),
    updateModel: vi.fn(),
    deleteModel: vi.fn(),
    testConnection: vi.fn(),
    ...overrides,
  };
}

function renderPage(api: AiSettingsApi) {
  return render(
    <MemoryRouter>
      <AiSettingsPage api={api} />
    </MemoryRouter>,
  );
}

describe("AiSettingsPage", () => {
  it("shows loading and then an actionable empty state", async () => {
    renderPage(createApi());

    expect(screen.getByText("正在加载 AI 配置…")).toBeInTheDocument();
    expect(await screen.findByText("还没有 Provider")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "添加 Provider" }),
    ).toBeInTheDocument();
  });

  it("shows an error and retries both lists", async () => {
    const user = userEvent.setup();
    const listProviders = vi
      .fn<AiSettingsApi["listProviders"]>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([]);
    const listModels = vi
      .fn<AiSettingsApi["listModels"]>()
      .mockResolvedValue([]);
    renderPage(createApi({ listProviders, listModels }));

    expect(await screen.findByText("无法加载 AI 配置")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("还没有 Provider")).toBeInTheDocument();
    expect(listProviders).toHaveBeenCalledTimes(2);
    expect(listModels).toHaveBeenCalledTimes(2);
  });

  it("masks the saved key and reports connection-test progress", async () => {
    const user = userEvent.setup();
    let resolveTest: (value: ConnectionTestResponse) => void = () => undefined;
    const testPromise = new Promise<ConnectionTestResponse>((resolve) => {
      resolveTest = resolve;
    });
    const testConnection = vi
      .fn<AiSettingsApi["testConnection"]>()
      .mockReturnValue(testPromise);
    renderPage(
      createApi({
        listProviders: vi.fn().mockResolvedValue([provider]),
        listModels: vi.fn().mockResolvedValue([model]),
        testConnection,
      }),
    );

    expect(await screen.findByText("API Key 已配置")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    expect(screen.getByText("正在测试连接…")).toBeInTheDocument();

    resolveTest({
      success: true,
      provider_type: "deepseek",
      remote_model: "deepseek-v4-flash",
      capabilities: model.capabilities,
      diagnostic: "连接成功",
      error_category: null,
      usage: { input_tokens: 3, output_tokens: 1, total_tokens: 4 },
    });
    expect(await screen.findByText("连接成功 · 4 tokens")).toBeInTheDocument();
    expect(testConnection).toHaveBeenCalledWith(1, 2);
  });

  it("creates a DeepSeek provider through a password field", async () => {
    const user = userEvent.setup();
    const createProvider = vi
      .fn<AiSettingsApi["createProvider"]>()
      .mockResolvedValue(provider);
    renderPage(createApi({ createProvider }));

    await screen.findByText("还没有 Provider");
    await user.click(screen.getByRole("button", { name: "添加 Provider" }));
    await user.type(screen.getByLabelText("Provider 名称"), "DeepSeek");
    await user.selectOptions(
      screen.getByLabelText("Provider 类型"),
      "deepseek",
    );
    await user.type(screen.getByLabelText("API Key"), "temporary-key");
    expect(screen.getByLabelText("API Key")).toHaveAttribute(
      "type",
      "password",
    );
    await user.click(screen.getByRole("button", { name: "保存 Provider" }));

    expect(createProvider).toHaveBeenCalledWith({
      name: "DeepSeek",
      provider_type: "deepseek",
      base_url: "https://api.deepseek.com",
      api_key: "temporary-key",
      enabled: true,
      extra: {},
    });
    expect(await screen.findByText("API Key 已配置")).toBeInTheDocument();
  });

  it("edits an existing model without changing its provider", async () => {
    const user = userEvent.setup();
    const updatedModel = { ...model, remote_model: "deepseek-v4-pro" };
    const updateModel = vi
      .fn<AiSettingsApi["updateModel"]>()
      .mockResolvedValue(updatedModel);
    renderPage(
      createApi({
        listProviders: vi.fn().mockResolvedValue([provider]),
        listModels: vi.fn().mockResolvedValue([model]),
        updateModel,
      }),
    );

    await user.click(
      await screen.findByRole("button", { name: "编辑模型 DeepSeek V4 Flash" }),
    );
    const remoteInput = screen.getByLabelText("远端模型名");
    await user.clear(remoteInput);
    await user.type(remoteInput, "deepseek-v4-pro");
    await user.click(screen.getByRole("button", { name: "保存模型" }));

    expect(updateModel).toHaveBeenCalledWith(2, {
      display_name: "DeepSeek V4 Flash",
      remote_model: "deepseek-v4-pro",
      enabled: true,
    });
    expect(await screen.findByText("deepseek-v4-pro")).toBeInTheDocument();
  });
});
