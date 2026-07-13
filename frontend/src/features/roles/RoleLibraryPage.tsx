import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Link } from "react-router-dom";

import {
  type AttributeDefinition,
  type CharacterAssetResponse,
  type RoleResponse,
  type RolesApi,
  rolesApi,
} from "../../api/roles";
import styles from "./RoleLibraryPage.module.css";

interface RoleLibraryPageProps {
  api?: RolesApi;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | {
      kind: "ready";
      assets: CharacterAssetResponse[];
      roles: RoleResponse[];
    };

type AttributeDataType = AttributeDefinition["data_type"];
type AttributeOperation = AttributeDefinition["allowed_operations"][number];

interface AttributeDraft {
  draftId: string;
  persisted: boolean;
  key: string;
  displayName: string;
  dataType: AttributeDataType;
  baseValue: string;
  description: string;
  updateRule: string;
  allowedOperations: AttributeOperation[];
  minimum: string;
  maximum: string;
  enumOptions: string;
  updateExample: string;
  noUpdateExample: string;
}

interface RoleDraft {
  id: number | null;
  name: string;
  portraitUrl: string;
  persona: string;
  systemPrompt: string;
  worldBook: string;
  attributes: AttributeDraft[];
}

const operationLabels: ReadonlyArray<{
  value: AttributeOperation;
  label: string;
}> = [
  { value: "replace", label: "允许替换" },
  { value: "increment", label: "允许增加" },
  { value: "decrement", label: "允许减少" },
];

function emptyAttribute(draftId: string): AttributeDraft {
  return {
    draftId,
    persisted: false,
    key: "",
    displayName: "",
    dataType: "string",
    baseValue: "",
    description: "",
    updateRule: "",
    allowedOperations: ["replace"],
    minimum: "",
    maximum: "",
    enumOptions: "",
    updateExample: "",
    noUpdateExample: "",
  };
}

function emptyRole(): RoleDraft {
  return {
    id: null,
    name: "",
    portraitUrl: "",
    persona: "",
    systemPrompt: "",
    worldBook: "",
    attributes: [],
  };
}

function scalarText(value: number | string | boolean): string {
  return typeof value === "string" ? value : String(value);
}

function attributeFromResponse(attribute: AttributeDefinition): AttributeDraft {
  return {
    draftId: `persisted-${attribute.key}`,
    persisted: true,
    key: attribute.key,
    displayName: attribute.display_name,
    dataType: attribute.data_type,
    baseValue: scalarText(attribute.base_value),
    description: attribute.description,
    updateRule: attribute.update_rule,
    allowedOperations: [...attribute.allowed_operations],
    minimum:
      attribute.minimum === null || attribute.minimum === undefined
        ? ""
        : String(attribute.minimum),
    maximum:
      attribute.maximum === null || attribute.maximum === undefined
        ? ""
        : String(attribute.maximum),
    enumOptions: attribute.enum_options.join("\n"),
    updateExample: attribute.update_example ?? "",
    noUpdateExample: attribute.no_update_example ?? "",
  };
}

function roleFromResponse(role: RoleResponse): RoleDraft {
  return {
    id: role.id,
    name: role.name,
    portraitUrl: role.portrait_url,
    persona: role.persona,
    systemPrompt: role.system_prompt,
    worldBook: role.world_book,
    attributes: role.attributes.map(attributeFromResponse),
  };
}

function isDataType(value: string): value is AttributeDataType {
  return (
    value === "integer" ||
    value === "number" ||
    value === "string" ||
    value === "boolean" ||
    value === "enum"
  );
}

function supportedOperation(
  dataType: AttributeDataType,
  operation: AttributeOperation,
): boolean {
  return (
    operation === "replace" ||
    ((dataType === "integer" || dataType === "number") &&
      (operation === "increment" || operation === "decrement"))
  );
}

function optionalNumber(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

function parseAttribute(draft: AttributeDraft): AttributeDefinition | null {
  const enumOptions = draft.enumOptions
    .split("\n")
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
  let baseValue: number | string | boolean;
  if (draft.dataType === "integer") {
    if (draft.baseValue.trim() === "") return null;
    const parsed = Number(draft.baseValue);
    if (!Number.isInteger(parsed)) return null;
    baseValue = parsed;
  } else if (draft.dataType === "number") {
    if (draft.baseValue.trim() === "") return null;
    const parsed = Number(draft.baseValue);
    if (!Number.isFinite(parsed)) return null;
    baseValue = parsed;
  } else if (draft.dataType === "boolean") {
    baseValue = draft.baseValue === "true";
  } else {
    baseValue = draft.baseValue;
  }
  return {
    key: draft.key.trim(),
    display_name: draft.displayName.trim(),
    data_type: draft.dataType,
    base_value: baseValue,
    description: draft.description.trim(),
    update_rule: draft.updateRule.trim(),
    allowed_operations: draft.allowedOperations.filter((operation) =>
      supportedOperation(draft.dataType, operation),
    ),
    minimum:
      draft.dataType === "integer" || draft.dataType === "number"
        ? optionalNumber(draft.minimum)
        : null,
    maximum:
      draft.dataType === "integer" || draft.dataType === "number"
        ? optionalNumber(draft.maximum)
        : null,
    enum_options: draft.dataType === "enum" ? enumOptions : [],
    update_example: draft.updateExample.trim() || null,
    no_update_example: draft.noUpdateExample.trim() || null,
  };
}

function validationError(form: RoleDraft): string | null {
  if (!form.name) return "请选择角色素材";
  if (!form.persona.trim()) return "请填写基础人设";
  const keys = form.attributes.map((attribute) => attribute.key.trim());
  if (new Set(keys).size !== keys.length) return "属性 key 不能重复";
  for (const attribute of form.attributes) {
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(attribute.key.trim())) {
      return "属性 key 必须以小写字母开头，且只包含小写字母、数字和下划线";
    }
    if (
      !attribute.displayName.trim() ||
      !attribute.description.trim() ||
      !attribute.updateRule.trim()
    ) {
      return "请完整填写属性的显示名称、说明和更新规则";
    }
    if (
      (attribute.dataType === "integer" || attribute.dataType === "number") &&
      attribute.baseValue.trim() === ""
    ) {
      return "请填写有效的数值基础值";
    }
    const parsed = parseAttribute(attribute);
    if (!parsed) return "基础值必须符合属性类型";
    if (parsed.allowed_operations.length === 0) return "请至少选择一种允许操作";
    if (
      parsed.minimum !== null &&
      parsed.maximum !== null &&
      parsed.minimum !== undefined &&
      parsed.maximum !== undefined &&
      parsed.minimum > parsed.maximum
    ) {
      return "最小值不能大于最大值";
    }
    if (
      typeof parsed.base_value === "number" &&
      parsed.minimum !== null &&
      parsed.minimum !== undefined &&
      parsed.base_value < parsed.minimum
    ) {
      return "基础值不能小于最小值";
    }
    if (
      typeof parsed.base_value === "number" &&
      parsed.maximum !== null &&
      parsed.maximum !== undefined &&
      parsed.base_value > parsed.maximum
    ) {
      return "基础值不能大于最大值";
    }
    if (
      parsed.data_type === "enum" &&
      new Set(parsed.enum_options).size !== parsed.enum_options.length
    ) {
      return "枚举选项不能重复";
    }
    if (
      parsed.data_type === "enum" &&
      (parsed.enum_options.length === 0 ||
        typeof parsed.base_value !== "string" ||
        !parsed.enum_options.includes(parsed.base_value))
    ) {
      return "枚举基础值必须属于枚举选项";
    }
  }
  return null;
}

export function RoleLibraryPage({ api = rolesApi }: RoleLibraryPageProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [form, setForm] = useState<RoleDraft | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const nextAttributeId = useRef(0);
  const mutationPending = saving || deletingId !== null;

  function createEmptyAttribute(): AttributeDraft {
    nextAttributeId.current += 1;
    return emptyAttribute(`new-${nextAttributeId.current}`);
  }

  const load = useCallback(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    setActionError(null);
    void Promise.all([
      api.listAssets(controller.signal),
      api.listRoles(controller.signal),
    ]).then(
      ([assetsResponse, rolesResponse]) => {
        setState({
          kind: "ready",
          assets: assetsResponse,
          roles: rolesResponse,
        });
      },
      (error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setState({ kind: "error" });
        }
      },
    );
    return controller;
  }, [api]);

  useEffect(() => {
    const controller = load();
    return () => controller.abort();
  }, [load]);

  function updateAttribute(index: number, update: Partial<AttributeDraft>) {
    setForm((current) => {
      if (!current) return current;
      return {
        ...current,
        attributes: current.attributes.map((attribute, candidateIndex) =>
          candidateIndex === index ? { ...attribute, ...update } : attribute,
        ),
      };
    });
  }

  function selectType(index: number, event: ChangeEvent<HTMLSelectElement>) {
    if (!isDataType(event.target.value)) return;
    const dataType = event.target.value;
    updateAttribute(index, {
      dataType,
      baseValue: dataType === "boolean" ? "false" : "",
      allowedOperations: ["replace"],
      minimum: "",
      maximum: "",
      enumOptions: "",
    });
  }

  function selectAsset(roleName: string) {
    if (state.kind !== "ready") return;
    const asset = state.assets.find(
      (candidate) => candidate.role_name === roleName,
    );
    setForm((current) =>
      current
        ? {
            ...current,
            name: asset?.role_name ?? "",
            portraitUrl: asset?.portrait_url ?? "",
          }
        : current,
    );
  }

  async function saveRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form || state.kind !== "ready" || mutationPending) return;
    const error = validationError(form);
    if (error) {
      setActionError(error);
      return;
    }
    const attributes = form.attributes
      .map(parseAttribute)
      .filter(
        (attribute): attribute is AttributeDefinition => attribute !== null,
      );
    setSaving(true);
    setActionError(null);
    try {
      const saved =
        form.id === null
          ? await api.createRole({
              name: form.name,
              persona: form.persona.trim(),
              system_prompt: form.systemPrompt,
              world_book: form.worldBook,
              attributes,
            })
          : await api.updateRole(form.id, {
              persona: form.persona.trim(),
              system_prompt: form.systemPrompt,
              world_book: form.worldBook,
              attributes,
            });
      setState((current) =>
        current.kind === "ready"
          ? {
              ...current,
              roles:
                form.id === null
                  ? [...current.roles, saved]
                  : current.roles.map((role) =>
                      role.id === saved.id ? saved : role,
                    ),
            }
          : current,
      );
      setForm(null);
    } catch {
      setActionError("保存角色失败，请检查角色资料后重试。");
    } finally {
      setSaving(false);
    }
  }

  async function deleteRole(role: RoleResponse) {
    if (
      state.kind !== "ready" ||
      mutationPending ||
      role.referenced_world_ids.length > 0
    ) {
      return;
    }
    setDeletingId(role.id);
    setActionError(null);
    try {
      await api.deleteRole(role.id);
      setState((current) =>
        current.kind === "ready"
          ? {
              ...current,
              roles: current.roles.filter(
                (candidate) => candidate.id !== role.id,
              ),
            }
          : current,
      );
      setConfirmDeleteId(null);
    } catch {
      setActionError("删除角色失败；请刷新引用状态后重试。");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>GLOBAL ROLE LIBRARY</p>
          <h1>角色库</h1>
          <p>管理全局角色的基础资料、属性定义与受控更新规则。</p>
        </div>
        <nav className={styles.navigation} aria-label="全局导航">
          <Link className={styles.backLink} to="/">
            返回世界
          </Link>
          <Link className={styles.backLink} to="/settings/ai">
            AI 设置
          </Link>
        </nav>
      </header>

      {state.kind === "loading" && (
        <p className={styles.stateCard}>正在加载角色库…</p>
      )}
      {state.kind === "error" && (
        <section className={styles.stateCard}>
          <h2>无法加载角色库</h2>
          <p>角色和本地素材都没有被更改，请检查本地服务后重试。</p>
          <button type="button" onClick={() => void load()}>
            重试
          </button>
        </section>
      )}

      {state.kind === "ready" && (
        <>
          <section className={styles.toolbar}>
            <span>
              <strong>{state.roles.length}</strong> 个角色 ·{" "}
              <strong>{state.assets.length}</strong> 个可用素材
            </span>
            <button
              type="button"
              disabled={mutationPending || state.assets.length === 0}
              title={
                state.assets.length === 0
                  ? "请先在角色资源目录中添加有效的同名立绘"
                  : undefined
              }
              onClick={() => {
                setActionError(null);
                setForm(emptyRole());
              }}
            >
              创建角色
            </button>
          </section>

          {actionError && (
            <p className={styles.errorBanner} role="alert">
              {actionError}
            </p>
          )}

          {form && (
            <form
              className={styles.formCard}
              aria-busy={saving}
              noValidate
              onSubmit={(event) => void saveRole(event)}
            >
              <div className={styles.formHeading}>
                <div>
                  <span className={styles.typeBadge}>
                    {form.id === null ? "新角色" : "编辑角色"}
                  </span>
                  <h2>{form.name || "选择角色素材"}</h2>
                </div>
                {form.portraitUrl && (
                  <img
                    className={styles.portrait}
                    src={form.portraitUrl}
                    alt={`${form.name} 默认立绘`}
                  />
                )}
              </div>

              <div className={styles.formGrid}>
                {form.id === null ? (
                  <label>
                    角色素材
                    <select
                      value={form.name}
                      disabled={mutationPending}
                      onChange={(event) => selectAsset(event.target.value)}
                    >
                      <option value="">请选择同名素材目录</option>
                      {state.assets.map((asset) => (
                        <option key={asset.role_name} value={asset.role_name}>
                          {asset.role_name}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label>
                    角色名称
                    <input disabled value={form.name} />
                  </label>
                )}
                <label className={styles.fullWidth}>
                  基础人设
                  <textarea
                    value={form.persona}
                    disabled={mutationPending}
                    onChange={(event) =>
                      setForm({ ...form, persona: event.target.value })
                    }
                  />
                </label>
                <label className={styles.fullWidth}>
                  系统提示词
                  <textarea
                    value={form.systemPrompt}
                    disabled={mutationPending}
                    onChange={(event) =>
                      setForm({ ...form, systemPrompt: event.target.value })
                    }
                  />
                </label>
                <label className={styles.fullWidth}>
                  世界书
                  <textarea
                    value={form.worldBook}
                    disabled={mutationPending}
                    onChange={(event) =>
                      setForm({ ...form, worldBook: event.target.value })
                    }
                  />
                </label>
              </div>

              <div className={styles.attributeHeading}>
                <div>
                  <h3>平铺属性定义</h3>
                  <p>
                    这里只编辑基础值与规则；移除旧 key
                    后再新增，视为删除再创建。
                  </p>
                </div>
                <button
                  type="button"
                  disabled={mutationPending}
                  onClick={() =>
                    setForm({
                      ...form,
                      attributes: [...form.attributes, createEmptyAttribute()],
                    })
                  }
                >
                  添加属性
                </button>
              </div>

              {form.attributes.length === 0 && (
                <p className={styles.inlineEmpty}>尚未定义动态属性。</p>
              )}
              <div className={styles.attributeList}>
                {form.attributes.map((attribute, index) => (
                  <fieldset
                    className={styles.attributeCard}
                    key={attribute.draftId}
                  >
                    <legend>属性 {index + 1}</legend>
                    <div className={styles.formGrid}>
                      <label>
                        属性 key
                        <input
                          value={attribute.key}
                          disabled={mutationPending || attribute.persisted}
                          onChange={(event) =>
                            updateAttribute(index, { key: event.target.value })
                          }
                        />
                      </label>
                      <label>
                        显示名称
                        <input
                          value={attribute.displayName}
                          disabled={mutationPending}
                          onChange={(event) =>
                            updateAttribute(index, {
                              displayName: event.target.value,
                            })
                          }
                        />
                      </label>
                      <label>
                        属性类型
                        <select
                          value={attribute.dataType}
                          disabled={mutationPending}
                          onChange={(event) => selectType(index, event)}
                        >
                          <option value="string">文本</option>
                          <option value="integer">整数</option>
                          <option value="number">数值</option>
                          <option value="boolean">布尔值</option>
                          <option value="enum">枚举</option>
                        </select>
                      </label>
                      <div className={styles.formField}>
                        <label htmlFor={`base-value-${attribute.draftId}`}>
                          基础值
                        </label>
                        {attribute.dataType === "boolean" ? (
                          <select
                            id={`base-value-${attribute.draftId}`}
                            value={attribute.baseValue}
                            disabled={mutationPending}
                            onChange={(event) =>
                              updateAttribute(index, {
                                baseValue: event.target.value,
                              })
                            }
                          >
                            <option value="false">否</option>
                            <option value="true">是</option>
                          </select>
                        ) : (
                          <input
                            id={`base-value-${attribute.draftId}`}
                            type={
                              attribute.dataType === "integer" ||
                              attribute.dataType === "number"
                                ? "number"
                                : "text"
                            }
                            step={
                              attribute.dataType === "integer" ? "1" : "any"
                            }
                            value={attribute.baseValue}
                            disabled={mutationPending}
                            onChange={(event) =>
                              updateAttribute(index, {
                                baseValue: event.target.value,
                              })
                            }
                          />
                        )}
                      </div>
                      <label className={styles.fullWidth}>
                        属性说明
                        <textarea
                          value={attribute.description}
                          disabled={mutationPending}
                          onChange={(event) =>
                            updateAttribute(index, {
                              description: event.target.value,
                            })
                          }
                        />
                      </label>
                      <label className={styles.fullWidth}>
                        更新规则
                        <textarea
                          value={attribute.updateRule}
                          disabled={mutationPending}
                          onChange={(event) =>
                            updateAttribute(index, {
                              updateRule: event.target.value,
                            })
                          }
                        />
                      </label>
                    </div>

                    <div className={styles.operations}>
                      {operationLabels.map((operation) => {
                        const supported = supportedOperation(
                          attribute.dataType,
                          operation.value,
                        );
                        return (
                          <label key={operation.value}>
                            <input
                              type="checkbox"
                              checked={
                                supported &&
                                attribute.allowedOperations.includes(
                                  operation.value,
                                )
                              }
                              disabled={mutationPending || !supported}
                              onChange={(event) => {
                                const operations = event.target.checked
                                  ? [
                                      ...attribute.allowedOperations,
                                      operation.value,
                                    ]
                                  : attribute.allowedOperations.filter(
                                      (candidate) =>
                                        candidate !== operation.value,
                                    );
                                updateAttribute(index, {
                                  allowedOperations: operations,
                                });
                              }}
                            />
                            {operation.label}
                          </label>
                        );
                      })}
                    </div>

                    {(attribute.dataType === "integer" ||
                      attribute.dataType === "number") && (
                      <div className={styles.formGrid}>
                        <label>
                          最小值
                          <input
                            type="number"
                            value={attribute.minimum}
                            disabled={mutationPending}
                            onChange={(event) =>
                              updateAttribute(index, {
                                minimum: event.target.value,
                              })
                            }
                          />
                        </label>
                        <label>
                          最大值
                          <input
                            type="number"
                            value={attribute.maximum}
                            disabled={mutationPending}
                            onChange={(event) =>
                              updateAttribute(index, {
                                maximum: event.target.value,
                              })
                            }
                          />
                        </label>
                      </div>
                    )}
                    {attribute.dataType === "enum" && (
                      <label className={styles.stackedLabel}>
                        枚举选项（每行一个）
                        <textarea
                          value={attribute.enumOptions}
                          disabled={mutationPending}
                          onChange={(event) =>
                            updateAttribute(index, {
                              enumOptions: event.target.value,
                            })
                          }
                        />
                      </label>
                    )}
                    <div className={styles.formGrid}>
                      <label>
                        更新示例
                        <textarea
                          value={attribute.updateExample}
                          disabled={mutationPending}
                          onChange={(event) =>
                            updateAttribute(index, {
                              updateExample: event.target.value,
                            })
                          }
                        />
                      </label>
                      <label>
                        不更新示例
                        <textarea
                          value={attribute.noUpdateExample}
                          disabled={mutationPending}
                          onChange={(event) =>
                            updateAttribute(index, {
                              noUpdateExample: event.target.value,
                            })
                          }
                        />
                      </label>
                    </div>
                    <button
                      type="button"
                      disabled={mutationPending}
                      onClick={() =>
                        setForm({
                          ...form,
                          attributes: form.attributes.filter(
                            (_candidate, candidateIndex) =>
                              candidateIndex !== index,
                          ),
                        })
                      }
                    >
                      移除属性 {index + 1}
                    </button>
                  </fieldset>
                ))}
              </div>

              <div className={styles.formActions}>
                <button type="submit" disabled={mutationPending}>
                  {saving ? "正在保存…" : "保存角色"}
                </button>
                <button
                  type="button"
                  disabled={mutationPending}
                  onClick={() => setForm(null)}
                >
                  取消
                </button>
              </div>
            </form>
          )}

          {state.roles.length === 0 ? (
            <section className={styles.stateCard}>
              <h2>角色库还是空的</h2>
              <p>从本地同名素材目录创建第一个全局角色。</p>
            </section>
          ) : (
            <section className={styles.roleList} aria-label="角色列表">
              {state.roles.map((role) => (
                <article
                  className={styles.roleCard}
                  aria-label={`角色 ${role.name}`}
                  key={role.id}
                >
                  <img
                    className={styles.portrait}
                    src={role.portrait_url}
                    alt={`${role.name} 默认立绘`}
                  />
                  <div className={styles.roleSummary}>
                    <h2>{role.name}</h2>
                    <p>{role.persona}</p>
                    <small>
                      {role.attributes.length} 个属性 · 版本 {role.version}
                    </small>
                    <p className={styles.references}>
                      {role.referenced_world_ids.length > 0
                        ? `引用世界：${role.referenced_world_ids.join("、")}`
                        : "尚未被世界引用"}
                    </p>
                  </div>
                  <div className={styles.cardActions}>
                    <button
                      type="button"
                      disabled={mutationPending}
                      aria-label={`编辑角色 ${role.name}`}
                      onClick={() => {
                        setActionError(null);
                        setForm(roleFromResponse(role));
                      }}
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      disabled={
                        saving ||
                        deletingId !== null ||
                        role.referenced_world_ids.length > 0
                      }
                      aria-label={`删除角色 ${role.name}`}
                      title={
                        role.referenced_world_ids.length > 0
                          ? "角色仍被世界引用，不能删除"
                          : undefined
                      }
                      onClick={() => setConfirmDeleteId(role.id)}
                    >
                      删除
                    </button>
                    {confirmDeleteId === role.id && (
                      <div className={styles.confirmation} role="alert">
                        <span>删除后无法恢复。</span>
                        <button
                          type="button"
                          disabled={deletingId === role.id}
                          onClick={() => void deleteRole(role)}
                        >
                          {deletingId === role.id
                            ? "正在删除…"
                            : `确认删除 ${role.name}`}
                        </button>
                        <button
                          type="button"
                          disabled={deletingId === role.id}
                          onClick={() => setConfirmDeleteId(null)}
                        >
                          取消删除
                        </button>
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </section>
          )}
        </>
      )}
    </main>
  );
}
