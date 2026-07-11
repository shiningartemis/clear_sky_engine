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
} from "../../api/aiSettings";
import styles from "./AiSettingsPage.module.css";

interface AiSettingsPageProps {
  api?: AiSettingsApi;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; providers: ProviderResponse[]; models: ModelResponse[] };

type ConnectionState = "loading" | ConnectionTestResponse;

const emptyProvider: ProviderCreate = {
  name: "",
  provider_type: "deepseek",
  base_url: "https://api.deepseek.com",
  api_key: "",
  enabled: true,
  extra: {},
};

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
        const [providers, models] = await Promise.all([
          api.listProviders(signal),
          api.listModels(signal),
        ]);
        setState({ kind: "ready", providers, models });
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
          defaults: {},
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
