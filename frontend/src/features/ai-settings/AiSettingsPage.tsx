import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  type AiSettingsApi,
  aiSettingsApi,
  type ConnectionTestResponse,
  type ModelResponse,
  type ProviderCreate,
  type ProviderResponse,
  type ProviderUpdate,
  parseJsonObjectEditor,
  type TaskKey,
  type TaskSettingResponse,
  type TaskSettingUpdate,
} from "../../api/aiSettings";
import styles from "./AiSettingsPage.module.css";

interface AiSettingsPageProps {
  api?: AiSettingsApi;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | {
      kind: "ready";
      providers: ProviderResponse[];
      models: ModelResponse[];
      taskSettings: TaskSettingResponse[];
    };

type ConnectionState = "loading" | ConnectionTestResponse;

const emptyProvider: ProviderCreate = {
  name: "",
  provider_type: "deepseek",
  base_url: "https://api.deepseek.com",
  api_key: "",
  enabled: true,
  extra: {},
};

const protectedProviderOptionKeys = new Set(
  [
    "model",
    "messages",
    "input",
    "authorization",
    "api_key",
    "base_url",
    "stream",
    "temperature",
    "max_tokens",
    "max_output_tokens",
    "thinking",
    "reasoning_effort",
    "tools",
    "tool_choice",
    "response_format",
    "json_schema",
  ].map(normalizeProviderOptionKey),
);

interface TaskFormState {
  modelId: string;
  temperature: string;
  maxOutputTokens: string;
  reasoningEffort: "" | "high" | "max";
  timeoutSeconds: string;
  extraPrompt: string;
  structuredOutputMode: "auto" | "native" | "prompt";
  providerOptionsSource: string;
  memoryTargetChars: string;
  memoryMaxChars: string;
}

function normalizeProviderOptionKey(key: string) {
  return [...key.toLocaleLowerCase()]
    .filter((character) => /[a-z0-9]/.test(character))
    .join("");
}

function editorPosition(source: string, offset: number) {
  const lines = source.slice(0, Math.max(0, offset)).split("\n");
  return { line: lines.length, column: (lines.at(-1)?.length ?? 0) + 1 };
}

function findRootObjectKeyOffset(source: string, targetKey: string) {
  let depth = 0;
  let inString = false;
  let escaped = false;
  let expectingRootKey = false;
  let rootKeyStart = -1;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === '"') {
        inString = false;
        if (rootKeyStart >= 0) {
          // 已通过 JSON.parse 的源文本可安全解码单个键；用解码值处理 Unicode 转义键。
          const decodedKey: unknown = JSON.parse(
            source.slice(rootKeyStart, index + 1),
          );
          if (decodedKey === targetKey) return rootKeyStart;
          rootKeyStart = -1;
          expectingRootKey = false;
        }
      }
      continue;
    }
    if (character === '"') {
      inString = true;
      if (depth === 1 && expectingRootKey) rootKeyStart = index;
    } else if (character === "{") {
      depth += 1;
      if (depth === 1) expectingRootKey = true;
    } else if (character === "}") {
      depth -= 1;
    } else if (character === "," && depth === 1) {
      expectingRootKey = true;
    }
  }
  return 0;
}

function formFromSetting(setting: TaskSettingResponse): TaskFormState {
  return {
    modelId: setting.model_id?.toString() ?? "",
    temperature: setting.temperature?.toString() ?? "",
    maxOutputTokens: setting.max_output_tokens?.toString() ?? "",
    reasoningEffort: setting.reasoning_effort ?? "",
    timeoutSeconds: setting.timeout_seconds.toString(),
    extraPrompt: setting.extra_prompt,
    structuredOutputMode: setting.structured_output_mode,
    providerOptionsSource: JSON.stringify(setting.provider_options, null, 2),
    memoryTargetChars: setting.memory_target_chars?.toString() ?? "",
    memoryMaxChars: setting.memory_max_chars?.toString() ?? "",
  };
}

function optionalNumber(source: string) {
  return source.trim() === "" ? null : Number(source);
}

function taskTitle(taskKey: TaskKey) {
  return taskKey === "location_simulation" ? "地点推演" : "属性与记忆分析";
}

