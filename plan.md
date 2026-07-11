# Clear Sky Engine 开发计划与进度

> 本文件是跨会话开发进度的唯一事实来源。开始工作前先读取“当前状态”和当前阶段；只有实际验证通过后才能勾选步骤。

## 当前状态

- 当前阶段：阶段 2——AI Provider 管理与接入
- 当前任务：2.2 统一 DTO、Provider 协议与注册表
- 最近完成：Provider/Model 全局迁移、CRUD、级联关系、密钥不回传和底层 SQL 参数脱敏均已通过完整检查
- 下一步：先为统一请求/响应、错误语义和无状态 `ProviderRegistry` 写失败测试，再实现最小公共协议
- 阻塞项：阶段 1 的干净 Windows 11 x64 验收需要外部环境，继续作为发布门禁，不阻塞阶段 2 开发；真实 AI 验证会产生费用，安排在 Provider 实现完成后执行

## 执行规则

- 每项功能遵循“失败测试 → 确认预期失败 → 最小实现 → 聚焦验证 → 完整验证”。文档、配置和纯生成产物可不使用 TDD，但仍必须验证。
- 只有验证命令真实通过后，才能把 `- [ ]` 改为 `- [x]`；不得以“预计通过”代替证据。
- 每个独立任务通过后，将代码、测试和本文件的进度更新放入同一任务级提交。
- 保留已完成阶段和验证记录；阶段完成时展开下一阶段，并更新本节的当前任务与下一步。
- 锁文件、OpenAPI 类型、Alembic 迁移和前端静态产物必须由工具生成，不得手工编辑。
- 当前工作树中的 `README.md` 删除和无关未跟踪文件属于用户改动，不得恢复、覆盖或误提交。

## 全局约束

- 产品与验收依据：`需求与产品设计.md`。
- 架构、数据模型、API 与分期依据：`技术选型文档.md`。
- 常驻编码约束：`AGENTS.md`。
- Windows 11 x64；Python 3.14.6 + uv；SQLite 使用 Python 3.14.6 自带版本；Node 24.18.0；React 19.2；Phaser 4.2；PyInstaller onedir。
- 生产环境仅有一个 Python 进程、一个 SQLite 数据库、一个绑定 `127.0.0.1` 的 FastAPI 服务和一个系统浏览器页面。
- 不新增核心文档禁止的框架、服务、脚本执行能力或第二事实来源。

## 五阶段路线图

- [ ] 阶段 1：工程与本地运行——工具链、项目骨架、数据库、前端空壳、本地安全启动器、检查和打包。
- [ ] 阶段 2：AI Provider——Provider/Model 管理、OpenAI-compatible、DeepSeek、流式协议、脱敏及真实 API 验证。
- [ ] 阶段 3：世界、角色与地图——世界/分支、角色、属性、位置、时间、地图与不依赖 AI 的完整配置体验。
- [ ] 阶段 4：轮次纵向切片——三阶段流水线、上下文隔离、状态命令、进度、取消/重试/恢复和原子提交。
- [ ] 阶段 5：历史、快照与发布验收——时间线、快照、分支、Playwright、onedir 和 29 项产品验收。

## 阶段 1——工程与本地运行

### 任务 1.1：计划与文档基线

**文件：** `plan.md`、`技术选型文档.md`、`AGENTS.md`

- [x] 创建本进度文件，写入五阶段路线图、阶段 1 任务、验证台账和决策记录。
- [x] 将 SQLite 基线改为 Python 3.14.6 自带版本，删除 3.53.3 硬要求，保留运行时版本记录与检查。
- [x] 检查文档占位符、SQLite 旧契约、Markdown 差异和空白错误。

**验证：**

```powershell
rg -n "T(BD)|TO(DO)" plan.md AGENTS.md 技术选型文档.md
rg -n "SQLite 3\.53\.3|必须验证为 SQLite 3\.53\.3" AGENTS.md 技术选型文档.md
git diff --check -- plan.md AGENTS.md 技术选型文档.md
```

### 任务 1.2：精确开发工具链与锁定依赖

**文件：** `.python-version`、`pyproject.toml`、`uv.lock`、`frontend/package.json`、`frontend/package-lock.json`、`scripts/setup.ps1`

