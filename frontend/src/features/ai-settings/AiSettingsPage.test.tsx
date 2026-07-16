import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type {
  AiSettingsApi,
  ConnectionTestResponse,
  ModelResponse,
  ProviderResponse,
  TaskSettingResponse,
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
  enabled: true,
  created_at: "2026-07-11T00:00:00Z",
  updated_at: "2026-07-11T00:00:00Z",
};

const locationSetting: TaskSettingResponse = {
  task_key: "location_simulation",
  model_id: 2,
  temperature: 0.7,
  max_output_tokens: 2048,
  reasoning_effort: "high",
  timeout_seconds: 90,
  extra_prompt: "保持客观",
  structured_output_mode: "auto",
  provider_options: { top_p: 0.9 },
  memory_target_chars: null,
  memory_max_chars: null,
  version: 1,
  updated_at: "2026-07-16T00:00:00Z",
};

const attributeSetting: TaskSettingResponse = {
  ...locationSetting,
  task_key: "attribute_memory_analysis",
  memory_target_chars: 20,
  memory_max_chars: 50,
};

function createApi(overrides: Partial<AiSettingsApi> = {}): AiSettingsApi {
  return {
    listProviders: vi.fn().mockResolvedValue([]),
    listModels: vi.fn().mockResolvedValue([]),
    listTaskSettings: vi
      .fn()
      .mockResolvedValue([locationSetting, attributeSetting]),
    createProvider: vi.fn(),
    updateProvider: vi.fn(),
    deleteProvider: vi.fn(),
    createModel: vi.fn(),
    updateModel: vi.fn(),
    deleteModel: vi.fn(),
    testConnection: vi.fn(),
    updateTaskSetting: vi.fn(),
    ...overrides,
  };
}