interface TaskSettingCardProps {
  setting: TaskSettingResponse;
  models: ModelResponse[];
  api: AiSettingsApi;
}

function TaskSettingCard({ setting, models, api }: TaskSettingCardProps) {
  const [form, setForm] = useState(() => formFromSetting(setting));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<
    { kind: "error" | "success"; text: string } | undefined
  >();
  const title = taskTitle(setting.task_key);
  const titleId = `task-setting-${setting.task_key}`;
  const enabledModels = models.filter((item) => item.enabled);

  function setField<Key extends keyof TaskFormState>(
    field: Key,
    value: TaskFormState[Key],
  ) {
    setForm((current) => ({ ...current, [field]: value }));
    setMessage(undefined);
  }

  function validateProviderOptions() {
    const parsed = parseJsonObjectEditor(form.providerOptionsSource);
    if (parsed.error || !parsed.value) {
      const issue = parsed.error ?? {
        message: "Provider 参数必须是 JSON 对象。",
        line: 1,
        column: 1,
      };
      setMessage({
        kind: "error",
        text: `第 ${issue.line} 行，第 ${issue.column} 列：${issue.message}`,
      });
      return null;
    }
    const conflict = Object.keys(parsed.value).find((key) =>
      protectedProviderOptionKeys.has(normalizeProviderOptionKey(key)),
    );
    if (conflict) {
      const keyOffset = findRootObjectKeyOffset(
        form.providerOptionsSource,
        conflict,
      );
      const position = editorPosition(form.providerOptionsSource, keyOffset);
      setMessage({
        kind: "error",
        text: `第 ${position.line} 行，第 ${position.column} 列：字段“${conflict}”与程序保留字段冲突。`,
      });
      return null;
    }
    return parsed.value;
  }

  function buildPayload(): TaskSettingUpdate | null {
    const providerOptions = validateProviderOptions();
    if (!providerOptions) return null;

    const modelId = optionalNumber(form.modelId);
    const temperature = optionalNumber(form.temperature);
    const maxOutputTokens = optionalNumber(form.maxOutputTokens);
    const timeoutSeconds = Number(form.timeoutSeconds);
    const memoryTargetChars = optionalNumber(form.memoryTargetChars);
    const memoryMaxChars = optionalNumber(form.memoryMaxChars);
    if (
      modelId === null ||
      !Number.isInteger(modelId) ||
      !enabledModels.some((item) => item.id === modelId)
    ) {
      setMessage({ kind: "error", text: "请选择一个已启用的任务模型。" });
      return null;
    }
    if (
      temperature !== null &&
      (!Number.isFinite(temperature) || temperature < 0 || temperature > 2)
    ) {
      setMessage({ kind: "error", text: "温度必须在 0 到 2 之间。" });
      return null;
    }
    if (
      maxOutputTokens !== null &&
      (!Number.isInteger(maxOutputTokens) || maxOutputTokens <= 0)
    ) {
      setMessage({ kind: "error", text: "最大输出 Tokens 必须是正整数。" });
      return null;
    }
    if (!Number.isInteger(timeoutSeconds) || timeoutSeconds <= 0) {
      setMessage({ kind: "error", text: "超时秒数必须是正整数。" });
      return null;
    }
    if (setting.task_key === "attribute_memory_analysis") {
      if (
        memoryTargetChars === null ||
        !Number.isInteger(memoryTargetChars) ||
        memoryTargetChars <= 0 ||
        memoryMaxChars === null ||
        !Number.isInteger(memoryMaxChars) ||
        memoryMaxChars <= 0
      ) {
        setMessage({ kind: "error", text: "记忆字数必须是正整数。" });
        return null;
      }
      if (memoryTargetChars > memoryMaxChars) {
        setMessage({
          kind: "error",
          text: "记忆目标字数不得大于硬上限。",
        });
        return null;
      }
    }
    return {
      model_id: modelId,
      temperature,
      max_output_tokens: maxOutputTokens,
      reasoning_effort: form.reasoningEffort || null,
      timeout_seconds: timeoutSeconds,
      extra_prompt: form.extraPrompt,
      structured_output_mode: form.structuredOutputMode,
      provider_options: providerOptions,
      memory_target_chars:
        setting.task_key === "attribute_memory_analysis"
          ? memoryTargetChars
          : null,
      memory_max_chars:
        setting.task_key === "attribute_memory_analysis"
          ? memoryMaxChars
          : null,
    };
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(undefined);
    const payload = buildPayload();
    if (!payload) return;
    setSaving(true);
    try {
      await api.updateTaskSetting(setting.task_key, payload);
      setMessage({ kind: "success", text: "下一次新轮次生效" });
    } catch {
      // 请求失败时不重置表单，开发商可以直接修正或重试当前完整输入。
      setMessage({
        kind: "error",
        text: "保存任务设置失败，请检查配置后重试。",
      });
    } finally {
      setSaving(false);
    }
  }

  function formatProviderOptions() {
    const parsed = parseJsonObjectEditor(form.providerOptionsSource);
    if (parsed.error || !parsed.value) {
      const issue = parsed.error ?? {
        message: "Provider 参数必须是 JSON 对象。",
        line: 1,
        column: 1,
      };
      setMessage({
        kind: "error",
        text: `第 ${issue.line} 行，第 ${issue.column} 列：${issue.message}`,
      });
      return;
    }
    setField("providerOptionsSource", JSON.stringify(parsed.value, null, 2));
  }

  return (
    <section className={styles.taskCard} aria-labelledby={titleId}>
      <div className={styles.taskHeader}>
        <div>
          <span className={styles.typeBadge}>固定全局任务</span>
          <h3 id={titleId}>{title}</h3>
        </div>
        <span className={styles.version}>版本 {setting.version}</span>
      </div>
      <form onSubmit={save}>
        <fieldset className={styles.taskFields} disabled={saving}>
          <label>
            任务模型
            <select
              required
              value={form.modelId}
              onChange={(event) => setField("modelId", event.target.value)}
            >
              <option value="">请选择模型</option>
              {enabledModels.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.display_name} · {item.remote_model}
                </option>
              ))}
            </select>
          </label>
          <div className={styles.taskGrid}>
            <label>
              温度（0–2，可留空）
              <input
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={form.temperature}
                onChange={(event) =>
                  setField("temperature", event.target.value)
                }
              />
            </label>
            <label>
              最大输出 Tokens（可留空）
              <input
                type="number"
                min="1"
                step="1"
                value={form.maxOutputTokens}
                onChange={(event) =>
                  setField("maxOutputTokens", event.target.value)
                }
              />
            </label>
            <label>
              思考强度
              <select
                value={form.reasoningEffort}
                onChange={(event) => {
                  const value = event.target.value;
                  if (value === "" || value === "high" || value === "max") {
                    setField("reasoningEffort", value);
                  }
                }}
              >
                <option value="">不指定</option>
                <option value="high">high</option>
                <option value="max">max</option>
              </select>
            </label>
            <label>
              超时秒数
              <input
                required
                type="number"
                min="1"
                step="1"
                value={form.timeoutSeconds}
                onChange={(event) =>
                  setField("timeoutSeconds", event.target.value)
                }
              />
            </label>
            <label>
              结构化输出策略
              <select
                value={form.structuredOutputMode}
                onChange={(event) => {
                  const value = event.target.value;
                  if (
                    value === "auto" ||
                    value === "native" ||
                    value === "prompt"
                  ) {
                    setField("structuredOutputMode", value);
                  }
                }}
              >
                <option value="auto">自动</option>
                <option value="native">原生 JSON</option>
                <option value="prompt">提示词 JSON</option>
              </select>
            </label>
          </div>
          {setting.task_key === "attribute_memory_analysis" && (
            <div className={styles.taskGrid}>
              <label>
                记忆目标字数
                <input
                  required
                  type="number"
                  min="1"
                  step="1"
                  value={form.memoryTargetChars}
                  onChange={(event) =>
                    setField("memoryTargetChars", event.target.value)
                  }
                />
              </label>
              <label>
                记忆硬上限
                <input
                  required
                  type="number"
                  min="1"
                  step="1"
                  value={form.memoryMaxChars}
                  onChange={(event) =>
                    setField("memoryMaxChars", event.target.value)
                  }
                />
              </label>
            </div>
          )}
          <label>
            额外提示词
            <textarea
              rows={4}
              value={form.extraPrompt}
              onChange={(event) => setField("extraPrompt", event.target.value)}
            />
          </label>
          <label>
            Provider 参数 JSON
            <textarea
              className={styles.jsonEditor}
              rows={8}
              spellCheck={false}
              value={form.providerOptionsSource}
              onChange={(event) =>
                setField("providerOptionsSource", event.target.value)
              }
            />
          </label>
          <div className={styles.taskActions}>
            <button type="button" onClick={formatProviderOptions}>
              格式化 JSON
            </button>
            <button type="submit">
              {saving ? "正在保存…" : "保存任务设置"}
            </button>
          </div>
        </fieldset>
      </form>
      {message && (
        <p
          className={
            message.kind === "error" ? styles.taskError : styles.taskSuccess
          }
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}
    </section>
  );
}