- [x] 使用 `uv` 安装并固定 Python 3.14.6，记录其自带 `sqlite3.sqlite_version`。
- [x] 下载官方 Node 24.18.0 win-x64 便携版到 `%LOCALAPPDATA%\ClearSkyEngineDev\toolchains\`，通过 `CLEAR_SKY_NODE_HOME` 使用，不覆盖现有 Node 22。
- [x] 创建后端与前端清单，固定直接依赖、Node engines 和 npm packageManager。
- [x] 由工具生成并提交 `uv.lock` 与 `package-lock.json`。
- [x] 实现 `scripts/setup.ps1` 的版本检查和 locked 安装。
- [x] 运行 setup 并确认 Python、Node、npm、SQLite 和锁文件安装均成功。

**验证：**

```powershell
.\scripts\setup.ps1
uv run python -c "import sqlite3, sys; print(sys.version); print(sqlite3.sqlite_version)"
npm --prefix frontend exec -- node --version
```

### 任务 1.3：后端、配置与数据库基础

**文件范围：** `backend/src/app/`、`backend/tests/`、`backend/migrations/`、`alembic.ini`

- [x] 先写配置、目录解析、SQLite PRAGMA、Session、空迁移和健康检查的失败测试并确认预期失败。
- [x] 实现 FastAPI 应用生命周期、共享 HTTPX AsyncClient、LocalAppData 目录和同步 SQLAlchemy Session。
- [x] 实现每连接 `foreign_keys=ON`、`journal_mode=WAL`、`synchronous=FULL`、`busy_timeout=5000`。
- [x] 实现 Alembic 接入、迁移前备份入口和空库升级。
- [x] 实现 `GET /api/health`，返回应用、数据库和实际 SQLite 运行时状态。
- [x] 运行聚焦测试、Ruff 与 Pyright。

**验证：**

```powershell
uv run pytest backend/tests -q
uv run ruff format --check backend
uv run ruff check backend
uv run pyright backend/src backend/tests
uv run pytest backend/tests/test_migrations.py -q
```

### 任务 1.4：前端、OpenAPI 与 Phaser 空壳

**文件范围：** `frontend/src/`、`frontend/index.html`、`frontend/vite.config.ts`

- [x] 先写 API 状态、应用壳和 `GameBridge` 生命周期的失败测试并确认预期失败。
- [x] 实现 React Router 应用壳、CSS Modules、原生 Fetch 健康检查以及 loading/error/backend-unavailable 状态。
- [x] 实现 Phaser 4.2 最小场景和可清理的类型化 `GameBridge`。
- [x] 从后端 OpenAPI 生成前端 DTO，禁止手工修改生成文件。
- [x] 运行 Vitest、Biome、TypeScript 和 Vite build。

**验证：**

```powershell
.\scripts\generate-api.ps1
npm --prefix frontend run check
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

### 任务 1.5：本地安全启动器与生产静态站点

**文件范围：** `backend/src/app/main.py`、`backend/src/app/launcher.py`、`backend/tests/`

- [x] 先写 loopback Host、同源 Origin、shutdown 令牌、随机端口、静态站点和浏览器启动的失败测试并确认预期失败。
- [x] 实现只绑定 `127.0.0.1` 的随机端口启动器和系统默认浏览器打开逻辑。
- [x] 实现生产 Host/Origin 校验和 `POST /api/app/shutdown` 启动期随机令牌。
- [x] 提供前端静态构建与 SPA fallback；生产环境不启用宽松 CORS。
- [x] 运行后端安全测试和本地启动冒烟测试。

**验证：**

```powershell
uv run pytest backend/tests -q
# 另执行隔离临时目录中的真实 Uvicorn loopback TCP 首页请求与协作式关闭冒烟
```

### 任务 1.6：统一检查与 PyInstaller onedir

**文件范围：** `scripts/generate-api.ps1`、`scripts/dev.ps1`、`scripts/check.ps1`、`scripts/build.ps1`、PyInstaller spec 与打包测试

- [x] 实现所有根脚本，任一步失败时返回非零。
- [x] 实现 OpenAPI 漂移检查和前端构建产物复制，禁止手工编辑生成物。
- [x] 实现 PyInstaller onedir 构建并包含迁移、静态站点和运行资源。
- [x] 从临时空数据库升级到 `head` 并运行应用冒烟测试。
- [x] 运行完整检查与构建，记录实际输出。
- [ ] 在干净 Windows 11 x64 环境执行最终阶段 1 冒烟；若当前环境无法提供干净机，保持该项未勾选并记录阻塞。

**验证：**

```powershell
.\scripts\check.ps1
.\scripts\build.ps1
```

## 阶段 1 验收

- [x] 空数据库可执行全部迁移到 `head`。
- [x] 一个 Python 进程可在 loopback 提供 React/Phaser 页面并打开系统默认浏览器。
- [x] `scripts/check.ps1` 完整通过。
- [x] PyInstaller onedir 构建成功并完成可用环境内的启动冒烟。
- [ ] 干净 Windows 11 x64 冒烟有证据，或明确记录为外部环境阻塞。

