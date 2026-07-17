# 合并阶段 4+5：完整可玩纵向闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox state, and this root `plan.md` is the only implementation-plan, progress, verification, and decision record.

**Goal:** 在现有阶段 1–3 基础上完成一版可从网页真正游玩的单线世界推演：玩家移动主角、提交自由意图，系统按地图并行推演全部已定位角色，生成各角色独立纪事、客观事件、属性与记忆变化，并且只在整轮成功时原子推进时间。

**Architecture:** 保持单进程模块化单体。每次轮次先在短数据库会话中冻结世界、角色位置、角色上下文和两个应用级 AI 任务配置，再在进程内通过 `asyncio.TaskGroup` 并行运行各地图的“地点推演 → 属性与记忆分析”链；所有输出通过统一 Schema、信息边界和状态命令校验后，才在一个短事务中写成功轮次。未完成运行及中间结果不入库。

**Tech Stack:** Python 3.14.6、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、SQLite、HTTPX、React 19.2、TypeScript 5.9、Vite、Phaser 4.2、Vitest/RTL、Playwright 1.61、PyInstaller onedir。

**Global Constraints:** `AGENTS.md`、`需求与产品设计.md`、`技术选型文档.md` 是实现约束；本文件是唯一任务与进度事实来源。不得另建平行计划、进度、决策或异常审查文档。不得加入 mock AI 轮次 Playwright、分支/快照 UI、持久化运行表、任意工作流 CRUD、模型 fallback、长期记忆压缩或核心文档禁止的框架与服务。

---

## 1. 跨窗口执行协议

每个新开发窗口必须按以下顺序开始：

1. 读取根 `AGENTS.md`。
2. 读取本文件的“当前状态”、当前任务和直接依赖；只在产品契约不清楚时读取 `需求与产品设计.md` 对应章节，只在技术契约不清楚时读取 `技术选型文档.md` 对应章节。
3. 运行 `git status --short --branch`，保留所有已有和无关改动。当前已知 `AGENTS.md` 有用户自己的未提交修改，除非用户另行要求，不得覆盖、暂存或提交它。
4. 一次只实施一个任务。严格执行“失败测试 → 确认按预期失败 → 最小实现 → 聚焦测试 → `scripts\check.ps1` → 更新本文件 → 任务级提交”。
5. 只有实际验证通过才能勾选。若被外部环境阻塞，保持未勾选并在“阻塞项”记录事实，不得写“预计通过”。
6. 每次任务提交只暂存该任务的代码、测试、生成物和 `plan.md`，不得使用 `git add .`。

计划状态标记：

- `[ ]` 未开始或未通过完整门禁；
- `[x]` 已实现且验证证据已经写入本文件；
- 正在进行的唯一任务由“当前执行点”指明，不另造状态符号。

## 2. 当前状态

- 当前执行点：任务 5——结构化 AI Schema、状态快照与 ContextBuilder 已完成并停止在任务边界；任务 6 尚未开始。
- 任务 1 开始基线提交：`7cf00d2 docs: define merged phase 4 and 5 implementation plan`。
- [x] 阶段 1：工程、本地运行、安全启动器、检查脚本和 onedir 构建基线完成；干净 Windows 11 x64 仍作为最终发布门禁保留。
- [x] 阶段 2：Provider/Model 管理、OpenAI-compatible、DeepSeek、普通/流式/JSON/Tool Calls 和真实 API 验证完成。
- [x] 阶段 3：全局角色、世界、动态属性、位置规则、地图、真实立绘和阶段 3 浏览器流程完成。
- [x] 合并阶段 4+5 产品与技术设计已逐项核对并写入两份核心文档。
- [ ] 合并阶段 4+5：任务 1–15 全部完成。

已存在且必须保留的世界创建回归基线：`backend/tests/world/test_world_api.py` 已验证世界只引用已有角色、同一角色可创建多个世界、失败时世界相关行回滚。任务 13 还要从真实浏览器强化为“创建世界前后角色数量、ID 和角色主数据不变”的永久回归，杜绝曾发生的角色唯一键冲突。

## 3. 交付顺序

| 顺序 | 任务 | 依赖 | 交付门禁 |
|---|---|---|---|
| 1 | 数据库与持久化模型 | 阶段 3 | 空库到 head、升级路径、约束 |
| 2 | 全局 AI 任务设置后端 | 1 | 固定两任务、参数校验、配置冻结读取 |
| 3 | 全局 AI 任务设置前端 | 2 | JSON 编辑器、冲突定位、保存反馈 |
| 4 | NPC 二次缓存位置分配 | 阶段 3 | 纯函数、确定性、显式 offline |
| 5 | AI 输出 Schema 与 ContextBuilder | 1、4 | 地图边界、角色知识隔离、最近 5 轮 |
| 6 | AI 节点调用与重试 | 2、5 | 每节点总计最多 3 次、无嵌套重试 |
| 7 | 进程内地图并行执行器 | 5、6 | 地图间并行、地图内串联、取消与单活动轮次 |
| 8 | 原子结算与历史查询 | 1、4、5、7 | 故事/事件/属性/记忆/时间一次提交 |
| 9 | 轮次 API 与 NDJSON 生命周期 | 7、8 | 创建、状态、流、取消、断线清理 |
| 10 | 前端轮次 API 与流状态 | 9 | 分块、空行、终态去重、Abort |
| 11 | 游戏主界面完整交互 | 3、10 | 意图、进度、失败保留、轮次卡片 |
| 12 | 确定性纵向集成回归 | 1–11 | 全链路、并发、重试、原子性、信息隔离 |
| 13 | 真实 AI Playwright | 12 | 网页从零操作至少两轮；不使用 mock AI |
| 14 | 异常闭环专项 code review | 12、13 | 错误、重试、取消、断线、原子性审查 |
| 15 | 全量检查、打包与干净机验收 | 1–14 | check、live AI、Playwright、build、Win11 |

### 3.1 第一版 38 项验收映射

| 验收项 | 对应实现/证据 |
|---|---|
| 1. Windows 11 无需预装 Python | 任务 15 onedir 与干净机 |
| 2. 仅监听 127.0.0.1 并自动开浏览器 | 阶段 1 基线 + 任务 15 回归 |
| 3. DeepSeek/OpenAI-compatible Provider 与模型 | 阶段 2 基线 + 任务 3、13 |
| 4. 两个全局 AI 任务独立配置 | 任务 1–3、13 |
| 5. 多世界隔离 | 阶段 3 基线 + 任务 8、12 |
| 6. 唯一主角且世界只引用已有角色 | 阶段 3 基线 + 任务 12、13 唯一键永久回归 |
| 7. 至少 20 个唯一角色、常用 NPC 数量流畅 | 阶段 3 基线 + 任务 12、13 |
| 8. 人设、世界书、动态属性、规则、立绘与删除保护 | 阶段 3 基线 + 任务 12、13 |
| 9. 总地图键鼠进入 | 阶段 3 Playwright + 任务 13 回归 |
| 10. 六地点进入与返回 | 阶段 3 Playwright + 任务 13 回归 |
| 11. 7 张可替换 16:9 地图 | 阶段 3资源测试 + 任务 15 打包回归 |
| 12. 背景 cover、立绘 1:1 contain | 阶段 3浏览器证据 + 任务 13 回归 |
| 13. 主角预留位、5 NPC、二次缓存、offline | 任务 4、12、13 |
| 14. 移动不推进时间，提交才推演 | 任务 8、11–13 |
| 15. 四时间段、天数、星期推进 | 任务 8、12、13 |
| 16. 只有同地点角色直接互动 | 任务 5、12、13 |
| 17. 玩家意图始终是主角尝试，缺席目标仍可提交 | 任务 5、11–13 |
| 18. 互动组完整、唯一且可包含 NPC 自由互动 | 任务 5、12、13 |
| 19. 所有有角色地图并行两节点链 | 任务 6、7、12、13 |
| 20. 所有启用角色独立纪事、独处极短、离线固定说明 | 任务 5、8、11–13 |
| 21. 角色知识与记忆严格隔离 | 任务 5、12、14 |
| 22. 每地图一次属性与记忆分析，语义由 AI 判断 | 任务 5–8、12 |
| 23. 基础值与变化值合成、三类操作与约束 | 阶段 3基线 + 任务 5、8、12 |
| 24. 每世界角色唯一记忆、20/50、`__` 原子追加 | 任务 1–3、5、8、12、13 |
| 25. 成功轮次保存与主界面折叠卡片 | 任务 1、8、9、11、13 |
| 26. 每失败节点最多三次且只重试失败节点 | 任务 6、7、12、14 |
| 27. 地图进度、次数、重试、数量、耗时和取消 | 任务 7、9–11、13 |
| 28. 失败/取消/断线/退出不留脏数据、不推进时间 | 任务 7–9、12、14 |
| 29. 新配置下轮生效、运行配置冻结、无 fallback | 任务 2、3、6、7、12 |
| 30. 世界间变化、规则、故事、记忆不串线 | 任务 1、5、8、12 |
| 31. API Key 不进入查询、日志、异常、Prompt、故事、历史 | 阶段 2 基线 + 任务 2、6、9、13、14 |
| 32. 空库迁移、记忆唯一、原子提交和无脏数据 | 任务 1、8、12、15 |
| 33. 异常路径专项 code review 与自然异常回归 | 任务 14 |
| 34. 真实浏览器永久回归世界创建重复插入角色 | 任务 13 |
| 35. 真实 AI 网页从配置到至少两轮完整闭环 | 任务 13 |
| 36. 不建设默认离线模拟 Playwright | 任务 13、15 |
| 37. 三张角色图片只作隔离测试素材 | 阶段 3 基线 + 任务 13 |
| 38. 干净 Windows 11 onedir 真实可玩冒烟 | 任务 15 |