export function AiSettingsPage({ api = aiSettingsApi }: AiSettingsPageProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [providerForm, setProviderForm] = useState<ProviderCreate | null>(null);
  const [editingProviderId, setEditingProviderId] = useState<number | null>(
    null,
  );
  const [modelProviderId, setModelProviderId] = useState<number | null>(null);
  const [editingModelId, setEditingModelId] = useState<number | null>(null);
  const [modelName, setModelName] = useState("");
  const [remoteModel, setRemoteModel] = useState("deepseek-v4-flash");
  const [connections, setConnections] = useState<
    Record<number, ConnectionState>
  >({});
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState({ kind: "loading" });
      try {
        const [providers, models, taskSettings] = await Promise.all([
          api.listProviders(signal),
          api.listModels(signal),
          api.listTaskSettings(signal),
        ]);
        setState({ kind: "ready", providers, models, taskSettings });
      } catch {
        if (!signal?.aborted) {
          setState({ kind: "error" });
        }
      }
    },
    [api],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function saveProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!providerForm || state.kind !== "ready") return;
    setActionError(null);
    try {
      if (editingProviderId === null) {
        const created = await api.createProvider(providerForm);
        setState({ ...state, providers: [...state.providers, created] });
      } else {
        const update: ProviderUpdate = {
          name: providerForm.name,
          provider_type: providerForm.provider_type,
          base_url: providerForm.base_url,
          enabled: providerForm.enabled,
          extra: providerForm.extra,
        };
        if (providerForm.api_key) update.api_key = providerForm.api_key;
        const updated = await api.updateProvider(editingProviderId, update);
        setState({
          ...state,
          providers: state.providers.map((item) =>
            item.id === editingProviderId ? updated : item,
          ),
        });
      }
      setProviderForm(null);
      setEditingProviderId(null);
    } catch {
      setActionError("保存 Provider 失败，请检查配置后重试。");
    }
  }

  function editProvider(item: ProviderResponse) {
    setEditingProviderId(item.id);
    setProviderForm({
      name: item.name,
      provider_type: item.provider_type,
      base_url: item.base_url,
      api_key: "",
      enabled: item.enabled,
      extra: item.extra,
    });
  }

  async function removeProvider(id: number) {
    if (state.kind !== "ready") return;
    setActionError(null);
    try {
      await api.deleteProvider(id);
      setState({
        ...state,
        providers: state.providers.filter((item) => item.id !== id),
        models: state.models.filter((item) => item.provider_id !== id),
      });
    } catch {
      setActionError("删除 Provider 失败，请重试。");
    }
  }

  async function saveModel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.kind !== "ready" || modelProviderId === null) return;
    setActionError(null);
    try {
      if (editingModelId === null) {
        const created = await api.createModel({
          provider_id: modelProviderId,
          display_name: modelName,
          remote_model: remoteModel,
          capabilities: {},
          enabled: true,
        });
        setState({ ...state, models: [...state.models, created] });
      } else {
        const updated = await api.updateModel(editingModelId, {
          display_name: modelName,
          remote_model: remoteModel,
          enabled: true,
        });
        setState({
          ...state,
          models: state.models.map((item) =>
            item.id === editingModelId ? updated : item,
          ),
        });
      }
      setModelProviderId(null);
      setEditingModelId(null);
      setModelName("");
      setRemoteModel("deepseek-v4-flash");
    } catch {
      setActionError("保存模型失败，请检查远端模型名。");
    }
  }

  function editModel(item: ModelResponse) {
    setEditingModelId(item.id);
    setModelProviderId(item.provider_id);
    setModelName(item.display_name);
    setRemoteModel(item.remote_model);
  }

  async function removeModel(id: number) {
    if (state.kind !== "ready") return;
    try {
      await api.deleteModel(id);
      setState({
        ...state,
        models: state.models.filter((item) => item.id !== id),
      });
    } catch {
      setActionError("删除模型失败，请重试。");
    }
  }

  async function testProvider(item: ProviderResponse) {
    if (state.kind !== "ready") return;
    const model = state.models.find(
      (candidate) => candidate.provider_id === item.id && candidate.enabled,
    );
    if (!model) return;
    setConnections((current) => ({ ...current, [item.id]: "loading" }));
    try {
      const result = await api.testConnection(item.id, model.id);
      setConnections((current) => ({ ...current, [item.id]: result }));
    } catch {
      setConnections((current) => ({
        ...current,
        [item.id]: {
          success: false,
          provider_type: item.provider_type,
          remote_model: model.remote_model,
          capabilities: model.capabilities,
          diagnostic: "连接测试请求失败",
          error_category: "network",
          usage: null,
        },
      }));
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>GLOBAL AI SETTINGS</p>
          <h1>Provider 与模型</h1>
          <p>集中管理连接、密钥和模型能力。密钥不会在读取时返回。</p>
        </div>
        <Link className={styles.backLink} to="/">
          返回游戏
        </Link>
      </header>

      {state.kind === "loading" && (
        <p className={styles.stateCard}>正在加载 AI 配置…</p>
      )}
      {state.kind === "error" && (
        <section className={styles.stateCard}>
          <h2>无法加载 AI 配置</h2>
          <p>本地服务暂时不可用，现有设置没有被更改。</p>
          <button type="button" onClick={() => void load()}>
            重试
          </button>
        </section>
      )}

      {state.kind === "ready" && (
        <>
          <div className={styles.toolbar}>
            <div>
              <strong>{state.providers.length}</strong> 个 Provider ·{" "}
              <strong>{state.models.length}</strong> 个模型
            </div>
            <button
              type="button"
              onClick={() => {
                setEditingProviderId(null);
                setProviderForm({ ...emptyProvider });
              }}
            >
              添加 Provider
            </button>
          </div>

          {actionError && <p className={styles.errorBanner}>{actionError}</p>}

          <section
            className={styles.taskSection}
            aria-labelledby="task-settings-title"
          >
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>GLOBAL WORKFLOW TASKS</p>
                <h2 id="task-settings-title">AI 任务设置</h2>
              </div>
              <p>保存后从下一次新轮次开始生效。</p>
            </div>
            <div className={styles.taskList}>
              {state.taskSettings.map((setting) => (
                <TaskSettingCard
                  key={setting.task_key}
                  setting={setting}
                  models={state.models}
                  api={api}
                />
              ))}
            </div>
          </section>

          {providerForm && (
            <form className={styles.formCard} onSubmit={saveProvider}>
              <h2>
                {editingProviderId === null ? "添加 Provider" : "编辑 Provider"}
              </h2>
              <div className={styles.formGrid}>
                <label>
                  Provider 名称
                  <input
                    required
                    value={providerForm.name}
                    onChange={(event) =>
                      setProviderForm({
                        ...providerForm,
                        name: event.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  Provider 类型
                  <select
                    value={providerForm.provider_type}
                    onChange={(event) => {
                      const providerType = event.target
                        .value as ProviderCreate["provider_type"];
                      setProviderForm({
                        ...providerForm,
                        provider_type: providerType,
                        base_url:
                          providerType === "deepseek"
                            ? "https://api.deepseek.com"
                            : providerForm.base_url,
                      });
                    }}
                  >
                    <option value="deepseek">DeepSeek 官方</option>
                    <option value="openai_compatible">OpenAI-compatible</option>
                  </select>
                </label>
                <label>
                  Base URL
                  <input
                    required
                    value={providerForm.base_url}
                    onChange={(event) =>
                      setProviderForm({
                        ...providerForm,
                        base_url: event.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  API Key
                  <input
                    type="password"
                    autoComplete="off"
                    placeholder={
                      editingProviderId === null
                        ? "输入 API Key"
                        : "留空保持不变"
                    }
                    value={providerForm.api_key ?? ""}
                    onChange={(event) =>
                      setProviderForm({
                        ...providerForm,
                        api_key: event.target.value,
                      })
                    }
                  />
                </label>
              </div>
              <div className={styles.formActions}>
                <button type="submit">保存 Provider</button>
                <button type="button" onClick={() => setProviderForm(null)}>
                  取消
                </button>
              </div>
            </form>
          )}

          {state.providers.length === 0 ? (
            <section className={styles.stateCard}>
              <h2>还没有 Provider</h2>
              <p>添加 DeepSeek 官方或 OpenAI-compatible 连接后，再配置模型。</p>
            </section>
          ) : (
            <div className={styles.providerList}>
              {state.providers.map((item) => {
                const providerModels = state.models.filter(
                  (candidate) => candidate.provider_id === item.id,
                );
                const connection = connections[item.id];
                return (
                  <article className={styles.providerCard} key={item.id}>
                    <div className={styles.providerHeader}>
                      <div>
                        <span className={styles.typeBadge}>
                          {item.provider_type === "deepseek"
                            ? "DeepSeek 官方"
                            : "OpenAI-compatible"}
                        </span>
                        <h2>{item.name}</h2>
                        <p>{item.base_url}</p>
                      </div>
                      <div className={styles.cardActions}>
                        <button
                          type="button"
                          onClick={() => editProvider(item)}
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          onClick={() => void removeProvider(item.id)}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                    <div className={styles.keyRow}>
                      <span>
                        {item.has_api_key
                          ? "API Key 已配置"
                          : "尚未配置 API Key"}
                      </span>
                      <button
                        type="button"
                        disabled={
                          !item.has_api_key || providerModels.length === 0
                        }
                        onClick={() => void testProvider(item)}
                      >
                        测试连接
                      </button>
                    </div>
                    <div className={styles.connectionState} aria-live="polite">
                      {connection === "loading" && "正在测试连接…"}
                      {connection &&
                        connection !== "loading" &&
                        connection.success &&
                        `连接成功 · ${connection.usage?.total_tokens ?? 0} tokens`}
                      {connection &&
                        connection !== "loading" &&
                        !connection.success &&
                        connection.diagnostic}
                    </div>

                    <div className={styles.modelHeader}>
                      <h3>模型</h3>
                      <button
                        type="button"
                        onClick={() => {
                          setEditingModelId(null);
                          setModelProviderId(item.id);
                          setModelName("");
                          setRemoteModel(
                            item.provider_type === "deepseek"
                              ? "deepseek-v4-flash"
                              : "",
                          );
                        }}
                      >
                        添加模型
                      </button>
                    </div>
                    {modelProviderId === item.id && (
                      <form className={styles.modelForm} onSubmit={saveModel}>
                        <input
                          aria-label="模型显示名称"
                          required
                          placeholder="显示名称"
                          value={modelName}
                          onChange={(event) => setModelName(event.target.value)}
                        />
                        <input
                          aria-label="远端模型名"
                          required
                          placeholder="remote model"
                          value={remoteModel}
                          onChange={(event) =>
                            setRemoteModel(event.target.value)
                          }
                        />
                        <button type="submit">保存模型</button>
                      </form>
                    )}
                    {providerModels.length === 0 ? (
                      <p className={styles.inlineEmpty}>尚未配置模型</p>
                    ) : (
                      <ul className={styles.modelList}>
                        {providerModels.map((modelItem) => (
                          <li key={modelItem.id}>
                            <span>
                              <strong>{modelItem.display_name}</strong>
                              <small>{modelItem.remote_model}</small>
                            </span>
                            <div className={styles.cardActions}>
                              <button
                                type="button"
                                aria-label={`编辑模型 ${modelItem.display_name}`}
                                onClick={() => editModel(modelItem)}
                              >
                                编辑
                              </button>
                              <button
                                type="button"
                                onClick={() => void removeModel(modelItem.id)}
                              >
                                删除
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </>
      )}
    </main>
  );
}