## 当前阶段：阶段 2——AI Provider 管理与接入

阶段 2 先建立可实际连接 AI 的全局基础，但不提前引入世界、角色或轮次表。Provider 与 Model 全局共享；世界级任务选模在后续世界/轮次阶段接入。

### 任务 2.1：Provider/Model 全局持久化与密钥边界

**文件范围：** `backend/src/app/ai/`、`backend/src/app/api/`、`backend/src/app/db/`、`backend/migrations/`、`backend/tests/`

- [x] 先写 Provider/Model 数据约束、CRUD、级联关系和 API Key 不回传的失败测试，并确认预期失败。
- [x] 使用 Alembic 建立 `ai_provider` 与 `ai_model` 全局表；API Key 可替换或清空，但查询 DTO 只返回 `has_api_key`。
- [x] 实现薄 `/api/providers`、`/api/models` 路由以及对应 Service/Store，不把 ORM 模型作为公开 DTO。
- [x] 验证空库到 `head`、升级路径、外键约束、事务回滚和查询/日志脱敏。
- [x] 重新生成 OpenAPI 类型并确认无手工漂移。

### 任务 2.2：统一 DTO、Provider 协议与注册表

**文件范围：** `backend/src/app/ai/`、`backend/tests/ai/`

- [ ] 先写统一请求/响应、错误语义和无状态注册表的失败测试。
- [ ] 定义普通与流式路径共用的消息、文本、reasoning、Tool Calls、finish reason、usage 和受控 `provider_options` DTO。
- [ ] 实现稳定 Provider 协议与无业务状态 `ProviderRegistry`；所有实现复用应用级 `httpx.AsyncClient`。
- [ ] 建立统一错误分类和脱敏边界，确保完整 Key、敏感请求和响应不进入异常或日志。

### 任务 2.3：OpenAI-compatible 普通与流式接入

**文件范围：** `backend/src/app/ai/openai_compatible.py`、`backend/src/app/ai/streaming.py`、`backend/tests/ai/`

- [ ] 使用 respx 先覆盖普通响应、SSE 分块/空行、Tool Calls、JSON Output、usage、取消和错误映射的失败测试。
- [ ] 实现 `OpenAICompatibleProvider` 普通调用与流式解析，并保持两条路径的公共语义一致。
- [ ] 仅在尚未产生有效输出时对临时网络错误有限重试；重试感知取消，不引入额外重试依赖。

### 任务 2.4：DeepSeek 专有适配

**文件范围：** `backend/src/app/ai/deepseek.py`、`backend/tests/ai/`

- [ ] 先写 DeepSeek `reasoning_content`、thinking、SSE keep-alive、JSON Output、Tool Calls、finish reason 和官方错误响应的失败测试。
- [ ] 复用 OpenAI-compatible 协议实现 `DeepSeekProvider`，只覆盖 DeepSeek 专有差异。
- [ ] 提供 `deepseek-v4-pro` 与 `deepseek-v4-flash` 官方预设，不把旧模型别名设为默认值。

### 任务 2.5：管理界面与连接测试

**文件范围：** `frontend/src/features/`、`frontend/src/api/`、`backend/src/app/api/`、前后端测试

- [ ] 先写 Provider/Model 列表、编辑、密钥遮蔽、loading/empty/error/retry 和连接测试状态的失败测试。
- [ ] 实现全局 Provider/Model 管理页面与原生 Fetch 调用，DTO 仅来自生成的 OpenAPI 类型。
- [ ] 实现连接测试 API；结果只返回能力与脱敏诊断，不记录完整 Prompt、Key 或敏感响应。

### 任务 2.6：离线回归、真实 API 与阶段验收

- [ ] 运行完整 respx 回归、`scripts\generate-api.ps1` 和 `scripts\check.ps1`。
- [ ] 使用用户提供的凭据运行普通、流式及模型支持能力的 `pytest -m live_ai -q`，记录 provider、模型、结果和 token usage。
- [ ] 无凭据时明确记录“真实 AI 集成未验证”，保持真实 API 验收未勾选，不以 mock 代替。
- [ ] 真实与离线验证均通过后完成阶段 2，并展开阶段 3 的世界、角色与地图细化清单。

### 阶段 2 验收

- [ ] 用户可以管理 OpenAI-compatible 与 DeepSeek Provider、模型和连接配置，查询响应与日志不泄露 API Key。
- [ ] 普通与流式调用的文本、reasoning、Tool Calls、JSON Output、finish reason、usage 和错误语义一致。
- [ ] respx 离线回归完整通过。
- [ ] 真实 API 普通、流式及模型支持能力验证完成；无凭据时明确保留为未验证。

**阶段 2 验证命令：**