---

## 任务 1：合并阶段数据库与持久化模型

**Files**

- Create: `backend/migrations/versions/0004_merged_turn_loop.py`
- Create: `backend/src/app/workflow/__init__.py`
- Create: `backend/src/app/workflow/models.py`
- Create: `backend/src/app/story/__init__.py`
- Create: `backend/src/app/story/models.py`
- Modify: `backend/src/app/ai/models.py`
- Modify: `backend/src/app/ai/service.py`
- Modify: `backend/src/app/api/providers.py`
- Modify: `backend/src/app/world/models.py`
- Modify: `backend/src/app/world/service.py`
- Create: `backend/tests/test_phase45_migrations.py`
- Modify: `backend/tests/test_migrations.py`
- Modify: `backend/tests/test_phase3_migrations.py`
- Modify: `backend/tests/test_provider_migrations.py`
- Modify: `backend/tests/test_provider_api.py`
- Modify: `backend/tests/ai/test_live_config.py`
- Modify: `backend/tests/world/test_world_api.py`
- Modify generated: `frontend/src/api/generated.ts` through `scripts/generate-api.ps1`
- Modify: `frontend/src/api/aiSettings.ts`
- Modify: `frontend/src/api/aiSettings.test.ts`
- Modify: `frontend/src/features/ai-settings/AiSettingsPage.tsx`
- Modify: `frontend/src/features/ai-settings/AiSettingsPage.test.tsx`

**Persistent contract**

- `ai_model.defaults_json` 必须由迁移移除；Provider/Model 只保存身份、连接和能力声明。
- 新建 `ai_task_setting`，只允许 `location_simulation`、`attribute_memory_analysis` 两行。迁移插入两行初始配置，`model_id` 初始允许为空；轮次启动层负责拒绝未选模型。
- 新建 `world_role_memory`，以 `(world_id, role_id)` 唯一并复合外键引用 `world_role_state`，`memory` 初始空字符串。迁移必须为全部既有 world_role_state 回填空记忆；以后创建世界主角或加入 NPC 时，在同一事务创建 version=1 的空记忆行。
- 新建 `turn`、`turn_story`、`turn_event`、`turn_event_participant`、`state_change`。只保存成功轮次，不建 `turn_run` 或 `turn_task_run`。字段严格采用 `技术选型文档.md` 12.5：turn 保存 world/branch/parent、提交时 day/time_slot、player_intent、客观事件 JSON、状态快照和安全 AI 元数据；story 绑定非空 role_id；event 绑定 location；participant 保存 knowledge_level/perspective_notes；state_change 保存 old/operand/new、操作、理由和可空 event_id。
- `turn_story` 只持久化获得 AI 纪事的已定位角色；离线角色的固定短说明由历史 DTO 根据 `turn.state_after_json.turn_positions` 合成，因此离线轮次自然不进入最近 5 个有效轮次。
- `state_after_json` 采用稳定结构：`turn_positions` 保存本轮冻结位置，`after` 保存成功结算后的 day、time_slot、主角地点和下一时段 NPC 位置。

关键 ORM 形状必须一致：