function createTaskApi(overrides: Partial<AiSettingsApi> = {}): AiSettingsApi {
  return createApi({
    listModels: vi.fn().mockResolvedValue([model]),
    ...overrides,
  });
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

  it("shows both global task cards without restoring model defaults", async () => {
    renderPage(
      createApi({
        listProviders: vi.fn().mockResolvedValue([provider]),
        listModels: vi.fn().mockResolvedValue([model]),
      }),
    );

    const locationCard = await screen.findByRole("region", {
      name: "地点推演",
    });
    const attributeCard = screen.getByRole("region", {
      name: "属性与记忆分析",
    });
    expect(within(locationCard).getByLabelText("任务模型")).toHaveValue("2");
    expect(within(attributeCard).getByLabelText("记忆目标字数")).toHaveValue(
      20,
    );
    expect(within(attributeCard).getByLabelText("记忆硬上限")).toHaveValue(50);
    expect(screen.queryByText(/Model defaults/i)).not.toBeInTheDocument();
    expect(screen.queryByText("模型默认参数")).not.toBeInTheDocument();
  });

  it("formats provider JSON and reports syntax line and column", async () => {
    const user = userEvent.setup();
    renderPage(createTaskApi());
    const card = await screen.findByRole("region", { name: "地点推演" });
    const editor = within(card).getByLabelText("Provider 参数 JSON");

    fireEvent.change(editor, { target: { value: '{"top_p":0.8}' } });
    await user.click(within(card).getByRole("button", { name: "格式化 JSON" }));
    expect(editor).toHaveValue('{\n  "top_p": 0.8\n}');

    fireEvent.change(editor, {
      target: { value: '{\n  "top_p": 0.8,\n}' },
    });
    await user.click(
      within(card).getByRole("button", { name: "保存任务设置" }),
    );
    expect(within(card).getByRole("alert")).toHaveTextContent(
      /第 3 行，第 1 列.*JSON 语法错误/,
    );
  });

  it("locates non-object roots and protected-field conflicts", async () => {
    const user = userEvent.setup();
    renderPage(createTaskApi());
    const card = await screen.findByRole("region", { name: "地点推演" });
    const editor = within(card).getByLabelText("Provider 参数 JSON");
    const save = within(card).getByRole("button", { name: "保存任务设置" });

    fireEvent.change(editor, { target: { value: '["value"]' } });
    await user.click(save);
    expect(within(card).getByRole("alert")).toHaveTextContent(
      "第 1 行，第 1 列：根节点必须是 JSON 对象。",
    );

    fireEvent.change(editor, {
      target: { value: '{\n  "max_tokens": 100\n}' },
    });
    await user.click(save);
    expect(within(card).getByRole("alert")).toHaveTextContent(
      /第 2 行，第 3 列.*字段“max_tokens”与程序保留字段冲突/,
    );

    fireEvent.change(editor, {
      target: {
        value: '{\n  "note": "max_tokens",\n  "max_tokens": 100\n}',
      },
    });
    await user.click(save);
    expect(within(card).getByRole("alert")).toHaveTextContent(
      /第 3 行，第 3 列.*字段“max_tokens”与程序保留字段冲突/,
    );

    fireEvent.change(editor, {
      target: {
        value:
          '{\n  "options": ["other", "max_tokens"],\n  "max_tokens": 100\n}',
      },
    });
    await user.click(save);
    expect(within(card).getByRole("alert")).toHaveTextContent(
      /第 3 行，第 3 列.*字段“max_tokens”与程序保留字段冲突/,
    );
  });

  it("validates memory target against its hard maximum", async () => {
    const user = userEvent.setup();
    const updateTaskSetting = vi.fn<AiSettingsApi["updateTaskSetting"]>();
    renderPage(createTaskApi({ updateTaskSetting }));
    const card = await screen.findByRole("region", {
      name: "属性与记忆分析",
    });

    const target = within(card).getByLabelText("记忆目标字数");
    await user.clear(target);
    await user.type(target, "51");
    await user.click(
      within(card).getByRole("button", { name: "保存任务设置" }),
    );

    expect(within(card).getByRole("alert")).toHaveTextContent(
      "记忆目标字数不得大于硬上限。",
    );
    expect(updateTaskSetting).not.toHaveBeenCalled();
  });

  it("disables only the saving card and announces the next-turn effect", async () => {
    const user = userEvent.setup();
    let resolveUpdate: (value: TaskSettingResponse) => void = () => undefined;
    const updatePromise = new Promise<TaskSettingResponse>((resolve) => {
      resolveUpdate = resolve;
    });
    const updateTaskSetting = vi
      .fn<AiSettingsApi["updateTaskSetting"]>()
      .mockReturnValue(updatePromise);
    renderPage(createTaskApi({ updateTaskSetting }));
    const locationCard = await screen.findByRole("region", {
      name: "地点推演",
    });
    const attributeCard = screen.getByRole("region", {
      name: "属性与记忆分析",
    });

    await user.click(
      within(locationCard).getByRole("button", { name: "保存任务设置" }),
    );
    expect(updateTaskSetting).toHaveBeenCalledWith("location_simulation", {
      model_id: 2,
      temperature: 0.7,
      max_output_tokens: 2048,
      reasoning_effort: "high",
      timeout_seconds: 90,
      extra_prompt: "保持客观",
      structured_output_mode: "auto",
      provider_options: { top_p: 0.9 },
      memory_target_chars: null,
      memory_max_chars: null,
    });
    expect(within(locationCard).getByLabelText("任务模型")).toBeDisabled();
    expect(
      within(attributeCard).getByRole("button", { name: "保存任务设置" }),
    ).toBeEnabled();

    resolveUpdate({ ...locationSetting, version: 2 });
    expect(
      await within(locationCard).findByText("下一次新轮次生效"),
    ).toBeInTheDocument();
  });

  it("keeps every edited value when saving a task fails", async () => {
    const user = userEvent.setup();
    const updateTaskSetting = vi
      .fn<AiSettingsApi["updateTaskSetting"]>()
      .mockRejectedValue(new Error("offline"));
    renderPage(createTaskApi({ updateTaskSetting }));
    const card = await screen.findByRole("region", { name: "地点推演" });
    const prompt = within(card).getByLabelText("额外提示词");
    const editor = within(card).getByLabelText("Provider 参数 JSON");

    await user.clear(prompt);
    await user.type(prompt, "保留这段提示");
    fireEvent.change(editor, {
      target: { value: '{"custom_flag":true}' },
    });
    await user.click(
      within(card).getByRole("button", { name: "保存任务设置" }),
    );

    expect(await within(card).findByRole("alert")).toHaveTextContent(
      "保存任务设置失败，请检查配置后重试。",
    );
    expect(prompt).toHaveValue("保留这段提示");
    expect(editor).toHaveValue('{"custom_flag":true}');
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