```powershell
uv run pytest backend/tests/ai backend/tests/test_provider_api.py backend/tests/test_provider_migrations.py -q
uv run ruff format --check backend
uv run ruff check backend
uv run pyright backend/src backend/tests
.\scripts\generate-api.ps1 -Check
npm --prefix frontend run test -- --run
.\scripts\check.ps1

# 使用用户提供的凭据和真实模型，会产生 API 费用
uv run pytest -m live_ai -q
```

## 验证记录

| 日期 | 任务 | 命令 | 结果 |
|---|---|---|---|
| 2026-07-11 | 1.1 | `rg` 占位符/旧 SQLite 契约检查；`git diff --cached --check` | 未发现占位符或旧硬版本契约；暂存差异无空白错误 |
| 2026-07-11 | 1.2 | `.\scripts\setup.ps1` | Python 3.14.6、SQLite 3.53.1、Node 24.18.0、npm 11.16.0；`uv sync --locked` 与 `npm ci` 成功，npm 审计 0 漏洞 |
| 2026-07-11 | 1.3 | `uv run pytest backend/tests -q`；Ruff format/check；Pyright | 10 个测试通过；Ruff 全部通过；Pyright 0 错误、0 警告 |
| 2026-07-11 | 1.4 | `generate-api.ps1 -Check`；健康 API 测试；Ruff/Pyright；Biome/TypeScript/Vitest/Vite | OpenAPI 无漂移；后端 2 个聚焦测试与前端 7 个测试通过；静态检查 0 错误/警告；Vite 构建成功 |
| 2026-07-11 | 1.5 | 后端全量测试/Ruff/Pyright；OpenAPI 与前端回归；真实 Uvicorn loopback TCP 冒烟 | 后端 18 个、前端 7 个测试通过；静态检查与构建通过；随机 loopback 首页返回 200 并正常关闭 |
| 2026-07-11 | 1.6 | `scripts\check.ps1`；`scripts\dev.ps1 -SmokeTest`；`scripts\build.ps1`；`dist\ClearSkyEngine\ClearSkyEngine.exe --smoke-test` | OpenAPI 无漂移；Ruff/Pyright/Biome/TypeScript 通过；后端 21 个、前端 7 个测试通过；Vite 与 onedir 构建成功；开发环境和打包程序均在 loopback 返回健康接口与首页 200，SQLite 3.53.1，并正常关闭。PyInstaller 警告仅涉及平台或未启用的可选模块 |
| 2026-07-11 | 阶段 1 本机浏览器验收 | 启动 `dist\ClearSkyEngine\ClearSkyEngine.exe` 并采集真实请求日志 | 单一打包进程持续运行；默认浏览器请求首页、CSS、React/Phaser 脚本、健康接口和 favicon，全部返回 200。首次端口探测因系统连接过滤产生假阴性，应用日志与进程证据确认启动正常 |
| 2026-07-11 | 阶段顺序调整 | 旧阶段引用与占位符 `rg` 检查；`git diff --check -- plan.md 技术选型文档.md AGENTS.md` | 阶段 2/3 旧顺序引用和占位符均未发现；三份文档差异无空白错误；产品范围与验收文档无需修改 |
| 2026-07-11 | 2.1 | Provider/Model 聚焦 pytest；`generate-api.ps1 -Check`；`scripts\check.ps1` | 迁移、CRUD、级联、回滚、异常链和 SQL 参数脱敏均通过；OpenAPI 无漂移；Ruff/Pyright/Biome/TypeScript 通过；后端 29 个、前端 7 个测试通过；Vite 构建成功 |

## 决策记录

| 日期 | 决策 | 影响 |
|---|---|---|
| 2026-07-11 | 使用分层滚动计划，任务级验证后勾选并提交 | `plan.md` 保留完整路线图，只展开当前阶段 |
| 2026-07-11 | 第一版 AI 流水线使用三阶段聚合 | 阶段 4 固定主推演、角色/属性并行、最终汇总和程序裁决 |
| 2026-07-11 | SQLite 跟随项目锁定的 Python 3.14.6 运行时自带版本 | 不再硬要求 3.53.3；当前 uv 运行时实测为 3.53.1，启动、检查和打包继续记录实际版本 |
| 2026-07-11 | Node 24.18.0 使用官方便携版 | 不覆盖本机现有 Node 22，通过 `CLEAR_SKY_NODE_HOME` 使用 |
| 2026-07-11 | 将 AI Provider 调整为阶段 2，世界、角色与地图顺延为阶段 3 | 先交付可管理、可测试且可真实连接的 AI 基础；Provider 保持全局，不依赖世界模型，轮次仍在两者完成后实现 |

## 已完成阶段

尚无。