```python
class AiTaskSetting(Base):
    __tablename__ = "ai_task_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_key: Mapped[str] = mapped_column(String(40), unique=True)
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_model.id", ondelete="RESTRICT"), nullable=True
    )
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    extra_prompt: Mapped[str] = mapped_column(Text)
    structured_output_mode: Mapped[str] = mapped_column(String(20))
    provider_options_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    memory_target_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

```python
class WorldRoleMemory(Base):
    __tablename__ = "world_role_memory"
    __table_args__ = (
        ForeignKeyConstraint(
            ["world_id", "role_id"],
            ["world_role_state.world_id", "world_role_state.role_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("world_id", "role_id", name="uq_world_role_memory_world_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[int] = mapped_column(Integer)
    role_id: Mapped[int] = mapped_column(Integer)
    memory: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

**Steps**

- [x] 先写空库到 head、`0003 -> 0004`、固定任务行、移除 `defaults_json`、既有世界角色记忆回填、所有外键/唯一/检查约束和级联删除测试。
- [x] 运行 `uv run pytest backend/tests/test_phase45_migrations.py backend/tests/test_provider_migrations.py -q`，确认因 `0004` 和模型不存在而失败。
- [x] 实现迁移与 ORM；不得编辑 `0001`–`0003` 已发布迁移。
- [x] 验证 downgrade 后可重新 upgrade 到 head，且升级已有 Provider/Model/世界/角色数据不丢失。
- [x] 运行聚焦测试、Ruff、Pyright，再运行 `./scripts/check.ps1`。
- [x] 更新本文件当前执行点、勾选项和验证记录；精确暂存本任务文件并提交 `feat: add merged turn persistence schema`。

**Expected:** 所有命令 exit 0；SQLite schema 不存在运行表；两条任务设置分别带稳定 task_key，记忆和轮次表约束生效。

---

## 任务 2：全局 AI 任务设置后端

**Files**

- Create: `backend/src/app/workflow/settings.py`
- Create: `backend/src/app/workflow/store.py`
- Create: `backend/src/app/api/ai_tasks.py`
- Modify: `backend/src/app/ai/service.py`
- Modify: `backend/src/app/api/providers.py`
- Modify: `backend/src/app/main.py`
- Create: `backend/tests/workflow/__init__.py`
- Create: `backend/tests/workflow/test_task_settings.py`
- Create: `backend/tests/test_ai_task_api.py`
- Modify: `backend/tests/test_provider_api.py`

**Contract**

```python
class TaskKey(StrEnum):
    LOCATION_SIMULATION = "location_simulation"
    ATTRIBUTE_MEMORY_ANALYSIS = "attribute_memory_analysis"


class StructuredOutputMode(StrEnum):
    AUTO = "auto"
    NATIVE = "native"
    PROMPT = "prompt"
```

每个设置 DTO 必须包含模型、温度、最大输出 Tokens、思考强度、超时、额外提示词、结构化输出策略、任意 Provider JSON 和版本；属性与记忆任务另外包含 `memory_target_chars` 和 `memory_max_chars`，初始为 20/50。保存成功递增版本，并对下一次新轮次生效。

自由 Provider JSON 根节点必须为对象。规范化后禁止与以下程序拥有字段冲突：

```python
PROTECTED_PROVIDER_OPTION_KEYS = frozenset(
    {
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
    }
)
```

未知 Provider 字段不做语义校验，原样保存；错误响应必须指出冲突字段。模型能力 `capabilities_json.json_output` 决定是否能使用原生 JSON。`native` 模式遇到不支持模型时拒绝保存；`auto` 自动选择原生 JSON 或提示词 JSON；`prompt` 始终提示词约束。不得自动选模或 fallback。

**Steps**

- [x] 先写固定 task_key、模型存在/启用、字段范围、20≤50、JSON 根对象、保留字段冲突、版本递增和配置快照不可变测试。
- [x] 写 API 测试：`GET /api/ai-task-settings` 固定返回两项；`PUT /api/ai-task-settings/{task_key}` 更新一项；缺模型仍可查看但不能作为可运行快照。
- [x] 保留任务 1 已完成的 Provider API 回归：Model 请求/响应不含 `defaults`，旧请求字段以 422 拒绝。
- [x] 运行聚焦测试确认按预期失败。
- [x] 实现 Store/Service/Router，在 `create_app` 注入同一服务；慢 AI I/O 不在这些同步短事务中发生。
- [x] 运行 `./scripts/generate-api.ps1` 生成类型，不手改 `frontend/src/api/generated.ts`。
- [x] 运行聚焦测试与 `./scripts/check.ps1`，更新本文件并提交 `feat: add global ai task settings`。

**Expected:** 设置来源只有 `ai_task_setting`；`ai_model` 不再携带行为参数；查询和错误不包含 API Key。

---

## 任务 3：全局 AI 任务设置前端与 JSON 编辑器（已完成，2026-07-16）

**Files**

- Modify: `frontend/src/api/aiSettings.ts`
- Modify: `frontend/src/api/aiSettings.test.ts`
- Modify: `frontend/src/features/ai-settings/AiSettingsPage.tsx`
- Modify: `frontend/src/features/ai-settings/AiSettingsPage.module.css`
- Modify: `frontend/src/features/ai-settings/AiSettingsPage.test.tsx`
- Modify generated: `frontend/src/api/generated.ts` through `scripts/generate-api.ps1`

**UX contract**

- AI 设置页保留 Provider/Model 管理，并新增“地点推演”“属性与记忆分析”两个固定任务卡片；不是每个世界一份配置。
- 每张卡片显式选择模型并编辑任务参数。属性与记忆卡片显示目标 20、硬上限 50，校验目标不得大于上限。
- Provider 参数使用独立多行 JSON 编辑框，提供“格式化 JSON”；语法错误显示行号、列号，根节点非对象或保留字段冲突定位到字段。
- 保存 loading 时禁用本卡片；成功显示“下一次新轮次生效”；失败保留全部输入。
- Model `defaults` 表单已在任务 1 随持久化/API 契约原子移除；本任务不得重新引入第二参数来源。

推荐的前端解析边界：

```ts
export interface JsonObjectParseResult {
  value: Record<string, unknown> | null;
  error: { message: string; line: number; column: number } | null;
}

export function parseJsonObjectEditor(source: string): JsonObjectParseResult;
```

实现时必须给出真实函数体和单测，不能用类型断言绕过未知 JSON。

**Steps**

- [x] 先写 API 转换、两个任务卡片、字段校验、格式化、语法行列、冲突字段及 loading/error/success 的 RTL/Vitest 测试，并保留任务 1 的 Model defaults 消失回归。
- [x] 运行 `npm --prefix frontend run test -- --run src/api/aiSettings.test.ts src/features/ai-settings/AiSettingsPage.test.tsx`，确认新行为失败。
- [x] 最小实现 JSON 编辑器和固定任务表单，不引入编辑器或表单依赖。
- [x] 运行聚焦测试、Biome、TypeScript、Vite build 和 `./scripts/check.ps1`。
- [x] 更新本文件并提交 `feat: add ai task configuration ui`。

**Expected:** 开发商只在一个全局页面配置两任务；任意 JSON 可编辑且格式问题可操作；世界创建页无任务参数。

**验证记录（2026-07-16）**

- RED：`npm --prefix frontend run test -- --run src/api/aiSettings.test.ts src/features/ai-settings/AiSettingsPage.test.tsx`，11 failed / 7 passed；失败点为缺少任务设置 API、JSON 解析器和两张固定任务卡片。
- GREEN：同一聚焦命令，2 个测试文件、18 tests passed。
- OpenAPI：`./scripts/generate-api.ps1` 成功，`frontend/src/api/generated.ts` 无漂移；沙箱内首次运行因 uv 用户缓存不可访问失败，获批在沙箱外原命令重跑通过。
- 前端分项：`npm --prefix frontend run check` 通过（49 files）；`npm --prefix frontend run typecheck` 通过；`npm --prefix frontend run build` 通过（Vite 46 modules，保留既有 >1500 kB chunk 警告）。
- 全量：`./scripts/check.ps1` 沙箱外通过；后端 216 passed、6 deselected，前端 15 个测试文件、138 tests passed，Ruff format/check、Pyright、Biome、TypeScript 与 Vite build 均通过。

**独立审查修复验证（2026-07-16）**

- 修复固定任务集合边界：响应必须恰好包含 `location_simulation` 与 `attribute_memory_analysis` 各一次；缺失或重复均作为无效响应进入既有错误边界。
- 修复保留字段定位：扫描合法 JSON 的根对象成员键，不再把字符串值中的同名文本误认为冲突键；覆盖 `{"note":"max_tokens","max_tokens":100}`。
- 补充成功保存表单到 `TaskSettingUpdate` 完整 payload 映射断言。
- RED：聚焦命令最终为 3 failed / 17 passed，分别证明缺失集合、重复集合和同名字符串值定位问题。
- GREEN：`npm --prefix frontend run test -- --run src/api/aiSettings.test.ts src/features/ai-settings/AiSettingsPage.test.tsx` 通过，2 个测试文件、20 tests passed。
- 分项：Biome 49 files、`tsc --noEmit`、Vite build 均通过；构建保留既有 >1500 kB chunk 警告。
- 全量：`./scripts/check.ps1` 沙箱外通过；后端 216 passed、6 deselected，前端 15 个测试文件、140 tests passed，Ruff format/check、Pyright、Biome、TypeScript 与 Vite build 均通过。

**第二次独立审查修复验证（2026-07-16）**

- 修复数组边界：根对象键扫描同时跟踪对象与数组深度；仅对象深度为 1 且数组深度为 0 时识别成员键和根成员分隔逗号。
- RED：聚焦命令为 1 failed / 19 passed，证明 `{"options":["other","max_tokens"],"max_tokens":100}` 把数组元素误定位为第 2 行第 24 列，而非真实根键第 3 行第 3 列。
- GREEN：`npm --prefix frontend run test -- --run src/api/aiSettings.test.ts src/features/ai-settings/AiSettingsPage.test.tsx` 通过，2 个测试文件、20 tests passed。
- 分项：Biome 49 files、`tsc --noEmit`、Vite build 均通过；构建保留既有 >1500 kB chunk 警告。
- 全量：`./scripts/check.ps1` 沙箱外通过；后端 216 passed、6 deselected，前端 15 个测试文件、140 tests passed，Ruff format/check、Pyright、Biome、TypeScript 与 Vite build 均通过。

---

## 任务 4：NPC 二次缓存、主角预留位与显式 offline

**Files**

- Modify: `backend/src/app/game/locations.py`
- Modify: `backend/src/app/game/__init__.py`
- Modify: `backend/src/app/world/service.py`
- Modify: `backend/tests/game/test_locations.py`
- Modify: `backend/tests/world/test_world_api.py`
- Modify if generated DTO changes: `backend/src/app/api/worlds.py`
- Modify related frontend tests only if response literal changes from `off_scene` to `offline`

**Pure-function contract**

- 使用唯一哨兵 `OFFLINE = "offline"`，API 和内存快照中绝不以 `None` 表示无地图。
- 先按规则解析每个启用 NPC 的主地点；无匹配规则的 NPC 直接 offline，不进入溢出缓存。
- 每张地图永远最多接收 5 名 NPC，无论主角当时是否在该地图，都为主角保留第 6 位。
- 主地点超出的 NPC 进入统一缓存；先按 role_id 排序，再使用 `sha256(f"{world_id}:{day}:{time_slot}:overflow")` 派生的随机种子打乱。
- 按 `LOCATION_IDS` 稳定顺序遍历，每张未满地图逐个补到 5，再进入下一张地图。全部满后剩余角色显式 offline。
- 主角移动不重新分配 NPC；只有成功轮次推进到下一时间段后才采用下一快照。

核心入口固定为：

```python
def allocate_role_presences(
    presences: Sequence[RolePresence],
    *,
    world_id: int,
    day: int,
    time_slot: str,
) -> tuple[RolePresence, ...]:
    """按主地点、二次缓存和永久主角预留位返回全部启用角色的非空位置事实。"""
```

**Steps**

- [x] 用表驱动测试覆盖：刚好 5 NPC、单地图 6+、多地图溢出补位、所有地图满、缓存剩余、无规则、空缓存、无 NPC、输入顺序变化、同种子复现、不同时间种子、主角移动不改变 NPC。
- [x] 先运行 `uv run pytest backend/tests/game/test_locations.py backend/tests/world/test_world_api.py -q`，确认旧 `enforce_location_capacity` 行为失败。
- [x] 实现纯函数并让 `WorldService.get_game_view` 和轮次快照共用它，禁止前端自行推断位置。
- [x] 运行聚焦测试与 `./scripts/check.ps1`，更新本文件并提交 `feat: redistribute overflow npcs deterministically`。

**Expected:** 所有启用角色都有字符串位置；每图 NPC≤5；离线角色后续不会创建地图链或触发空指针。

**验证记录（2026-07-16）**

- RED：`uv run pytest backend/tests/game/test_locations.py backend/tests/world/test_world_api.py -q` 为 14 failed / 22 passed；失败点为缺少 `OFFLINE` 与 `allocate_role_presences`，以及旧容量逻辑未把两个溢出 NPC 补入 `the_dungeon`。
- GREEN：同一聚焦命令最终为 36 passed；显式覆盖 role_id 排序、`sha256("7:1:morning:overflow")` 种子、`LOCATION_IDS` 补位顺序、每图最多 5 NPC、永久主角预留位、offline/禁用角色、输入顺序、返回顺序、跨时间种子与主角移动稳定性。
- 分项：Ruff format/check 通过；Pyright 为 0 errors / 0 warnings / 0 informations。
- 全量：`./scripts/check.ps1` 沙箱内因 uv 用户缓存无法初始化失败，沙箱外原命令重跑通过；后端 225 passed、6 deselected，前端 15 个测试文件、140 tests passed，OpenAPI 无漂移，Ruff/Pyright/Biome/TypeScript/Vite build 均通过；保留既有 >1500 kB chunk 警告。
- 边界：当前尚无轮次快照模块，未提前创建任务 5+ 实现；新纯函数已从 `app.game` 正确导出，供后续快照构建复用。

---

## 任务 5：结构化 AI Schema、状态快照与 ContextBuilder

**Files**

- Create: `backend/src/app/workflow/definitions.py`
- Create: `backend/src/app/workflow/schemas.py`
- Create: `backend/src/app/workflow/context.py`
- Create: `backend/src/app/story/store.py`
- Modify: `backend/src/app/attribute/models.py`
- Modify: `backend/src/app/attribute/resolver.py`
- Create: `backend/tests/workflow/test_schemas.py`
- Create: `backend/tests/workflow/test_context.py`
- Modify: `backend/tests/attribute/test_resolver.py`

**Stable task definitions**

`workflow/definitions.py` 只能暴露两个固定任务；不提供 CRUD、DAG、循环或脚本节点。

地点推演的系统约束必须明确：玩家输入只是主角准备尝试的行动，NPC 可拒绝、忽略或自行互动，主角没有成功或因果优先级；地图是直接互动范围；程序冻结的位置不可由 AI 改写，输出 Schema 不提供任何位置变更字段。每篇纪事只能写该角色亲历、感知、被告知或公开可知的内容，不能因为一次调用生成全地图纪事就互相泄露视角。

地点推演输出采用以下公共结构；`event_key` 是单轮内本地稳定字符串，最终结算映射为数据库整数 ID：

```python
class EventKnowledge(BaseModel):
    role_id: int = Field(gt=0)
    level: Literal["participant", "observer", "told", "public"]
    perspective_notes: str = ""


class ObjectiveEventOutput(BaseModel):
    event_key: str = Field(min_length=1, max_length=80)
    group_id: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=80)
    fact: dict[str, JsonValue]
    knowledge: list[EventKnowledge]


class RoleChronicleOutput(BaseModel):
    role_id: int = Field(gt=0)
    content: str = Field(min_length=1)
    known_event_keys: list[str]


class InteractionGroupOutput(BaseModel):
    group_id: str = Field(min_length=1, max_length=80)
    role_ids: list[int] = Field(min_length=1)


class LocationSimulationOutput(BaseModel):
    location_id: str
    groups: list[InteractionGroupOutput] = Field(min_length=1)
    events: list[ObjectiveEventOutput]
    chronicles: list[RoleChronicleOutput] = Field(min_length=1)
```

程序校验：本地图每名角色恰好属于一个组且恰好一篇纪事；无未知/重复/跨地图角色；事件 group 存在；事件 knowledge 和纪事 known events 一致。互动优先但不强迫，单人组合法；AI 可以把多人地图划成全体、部分、两两或独行组。只有一个角色的地图仍调用 AI，但 Prompt 明确只生成特别简短的一句话纪事，禁止为凑篇幅虚构无意义事件。

属性与记忆输出：

```python
class RoleAttributeMemoryOutput(BaseModel):
    role_id: int = Field(gt=0)
    attribute_update_intents: list[AttributeUpdateIntent]
    memory_append: str


class AttributeMemoryAnalysisOutput(BaseModel):
    location_id: str
    roles: list[RoleAttributeMemoryOutput] = Field(min_length=1)
```

每个已定位角色恰好返回一段 `memory_append`，包括独处角色；长度不超过冻结配置的 hard max，不得含 `__`。离线角色完全不进入该任务。`AttributeUpdateIntent.source_event_id` 改为 `str | None`；没有客观事件也允许 AI 按角色本轮内容与规则合理更新属性，程序不再要求来源事件非空，但非空时必须引用本地图事件。

`ContextBuilder` 必须在短 Session 中为每个角色读取：自身人设/提示词/世界书、最终属性、完整长期记忆、最近 5 个含 `turn_story` 的有效轮次、其亲历/感知/被告知事件和公开事实。长期摘要已经包含最近内容时仍同时发送最近 5 轮，这是有意加强近期印象；第一版不得去重、截断累计记忆、设置累计上限或发增长警告。不得读取其他角色纪事。地点上下文只含本地图角色；主角意图只注入主角地图。属性与记忆上下文只含本地图本轮结构、角色最终属性与对应更新规则。

**Steps**

- [x] 先写 Schema 的遗漏、重复、跨图、未知事件、无事件合法、单人组、多组和记忆分隔符测试。
- [x] 先写 ContextBuilder 的跨地图隔离、主角意图隔离、其他角色纪事不可见、公开事实可见、完整记忆、最近 5 个有效轮次、offline 不计数、独处计数测试。
- [x] 修改属性命令测试，允许 `source_event_id=None`，同时拒绝未知非空 event_key。
- [x] 运行聚焦测试确认失败后实现最小 Schema、校验器、Store 查询和 ContextBuilder。
- [x] 运行聚焦测试与 `./scripts/check.ps1`，更新本文件并提交 `feat: add isolated turn contexts and ai schemas`。

**Expected:** 玩家能看全部纪事，但任何角色的后续上下文都无法从查询层拿到其他角色纪事；最近 5 轮定义可由持久化事实精确判断。

---

## 任务 6：AI 节点调用、结构化输出与每节点重试

**Files**

- Create: `backend/src/app/workflow/ai_tasks.py`
- Create: `backend/src/app/workflow/retry.py`
- Modify: `backend/src/app/ai/openai_compatible.py`
- Modify: `backend/src/app/ai/deepseek.py`
- Modify: `backend/src/app/main.py`
- Create: `backend/tests/workflow/test_ai_tasks.py`
- Create: `backend/tests/workflow/test_retry.py`
- Modify: `backend/tests/ai/test_openai_compatible.py`
- Modify: `backend/tests/ai/test_deepseek.py`

**Attempt ownership**

每个工作流节点的“首次 + 自动重试 2 次”必须只有一个计数器。现有 Provider 内部重试不能与工作流重试叠加；重构后工作流任务调用使用单次 Provider transport attempt，`RetryPolicy(max_attempts=3)` 是节点重试唯一拥有者。连接测试保持单次、可操作失败。

```python
RETRYABLE_CATEGORIES = frozenset(
    {
        AiErrorCategory.RATE_LIMITED,
        AiErrorCategory.TIMEOUT,
        AiErrorCategory.NETWORK,
        AiErrorCategory.UNAVAILABLE,
        AiErrorCategory.INVALID_RESPONSE,
    }
)


@dataclass(frozen=True)
class AttemptResult[T]:
    value: T
    attempt: int
```

结构化输出无效包括 JSON 解析、Pydantic Schema、分组、角色覆盖、事件引用和记忆摘要校验失败，均可重试。用户取消、缺模型、Provider/API Key 配置错误、认证、权限和余额错误立即失败。每次重试沿用同一冻结输入和配置；属性节点失败不得重跑已成功的地点节点。

请求构建规则：

- `auto` 且能力支持 `json_output`，或显式 `native` 时使用 `ResponseFormat(type="json_object")`；
- `prompt` 或 auto fallback 在 system prompt 中附加同一 JSON Schema 约束；
- 自由 Provider JSON 在最终 payload 顶层原样合并，但此前已通过保留字段校验；
- Prompt 只含任务最小上下文，不含 API Key、其他地图或完整无关历史；
- 日志只记 task_key、模型 ID、尝试、耗时、结果类别和 token usage，不记完整 Prompt/响应/Key。

**Steps**

- [ ] 用 fake Provider/respx 写单次成功、第三次成功、三次耗尽、不可重试立即失败、Schema 无效重试、取消打断退避、配置冻结和 native/prompt 两路径同 Schema 测试。
- [ ] 写 Provider 回归证明一次节点最多产生三次实际 HTTP 请求，不是 3×内部重试。
- [ ] 运行聚焦测试确认失败后实现 `TaskInvoker`、`RetryPolicy` 和安全请求构建。
- [ ] 运行聚焦测试、Ruff、Pyright、`./scripts/check.ps1`；不在此任务运行付费 Playwright。
- [ ] 更新本文件并提交 `feat: add structured ai task invocation and retries`。

**Expected:** 尝试次数与真实 HTTP 次数一致；错误分类符合产品定义；成功节点可复用。

---

## 任务 7：进程内地图并行执行器与生命周期

**Files**

- Create: `backend/src/app/workflow/runtime.py`
- Create: `backend/src/app/workflow/executor.py`
- Create: `backend/src/app/workflow/manager.py`
- Modify: `backend/src/app/main.py`
- Create: `backend/tests/workflow/test_executor.py`
- Create: `backend/tests/workflow/test_manager.py`

**Runtime contract**

```python
class NodeKey(StrEnum):
    LOCATION_SIMULATION = "location_simulation"
    ATTRIBUTE_MEMORY_ANALYSIS = "attribute_memory_analysis"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

`TurnRun`、`MapChainRun`、冻结输入、节点输出、错误和取消事件只存在内存。Manager 全应用只允许一个活动 run。每张有角色地图创建一条 coroutine：地点成功后该地图立即执行属性与记忆节点，不等待其他地图；所有地图 coroutine 由一个 `asyncio.TaskGroup` 并行，Provider 调用共享 `asyncio.Semaphore`。离线角色无链路。

进度事件至少包含：`run_id`、`kind`、`location_id`、`node`、`attempt`、`max_attempts=3`、`retrying`、`completed_maps`、`total_maps`、`elapsed_ms`、安全错误。终态只发一次。

取消、失败或 TaskGroup 异常必须协作式取消未完成调用并丢弃全部输出。成功运行在交给结算服务后也立即从活动槽释放；为状态读取只允许短暂保留安全终态，不能持久化。

**Steps**

- [ ] 用可控 async fake 写地图内严格串联、地图间确实重叠、并发上限、地点失败不进第二节点、属性失败不重跑地点、成功节点内存复用、离线跳过、单活动 run 和取消测试。
- [ ] 写冻结设置测试：运行中保存新配置不改变该 run，新 run 读取新版本。
- [ ] 运行聚焦测试确认失败后实现 runtime/executor/manager；所有并发与时间测试使用 Event/虚拟时钟，不用真实 sleep。
- [ ] 在 `create_app` lifespan 创建并销毁唯一 Manager；应用退出取消活动运行。
- [ ] 运行聚焦测试与 `./scripts/check.ps1`，更新本文件并提交 `feat: run map chains in memory`。

**Expected:** 无 `turn_run` 数据写入；地图链按设计并行；任何失败都只留下安全内存终态。

---

## 任务 8：原子结算、属性与记忆写入、时间推进和历史查询

**Files**

- Create: `backend/src/app/game/time.py`
- Create: `backend/src/app/story/service.py`
- Modify: `backend/src/app/story/store.py`
- Modify: `backend/src/app/world/store.py`
- Modify: `backend/src/app/world/service.py`
- Modify: `backend/src/app/attribute/resolver.py`
- Create: `backend/tests/game/test_time.py`
- Create: `backend/tests/story/__init__.py`
- Create: `backend/tests/story/test_settlement.py`
- Create: `backend/tests/story/test_history.py`

**Atomic settlement order**

1. 开启一个短 Session/事务并重读 world、内部 branch、角色 state version。
2. 校验冻结 `state_version`、全部地图覆盖、故事、组、事件、知识边界、属性命令和记忆摘要。
3. 先在内存副本对每个角色调用唯一 `apply_attribute_updates`；任一失败不修改 ORM。
4. 插入 `turn`，再把 AI `event_key` 映射为数据库 `turn_event.id`。
5. 写已定位角色 `turn_story`、事件参与者和 `state_change`。
6. 更新 `world_role_state.change_values_json/version`。
7. 对每个已定位角色写记忆：空串时 `fragment`，否则 `old + "__" + fragment`；同时递增 memory version。
8. 写 `state_after_json`，更新 branch `head_turn_id`、day、time_slot、state_version 和时间戳；night 后 Day+1/morning。
9. commit。任何异常 rollback，且内存 run 变为失败。

`advance_time` 固定为纯函数：

```python
def advance_time(day: int, time_slot: TimeSlot) -> tuple[int, TimeSlot]:
    order: tuple[TimeSlot, ...] = ("morning", "midday", "evening", "night")
    index = order.index(time_slot)
    if index == len(order) - 1:
        return day + 1, "morning"
    return day, order[index + 1]
```

历史查询按 turn 倒序读取，但 API 返回按 UI 需要的稳定顺序。每轮角色列表必须覆盖提交时全部启用角色：主角第一，其余按稳定 role_id；已定位角色读取 AI 纪事，offline 根据 `turn_positions` 合成固定短句，不运行属性/记忆分析。客观事件和属性变化都与轮次一起返回。

**Steps**

- [ ] 先写四时间段/跨日表驱动测试、属性无变化仍追加合理摘要、首次/后续 `__` 追加、世界与角色隔离测试。
- [ ] 写事务故障注入：故事、事件、第二角色属性、第二角色记忆、branch version 冲突和 commit 前异常，逐一断言 turn/故事/事件/state_change/属性/记忆/时间全部未变。
- [ ] 写历史测试：主角第一、已定位全纪事、offline 固定说明、旧轮次完整、最近 5 有效轮次只取 `turn_story`。
- [ ] 运行聚焦测试确认失败后实现时间函数、Store 和 SettlementService。
- [ ] 运行聚焦测试与 `./scripts/check.ps1`，更新本文件并提交 `feat: settle turns atomically`。

**Expected:** 只有完整成功产生一个 turn；属性表与记忆表来自同一 AI 响应并在同一事务生效；失败时间不动。

---

## 任务 9：轮次 API、NDJSON 与断线取消

**Files**

- Create: `backend/src/app/api/turns.py`
- Modify: `backend/src/app/api/worlds.py`
- Modify: `backend/src/app/main.py`
- Create: `backend/tests/test_turn_api.py`
- Create: `backend/tests/test_turn_stream.py`

**API contract**

- `POST /api/worlds/{world_id}/turn-runs`：只接受 `{ "player_intent": string }`，校验当前无活动轮次、世界存在、意图非空、两任务可运行；冻结快照并返回 202 与临时 `run_id`。
- `GET /api/turn-runs/{run_id}`：返回当前安全内存状态；进程重启后 404，不查数据库。
- `GET /api/turn-runs/{run_id}/stream`：`application/x-ndjson`，每行一个完整事件；首次连接领取 run 并启动/订阅执行；连接断开调用 cancel 并等待清理。
- `POST /api/turn-runs/{run_id}/cancel`：幂等取消，返回当前状态。
- `GET /api/worlds/{world_id}/turns`：返回全部成功轮次；不提供独立历史、分页、分支或快照 API。

POST 后若 stream 在 10 秒内未领取，Manager 自动取消 pending run，避免页面错误造成全局活动槽永久占用。该等待只属于进程内生命周期，不持久化且不改变 AI 节点超时。

NDJSON 终态：`run_succeeded` 带新 turn DTO；`run_failed` 带可操作安全错误；`run_cancelled` 不带故事。断线、刷新、应用退出均不得提交。

**Steps**

- [ ] 先写创建/重复创建、未配置、错误世界、空意图、状态、单次 stream 领取、分块事件、幂等取消、未领取超时、断线取消、重启式 404 和历史 API 测试。
- [ ] 通过受控 fake executor 证明 stream 断开后 DB 无 turn/属性/记忆/时间变化。
- [ ] 实现薄 Router；业务状态归 Manager/SettlementService，Router 只做 DTO/HTTP/StreamingResponse 转换。
- [ ] 运行 `./scripts/generate-api.ps1`，再运行后端聚焦测试和 `./scripts/check.ps1`。
- [ ] 更新本文件并提交 `feat: expose in-memory turn run api`。

**Expected:** 页面生命周期与 run 生命周期绑定；终态不重复；重启只看到上次成功轮次。

---

## 任务 10：前端轮次 API、NDJSON 解析与运行状态

**Files**

- Create: `frontend/src/api/turns.ts`
- Create: `frontend/src/api/turns.test.ts`
- Create: `frontend/src/features/game/turnRunReducer.ts`
- Create: `frontend/src/features/game/turnRunReducer.test.ts`
- Create: `frontend/src/app/TurnRunContext.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify generated: `frontend/src/api/generated.ts` through script

**Client contract**

`streamTurnRun` 使用原生 Fetch/ReadableStream/TextDecoder，必须处理：任意 chunk 边界、一行跨多个 chunk、一个 chunk 多行、空行、最后换行、无最后换行、无效 JSON、HTTP 错误、AbortSignal、重复终态和断线。每个完整 JSON 行先经过运行时 type guard，再交 reducer；禁止 `any` 和无检查断言。

```ts
export interface TurnRunClient {
  create(worldId: number, playerIntent: string): Promise<TurnRunCreated>;
  stream(
    runId: string,
    signal: AbortSignal,
    onEvent: (event: TurnRunEvent) => void,
  ): Promise<void>;
  cancel(runId: string): Promise<TurnRunStatus>;
  listTurns(worldId: number, signal?: AbortSignal): Promise<TurnResponse[]>;
}
```

Reducer 维护唯一活动 run、地图节点进度、elapsed、终态和原始意图。终态后清空活动锁；失败/取消保留意图；成功用服务端 turn 更新历史，不能由前端推断时间、位置或属性。

`TurnRunContext` 只承担明确的跨 App 导航锁与卸载取消，不成为第二业务事实来源。活动期间禁用设置/角色/世界导航；页面离开或刷新触发 Abort，后端断线取消。

**Steps**

- [ ] 先写 NDJSON 所有分块边界、错误和终态去重测试，以及 reducer 成功/失败/取消/重试状态测试。
- [ ] 先写 App 导航锁和卸载 Abort 测试，确认新模块缺失而失败。
- [ ] 实现客户端、type guards、reducer 和最小 Context；不引入状态库。
- [ ] 运行聚焦 Vitest、Biome、TypeScript、Vite build 和 `./scripts/check.ps1`。
- [ ] 更新本文件并提交 `feat: add turn streaming client state`。

**Expected:** 网络流再碎也只产生完整事件；前端不伪造世界事实；断线能闭合取消。

---

## 任务 11：游戏主界面意图、进度、结果与历轮卡片

**Files**

- Modify: `frontend/src/features/game/GamePage.tsx`
- Modify: `frontend/src/features/game/GamePage.module.css`
- Modify: `frontend/src/features/game/GamePage.test.tsx`
- Create: `frontend/src/features/game/TurnProgress.tsx`
- Create: `frontend/src/features/game/TurnProgress.test.tsx`
- Create: `frontend/src/features/game/TurnHistory.tsx`
- Create: `frontend/src/features/game/TurnHistory.test.tsx`
- Modify: `frontend/src/game/GameBridge.ts`
- Modify: `frontend/src/game/GameBridge.test.ts`

**User flow**

1. 玩家进入地点；地图移动不改变时间。
2. 输入自由意图。UI 文案明确它是“主角准备尝试什么”，不是命令世界结果。
3. 即使意图目标不在本地图也允许提交；最终故事可找不到、失败或准备，但不能跨地图直接互动；整轮成功时仍正常消耗一轮。
4. 运行时锁定移动、重复提交、世界/角色/AI 配置导航；允许取消。
5. 按地图显示节点、`尝试 n/3`、自动重试、完成地图数/总地图数和总耗时。
6. 成功：刷新服务端 game view，清空意图，把新轮次卡片插入并滚动到结果；最新展开，所有旧轮次折叠。
7. 失败/取消：不新增卡片，不改时间/位置/属性，保留原意图；显示可操作错误和“再次提交”。

轮次卡片展开顺序固定：主角独立纪事、其他角色独立纪事、客观事件、属性变化。所有启用角色都有纪事项；offline 显示程序固定短说明。主角只是第一项，没有因果优先级。

**Steps**

- [ ] 先写允许缺席目标意图、提交锁、取消、失败保留、成功清空/滚动、最新展开/旧轮折叠、全部角色列表、offline 说明和无多余历史控制测试。
- [ ] 写 GameBridge 回归：活动轮次期间键盘/鼠标移动被拒绝，结束后恢复；监听器始终清理。
- [ ] 运行聚焦测试确认失败后实现组件和 CSS Modules；提供 loading/empty/error/disabled/retry 状态。
- [ ] 运行前端聚焦检查和 `./scripts/check.ps1`，更新本文件并提交 `feat: complete playable turn interface`。

**Expected:** 用户在一个游戏主界面完成移动、意图、等待、阅读和下一轮；没有独立历史页、分支或快照控制。

---

## 任务 12：确定性的完整纵向集成回归

**Files**

- Create: `backend/tests/workflow/test_turn_integration.py`
- Create: `backend/tests/workflow/test_turn_failures.py`
- Modify: `backend/tests/world/test_world_api.py`
- Modify: `frontend/src/features/game/GamePage.test.tsx`
- Modify: `scripts/check.ps1` only if new ordinary test locations are not already discovered

此任务允许 fake Provider/respx 做确定性的单元与集成测试；用户禁止的是用 mock AI 替代真实 AI Playwright，不是禁止底层自动回归。

**Required cases**

- 两张以上有角色地图并行；主角意图只出现在主角地图。
- NPC–NPC 可互动且不围绕主角；每角色只属于一组；跨地图角色/事件被拒绝。
- 多人地图、单人地图和 offline 同轮共存；offline 没有 AI 调用、属性分析或记忆追加。
- 每个地图只调用一次地点推演；属性 Schema 第一次无效、第二次成功时只重试属性节点。
- 可重试三次与不可重试一次；取消、stream 断开、配置变化、世界 state_version 冲突。
- 所有已定位角色运行属性分析，即使无客观事件；合理无变化和合理变化都能结算。
- 记忆首次写入、第二轮 `__` 追加；总文本无上限、每轮 fragment 受冻结 hard max。
- 成功后时间、下一位置、历史卡片 DTO 正确；失败时所有相关表与时间完全不变。
- 世界创建前后 role 行数量、ID、persona、prompt、world_book、属性定义和 version 不变；只允许引用关系变化。

**Steps**

- [ ] 先实现上述集成测试夹具和断言，并确认至少一个完整闭环测试在执行器/结算/API尚未接好时失败。
- [ ] 只修复集成暴露出的最低公共层问题，不在测试里放宽不变量或吞错。
- [ ] 运行 `uv run pytest backend/tests/workflow backend/tests/story backend/tests/world/test_world_api.py -q`。
- [ ] 运行 `npm --prefix frontend run test -- --run` 和 `./scripts/check.ps1`。
- [ ] 更新验证记录并提交 `test: cover merged turn loop integration`。

**Expected:** 默认检查完全离线、快速、可复现，并能证明并发、隔离、重试和原子性；它不能替代任务 13。

---

## 任务 13：真实 AI Playwright 完整可玩验收

**Files**

- Create: `frontend/playwright.live.config.ts`
- Create: `frontend/e2e/phase45-real-ai.spec.ts`
- Modify: `frontend/package.json`
- Modify: `scripts/prepare-e2e-content.ps1`
- Create: `scripts/run-live-e2e.ps1`
- Create: `scripts/verify_live_e2e_state.py`
- Modify: `frontend/e2e/phase3-world-map.spec.ts` only to share safe helpers without weakening assertions

**Hard rule:** 本任务的轮次推演必须调用用户提供的真实 Provider 与真实模型。不得加入默认离线 AI、mock Provider、路由拦截伪造 AI 结果或以任务 12 替代。该付费测试不进入 `scripts/check.ps1`。

`playwright.live.config.ts` 必须在启动浏览器前检查专用环境变量，缺失时明确失败为“真实 AI 浏览器验收未验证”，而不是 skip 后宣称通过。变量固定为 `CLEAR_SKY_LIVE_PROVIDER_TYPE`、`CLEAR_SKY_LIVE_BASE_URL`、`CLEAR_SKY_LIVE_API_KEY`、`CLEAR_SKY_LIVE_MODEL`；Key 只经环境传入网页密码框。live 配置关闭 trace/video，并确保日志、截图标题、HTML 报告和断言文本都不出现 Key。

运行命令固定为：

```powershell
npm --prefix frontend run test:e2e:live
```

该 npm script 调用 `scripts/run-live-e2e.ps1`：先运行 live Playwright，成功后再运行只读数据库验证脚本；任何一步失败都返回非零。live profile 使用独立 `config_test/live-e2e-localappdata`，不得读取或清理正式 LocalAppData。

**Browser journey**

- [ ] 从隔离空库打开网页，复制测试专用 `天.jpg`、`莫莉莉.png`、`安可儿.png`，不创建产品种子角色。
- [ ] 通过网页新增真实 Provider、API Key、模型，并配置两个全局任务及 Provider JSON。
- [ ] 通过网页创建三名角色、属性和更新规则；记录角色列表。
- [ ] 以已有角色 ID 创建世界；再次取角色列表，断言数量和 ID 完全不变，角色主数据除 `referenced_world_ids` 外完全不变；任何 4xx/5xx、唯一键错误或 console error 立即失败。
- [ ] 加入 NPC、为 morning 与 midday 都配置位置规则，验证真实立绘与同/跨地图分布，并确保需要检查记忆追加的角色连续两轮都已定位。
- [ ] 移动主角并断言时间不变。
- [ ] 提交第一轮真实意图，观察每地图节点、尝试次数、完成数和耗时；验证所有启用角色纪事、同地图互动、跨地图不互动、NPC 自由互动、客观事件和时间推进。
- [ ] 提交第二轮真实意图；验证最新轮次展开、旧轮折叠、属性变化显示和下一时段位置。
- [ ] 浏览器流程结束后运行 `scripts/verify_live_e2e_state.py` 只读取隔离 SQLite，断言两个 turn、无运行表、每个已定位角色 memory 存在且第二轮形成 `__` 追加；脚本只输出计数/布尔结果，不输出 Prompt、Key、完整故事或记忆。

测试 AI 有权合理判断不互动或不更新属性，因此断言应验证结构与客观边界，不能强迫具体剧情或具体数值变化。为稳定验证属性变化，可以在角色规则和玩家意图中创建明确、合理的客观条件，但结果仍由真实 AI 推演。

若真实流程自然遇到异常，记录安全类别与复现步骤到本文件“自然异常回归”，先修复并添加最低层回归，再重新运行相同真实流程；不为凑异常覆盖人为破坏 Provider。

**Expected:** Playwright exit 0；真实 API usage 可记录 provider、模型、测试结果和 token usage 总量，但不记录密钥和完整内容。

---

## 任务 14：异常闭环专项 code review

**Files to review**

- `backend/src/app/ai/errors.py`
- `backend/src/app/workflow/retry.py`
- `backend/src/app/workflow/ai_tasks.py`
- `backend/src/app/workflow/executor.py`
- `backend/src/app/workflow/manager.py`
- `backend/src/app/story/service.py`
- `backend/src/app/api/turns.py`
- `frontend/src/api/turns.ts`
- `frontend/src/features/game/turnRunReducer.ts`
- `frontend/src/features/game/GamePage.tsx`

**Review checklist**

- [ ] 错误分类：超时、临时网络、429、5xx、无效结构可重试；取消、缺模型/Provider/Key、配置、认证、权限、余额不可重试。
- [ ] 次数：节点最多三次真实 HTTP 请求，无 Provider 内部嵌套重试；属性失败不重跑地点。
- [ ] 取消：用户取消、stream 断开、页面刷新、App shutdown 都能传到 HTTPX 并释放活动槽。
- [ ] 临时状态：无运行表、无中间结果写库、终态只短暂存在内存、重启无需恢复。
- [ ] 原子性：所有验证先于 ORM 修改；事务内任意失败会 rollback 故事、事件、属性、记忆、branch head 和时间。
- [ ] 脱敏：安全错误、日志、NDJSON、trace 和测试产物不含 API Key、Authorization、完整 Prompt 或敏感响应。
- [ ] 前端：失败不插卡、不更新时间，意图保留；重复终态/断线不会二次结算或出现幽灵 loading。

审查必须引用实际代码与测试证据，并把结论直接写入下方“异常专项审查记录”；不得新建 review 文档。发现问题先补失败测试并修复，再重新审查。异常不一定能在真实 AI Playwright 中遇到，因此不要求人为制造异常端到端场景。

完成后运行相关聚焦测试和 `./scripts/check.ps1`，更新本文件并提交 `review: close turn failure paths`；若审查无代码变更，则只提交本文件的审查证据。

---

## 任务 15：全量门禁、onedir 与干净 Windows 11 验收

**Files**

- Modify as required by real failures: `scripts/build.ps1`, PyInstaller spec, packaging tests
- Modify: `plan.md`

**Commands from repository root**

```powershell
./scripts/generate-api.ps1 -Check
./scripts/check.ps1
uv run pytest -m live_ai -q
npm --prefix frontend run test:e2e:live
./scripts/build.ps1
```

然后在干净 Windows 11 x64、未预装 Python/Node 的环境中运行 onedir 程序并完成最小真实浏览器冒烟：启动、自动打开浏览器、健康接口、已有成功轮次读取、创建或打开测试世界、真实 AI 提交一轮、正常关闭。记录实际 Python/SQLite/Node 构建版本、应用版本、Provider/模型、检查结果和安全 token usage 摘要。

**Final acceptance**

- [ ] `需求与产品设计.md` 第 16 节 38 项逐条对应到自动测试、真实 AI Playwright 或干净机证据，没有未解释缺口。
- [ ] `git diff --check` 通过，`git status --short` 只含有意变更；无 Key、真实故事、完整 Prompt、测试数据库、Playwright trace/report 或 LocalAppData 被提交。
- [ ] 未实现分支/快照、独立历史页、长期记忆压缩、任意工作流、模型 fallback 或 mock AI 轮次 Playwright。
- [ ] 所有普通检查、真实 AI、真实 Playwright、onedir 与干净 Win11 门禁通过。
- [ ] 更新本文件当前状态为“合并阶段 4+5 已验收”，填写最终验证和决策记录，提交 `release: verify playable turn loop`。

若缺真实凭据，必须保留任务 13/15 未勾选并写“真实 AI 浏览器验收未验证”；若缺干净机，必须保留最终门禁未勾选。两者都不能由 mock、开发机或“预计通过”替代。

---

## 4. 验证记录

| 日期 | 任务 | 命令/证据 | 结果 |
|---|---|---|---|
| 2026-07-12 | 阶段 2 | `pytest -m live_ai`、离线全量检查 | DeepSeek 普通、流式、thinking、JSON、Tool Calls 与离线回归通过；密钥未入库外边界 |
| 2026-07-15 | 阶段 3 | `scripts/check.ps1`、`frontend/e2e/phase3-world-map.spec.ts`、用户确认 | 角色、世界、属性、地图、位置规则、三张真实立绘和浏览器流程完成；世界创建唯一键 bug 已修复 |
| 2026-07-16 | 合并设计 | 核心文档契约扫描、`git diff --check`、用户逐项确认 | 阶段 4+5 合并设计已写入 `需求与产品设计.md`、`技术选型文档.md`，提交 `ba0a44c` |
| 2026-07-16 | 任务 1 | RED：迁移聚焦测试 `7 failed, 1 passed`，Model 后端 `2 failed`，前端边界 `1 failed`；GREEN：`uv run pytest backend/tests/test_phase45_migrations.py -q`、`scripts/check.ps1`、独立代码审查 | 迁移聚焦 `7 passed`；完整检查后端 `177 passed, 6 deselected`、前端 `127 passed`，Ruff/Pyright/Biome/TypeScript/Vite build 全部通过；SQLite `3.53.1`；审查无 Critical/Important/Minor；未改 Provider 传输，未重复付费真实 AI 测试 |
| 2026-07-16 | 任务 2 | RED：聚焦 pytest 因缺少 `app.workflow.settings` 收集失败；删除受引用模型暴露 `IntegrityError`；PUT 缺必填可空字段错误返回 200；独立审查证明密钥拼写绕过、快照可变及任务设置提交异常链可携带敏感参数；GREEN：聚焦 pytest、`scripts/generate-api.ps1`、`scripts/check.ps1`、独立与正式代码审查 | 聚焦 `46 passed`；完整检查后端 `216 passed, 6 deselected`、前端 `127 passed`，Ruff/Pyright/Biome/TypeScript/Vite build 全部通过；审查 3 个有效 Important 已修复，PUT version 意见按既定服务端版本契约不采纳；仅已有 Vite 大包警告；未改 Provider 传输，未重复付费真实 AI 测试 |
| 2026-07-16 | 任务 4 | RED：聚焦 `14 failed, 22 passed`；GREEN：聚焦、Ruff、Pyright、`scripts/check.ps1`、旧哨兵/入口搜索与 diff 审计 | 聚焦 `36 passed`；完整检查后端 `225 passed, 6 deselected`、前端 `140 passed`，所有静态检查和构建通过；仅既有 Vite 大包警告；轮次快照尚不存在，未提前实现任务 5+ |
| 2026-07-17 | 任务 5 | RED：聚焦 pytest 因缺少 `app.workflow.schemas`、`app.workflow.context` 且事件来源仍要求整数而收集失败；补充快照 RED `2 failed, 3 passed`；GREEN：聚焦 pytest、Ruff、Pyright、`scripts/check.ps1`、diff 自审 | 聚焦 `54 passed`；完整检查后端 `245 passed, 6 deselected`、前端 `140 passed`，Ruff/Pyright/Biome/TypeScript/OpenAPI 漂移检查/Vite build 全部通过；仅既有 Vite 大包警告；未改 Provider 传输，未运行付费真实 AI 测试；正式独立审查由控制器执行 |

后续每个任务在完成提交前追加一行，至少记录日期、精确命令、pass/fail、测试数量或关键证据、未验证项。

## 5. 异常专项审查记录

任务 14 完成前保持为空。只在这里记录实际审查范围、发现、修复提交、复验命令和最终结论。

## 6. 自然异常回归

当前无。真实 AI Playwright 若自然触发 Provider、结构化输出、网络或取消异常，在这里记录脱敏复现条件、最低层测试、修复提交和真实复验结果；不得记录 Key、完整 Prompt 或完整响应。

## 7. 阻塞项

- 干净 Windows 11 x64 最终发布门禁需要可用的隔离机器或虚拟机；在实际完成前不得勾选任务 15。
- 真实 AI Playwright 需要用户提供可用 Provider、API Key 和两个任务所选模型；无凭据时必须明确未验证。

## 8. 决策记录

| 日期 | 决策 | 实施影响 |
|---|---|---|
| 2026-07-16 | 阶段 4 与阶段 5 合并 | 先交付完整可玩单线闭环，再考虑后续高级功能 |
| 2026-07-16 | 地图是直接互动边界 | 每地图独立推演，主角意图只进入主角地图，禁止跨图直接互动 |
| 2026-07-16 | 玩家意图永远是主角尝试 | AI 可推演失败、拒绝和合理后果，主角无世界因果优先级 |
| 2026-07-16 | 每图一条两节点链 | 地点推演一次返回全图角色纪事；成功后同图一次分析全部角色属性与记忆 |
| 2026-07-16 | 未完成运行只在内存 | 失败、取消、断线、刷新和重启不入库、不推进时间、不恢复运行 |
| 2026-07-16 | 长期记忆只追加 | 每世界+角色唯一 TEXT，以 `__` 分隔；默认目标 20、硬上限 50，无累计上限 |
| 2026-07-16 | 第一版不开放分支、快照或独立历史页 | 保留内部初始 branch，只在游戏主界面展示可折叠轮次卡片 |
| 2026-07-16 | 轮次 Playwright 只用真实 AI | 不建设 mock/offline AI 轮次 Playwright；底层 fake/respx 回归仍必须完整 |
| 2026-07-16 | 异常闭环以专项 code review 为必需门禁 | 不人为制造真实 Provider 异常；自然异常转为永久回归 |
| 2026-07-16 | `ai_model.defaults_json` 的数据库、Service、API、生成类型和现有前端入口在任务 1 原子移除 | 避免迁移完成后出现 ORM/API 仍读写已删除列的断裂状态；任务 2、3 只保留回归并实现任务设置能力 |
