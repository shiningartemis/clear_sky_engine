# Clear Sky Engine：AI 编码规范

本文件适用于整个仓库。它只规定 AI 编码时必须常驻的执行约束；完整产品定义见 `需求与产品设计.md`，完整架构与技术决策见 `技术选型文档.md`。

## 1. 指令与阅读顺序

优先级：用户当前明确要求 > 两份核心文档 > 本文件 > 现有代码与其他文档。

- 用户要求与核心文档冲突时，指出冲突并确认是否同步修改核心文档，不得静默偏离。
- 本文件不能替代核心文档。产品范围、验收标准查 `需求与产品设计.md`；技术理由、数据模型、API 和实施分期查 `技术选型文档.md`。
- 后续开发计划、任务拆分、实施进度、验证记录和决策记录统一维护在仓库根目录的 `plan.md` 中，并以其作为开发计划与进度的唯一基准；不得另建平行的计划或记录文档。此前已分散在其他文档中的历史内容无需追溯迁移，除非用户明确要求。
- 只读取当前任务相关章节和代码，不为“全面了解”扫描全仓库。
- `AGENTS-*.md` 是外部项目参考，不是本项目规范；仅在维护本文件时读取。
- 未确定的长期契约不得自行发明；会改变产品或架构方向时先请求确认。
- 更深目录仅在确有独立规则时增加 `AGENTS.md`，且不得削弱根规则。

## 2. 当前状态与工作原则

项目已完成阶段 1 的开发机工程和阶段 2 的 AI Provider 管理与接入；干净 Windows 11 x64 冒烟仍是发布门禁。当前优先实施阶段 3 的世界、角色、动态属性与地图。目录或能力尚未实际创建前不得声称可用。

- 遵循奥卡姆剃刀：做完整交付所需的最小实现；无真实用途不新增依赖、层、接口、服务或兼容代码。
- 只修改任务所需文件，保留用户已有和无关改动，不顺手重构或批量格式化。
- 先找现有实现和测试；不得并行建立第二套模型、客户端、状态机、校验器或事实来源。
- 新依赖必须证明现有标准库和已选依赖无法清晰完成任务，并取得用户同意。
- 修复放在拥有该不变量的最低公共层，并增加能复现问题的回归测试。

技术基线：Windows 11 x64；Python 3.14.6 + uv；SQLite 使用项目锁定的 Python 3.14.6 运行时自带版本；React 19.2 + TypeScript + Vite；Phaser 4；npm/Node 24；PyInstaller onedir。提交 `.python-version`、`uv.lock`、`package-lock.json`，安装使用锁文件；启动、检查和打包必须记录实际 `sqlite3.sqlite_version`。

## 3. 不可违反的架构边界

- 采用模块化单体。生产环境只有一个 Python 进程、一个 SQLite 数据库、一个绑定 `127.0.0.1` 的 FastAPI 服务和一个系统浏览器页面；Node.js 仅用于开发与构建。
- 生产环境校验 loopback Host 和同源 Origin，不启用宽松 CORS；shutdown 使用启动期随机令牌，不为本地单用户应用引入账号或 JWT。
- 程序是时间、位置、客观事件和状态的唯一裁决者；AI 只提交故事、事件和结构化状态变更意图。
- 只有同地点角色才能直接互动。地图移动、地点选择、进入或返回地图不推进时间；只有成功提交的 `turn` 推进时间。
- 阶段 3 每个世界恰有一个不可删除的主角；所有启用 NPC 每轮参与推演，包括离屏 NPC。阶段 5 开放分支前必须另行迁移分支状态，不能让可切换分支共享角色变化值。
- 角色上下文必须按其亲历、感知、被告知和公开事实隔离；全局角色纪事不得进入普通角色记忆。
- 失败、取消或中断不得生成 `turn`、部分更新世界或推进时间；最终结算必须原子提交。
- Provider、模型、应用设置和角色主表全局共享；世界角色引用、变化值、位置规则、故事、时间、分支和工作流选择按世界隔离。
- 每个启用的工作流任务必须人工选择模型；不做自动选模或模型 fallback。
- API Key 可按产品决策明文存于本地 SQLite，但完整 Key 不得进入查询响应、日志、异常、Prompt、故事、普通导出或测试快照。

除非用户明确修改核心文档，禁止引入：

- 向量数据库、Embedding、语义检索、RAG；
- Redis、Celery、外部队列、微服务、Kubernetes、PostgreSQL；
- LangChain、LangGraph、CrewAI、AutoGen、完整工作流引擎；
- 任意用户 Python/JavaScript/Shell、任意 SQL 或动态代码执行；
- Electron、Tauri、PySide6、pywebview；
- 云端账号、登录、OAuth、JWT、多用户权限、局域网或公网服务；
- Redux、Zustand、Axios、Tailwind、ESLint、Prettier 或大型 UI 库。

## 4. 目标目录与代码归属

按需创建，不预建空层：

```text
.python-version
pyproject.toml
uv.lock
backend/
  src/app/
    main.py
    launcher.py
    config.py
    api/
    ai/
    workflow/
    world/
    character/
    attribute/
    story/
    game/
    db/
    resources/
    static/
  tests/
  migrations/
frontend/
  package.json
  package-lock.json
  src/
    app/
    api/
    features/
    game/
    components/
  e2e/
scripts/
```

- `api/` 只做输入解析、Service 调用和 HTTP 转换；业务规则进入对应能力目录。
- `ai/` 放公共 AI 模型、Provider、注册表和错误转换；`workflow/` 放任务定义、执行器、上下文和运行状态。
- `world/`、`character/`、`attribute/`、`story/`、`game/` 分别拥有各自业务事实，禁止跨模块复制规则。
- `db/` 放 ORM、Session、Store 和迁移接入；迁移只放 `backend/migrations/`。
- `frontend/src/features/` 按页面能力组织；`components/` 仅放确实跨 feature 复用的无业务展示组件。
- `frontend/src/game/` 只放 Phaser 场景、输入和 `GameBridge`；`api/` 放 Fetch、NDJSON 和 OpenAPI 生成类型。
- `backend/src/app/static/` 是前端构建产物，生成后复制，不手工编辑。
- 不创建 `domain/application/infrastructure/adapter` 四层目录，不创建含糊的 `utils.py`、`helpers.py`、`common.py` 业务垃圾箱。
- 单实现 Service/Store 不抽接口；Store 直接使用 SQLAlchemy `Session`。仅多实现的 Provider 和 Skill 定义稳定协议；依赖用普通构造函数传入。

## 5. 后端与数据规则

- FastAPI 路由保持薄；Pydantic 2 用于 API DTO、AI 输入输出、配置和状态命令，ORM 模型不得直接作为公开 DTO。
- 在边界校验输入；已知结构不得用 `dict[str, Any]` 代替 Schema。业务错误只在 API 层转成 HTTP 响应。
- 使用 SQLAlchemy 2.0 同步 `Session` 和短事务；AI、流式或其他慢 I/O 期间绝不持有数据库连接或事务。
- SQLite 每连接启用 `foreign_keys=ON`、`journal_mode=WAL`、`synchronous=FULL`、`busy_timeout=5000`。
- 所有 Schema 变化使用 Alembic，并验证空库到 `head`；升级前备份。禁止手改生产库或只改 ORM。
- 数据写入 `%LOCALAPPDATA%\ClearSkyEngine\`；测试使用隔离临时库；图片、音频、地图和精灵不存 BLOB。
- 外键和查询必须携带拥有该状态的 `world_id`、`branch_id`；阶段 3 的世界角色变化表明确只用 `world_id`，其他分支拥有的数据不得省略 `branch_id`。
- 时间推进、星期推导、位置规则和属性命令优先写成无 I/O 纯函数并做表驱动测试。
- 角色使用全局角色主表与世界角色变化表；角色主表决定平铺属性 key、类型和基础值，世界变化表以 `(world_id, role_id)` 唯一。最终值只遍历主表 key，缺少变化时用基础值，遗留变化 key 或类型不匹配值静默忽略。
- `base_values_json` 的 key 集合是角色属性定义的事实来源；类型、显示名、含义、更新规则和允许操作必须与其 key 集合完全一致，可选约束和示例只能引用这些 key。
- 世界角色页只读展示最终属性。基础值、约束和更新规则只能在角色库编辑；世界变化值只能由成功轮次的受控更新意图和通用属性函数写入，禁止用户直接编辑或为动态属性生成脚本。
- 稳定 ID、持久化 JSON、流事件和用户存档一经发布即为兼容边界；变化必须提供迁移或向后读取测试。首次发布前不保留无用兼容层。

## 6. AI Provider 与流水线

- 第一版只实现 `OpenAICompatibleProvider`、复用兼容协议的 `DeepSeekProvider` 和无业务状态的 `ProviderRegistry`。
- 所有 Provider 共用应用级 `httpx.AsyncClient`；不得每请求创建客户端。
- 公共 DTO 只放跨 Provider 语义；厂商字段进入受控 `provider_options`。普通与流式路径的文本、reasoning、tool calls、finish reason、usage 和错误语义必须一致。
- DeepSeek 专有行为、SSE keep-alive/空行和错误转换按核心文档实现；错误与异常链必须脱敏。
- 临时网络错误只在尚未产生有效输出时有限重试；重试必须感知取消、输出和任务状态，不引入 Tenacity。
- 离线回归使用 respx；Provider、流式协议或 AI 关键链路变更还必须用用户提供的真实 API 运行 `pytest -m live_ai`，mock 不能替代。
- 真实测试覆盖普通、流式及模型支持的 reasoning/thinking、JSON Output、Tool Calls；记录 provider、模型、结果和 token usage，不记录密钥、完整 Prompt 或敏感响应。
- 真实测试产生费用，不默认进入 CI 或 `scripts\check.ps1`。无凭据时报告“真实 AI 集成未验证”，不得宣称完整验证。

流水线只支持阶段顺序执行、阶段内并行：

- 第一版任务定义在 `workflow/definitions.py`，不创建工作流 CRUD、任意 DAG、循环或条件脚本。
- 使用 `asyncio.TaskGroup` 组织并行、共享 `asyncio.Semaphore` 限流、协作式取消；第一版全应用最多一个活动 `turn_run`。
- 创建运行时冻结输入快照并结束事务；任务只读取自己的最小上下文，状态与中间结果可恢复。
- 重试沿用原快照，仅在输入哈希一致时复用成功结果；启动时把遗留运行标为 `interrupted`。
- 最终短事务校验快照版本、故事结构、信息边界和状态命令后，才写不可变 `turn` 并推进时间。
- AI 上下文统一由 `ContextBuilder` 过滤。Skill 是受控业务能力，不得绕过状态命令层或执行任意 SQL、Shell、文件写删和动态代码。
- 动态属性分析只接收目标角色本轮相关事件、当前最终属性和对应规则；Skill 只提交结构化更新意图，不直接写库。任一意图无效不得部分更新，最终由单一通用函数在结算事务中应用。

## 7. 前端与 Phaser

- 状态优先使用组件 state，其次 `useReducer`，最后少量 Context；无明确跨页面需求不加全局状态。
- 使用原生 Fetch；后端 OpenAPI 是 DTO 唯一来源，生成类型不得手改。进度流固定为 `application/x-ndjson`、每行一个完整 JSON 事件；解析必须处理分块、空行、取消、断线和重复终态。
- React 负责页面、表单、故事、时间线、轮次进度和覆盖层；Phaser 只负责场景、精灵、输入、Camera、碰撞、锚点和地图呈现。
- React 与 Phaser 只通过类型化 `GameBridge` 通信；监听必须清理，不引入事件总线库。
- 前端不得推断 NPC 位置、可见性、时间或世界裁决；这些事实来自后端。
- 地图目录以单一 `map_manifest.json` 为事实来源，不在多处硬编码。稳定 scene/location/asset ID 及资源替换规则见核心文档。
- 首次启动只复制缺失的默认地图到 LocalAppData，绝不覆盖用户已有的同名资源。
- 地图 manifest 只保存中文文件主体，不保存扩展名；地图按 `.jpg`、`.png` 查找，同名冲突时优先 `.jpg`。地图像素可变但必须保持横向 16:9，锚点和碰撞配置使用归一化坐标，不绑定绝对像素。
- 角色资源位于 `content/characters/{角色名称}/`，默认立绘主体必须等于角色名称；其他文件主体是未来差分或 CG 描述。同名资源按 `.jpg`、`.jpeg`、`.png`、`.gif`、`.webp`、`.avif`、`.bmp` 的稳定顺序取第一张，禁止 SVG。此命名和优先级是长期资源契约。
- 角色立绘使用 1:1 相框和 contain 自适应，不裁切、不拉伸；场景 CG 预留全屏 contain 展示模式。每地点最多 6 个角色，主角优先，其余 NPC 按稳定角色 ID 取前 5 个，溢出角色进入离屏状态。
- CSS 使用 CSS Modules；用户可见交互必须有明确的 loading、empty、error、disabled 和 retry 状态。

## 8. 代码与注释

- 新功能和 bug 修复默认先写失败测试，再做最小实现；文档和纯生成产物可例外。
- Python 使用现代类型标注，TypeScript 保持严格模式；不得用 `Any`、`any`、无检查断言或吞错绕过类型系统。
- 关键业务逻辑和关键代码逻辑必须有简洁、准确的中文注释或中文文档字符串，至少覆盖业务不变量、非显然算法、状态机、并发/取消、事务、信息隔离、安全和协议兼容。
- 人工编写的源码注释统一使用中文；标识符使用英文，必要的 API、协议和厂商术语可保留原文。生成代码、第三方代码和许可证原文除外。
- 注释解释“为什么、约束和失败后果”，不逐行翻译代码。修改逻辑时同步更新，删除失效注释和注释掉的旧实现。
- 不手改锁文件、OpenAPI 生成类型、前端构建产物或已发布 Alembic 迁移；使用对应工具生成。

## 9. 开发命令契约

首次脚手架必须建立以下根入口：

| 命令 | 职责 |
|---|---|
| `scripts\setup.ps1` | 校验版本，执行 `uv sync --locked` 和 `npm ci --prefix frontend` |
| `scripts\dev.ps1` | 启动 FastAPI 与 Vite 开发环境 |
| `scripts\generate-api.ps1` | 生成前端 OpenAPI 类型并检查漂移 |
| `scripts\check.ps1` | 后端/前端完整静态检查、类型检查、单测和前端构建 |
| `scripts\build.ps1` | 生成 Windows PyInstaller onedir 包 |

脚本存在后，所有命令从仓库根目录运行并优先使用脚本：

```powershell
.\scripts\setup.ps1
.\scripts\dev.ps1
.\scripts\generate-api.ps1
.\scripts\check.ps1
.\scripts\build.ps1
```

`check.ps1` 至少运行 Ruff format/check、Pyright、pytest、Biome、`tsc --noEmit`、Vitest 和 Vite build，任一步失败即返回非零。`frontend/package.json` 提供 `check`、`typecheck`、`test`、`build`、`test:e2e`；不叠加 ESLint/Prettier。

聚焦检查：

```powershell
uv run pytest backend/tests/path/to/test_file.py -q
npm --prefix frontend run test -- --run src/path/to/file.test.ts
npm --prefix frontend run test:e2e -- e2e/path.spec.ts

# 使用用户提供的凭据和真实模型，会产生 API 费用
uv run pytest -m live_ai -q
```

## 10. 最低验证要求

| 变更 | 必须验证 |
|---|---|
| 仅文档/规范 | 事实、链接、命令、占位符、`git diff --check` |
| Python 逻辑 | 聚焦 pytest、Ruff、Pyright；完成前 `scripts\check.ps1` |
| API DTO/路由 | 后端 API 测试、`scripts\generate-api.ps1`、相关前端测试 |
| ORM/迁移 | 空库到 `head`、升级路径、约束和事务测试 |
| Provider/流式 | respx 回归 + 真实 API `pytest -m live_ai` |
| 流水线/轮次 | 顺序、并行上限、取消、重试、复用、恢复、原子提交 |
| React/Phaser | 相关 Vitest/RTL；关键键鼠和用户流程运行 Playwright |
| 启动/打包 | `scripts\build.ps1` 和干净 Windows 11 x64 冒烟测试 |

真实 AI 与离线测试缺一不可。并发、时间、随机位置和重试测试必须可重复，不依赖真实等待或无种子随机数。

阶段 3 的真实 Playwright 必须通过网页完成角色创建、属性与规则配置、世界创建、NPC 引入和真实立绘展示；`resource` 中的 `天.jpg`、`莫莉莉.png`、`安可儿.png` 只作为隔离测试素材，不得创建产品种子数据。完整轮次接通后还必须通过网页真实调用用户提供的 AI，验证故事到属性更新的闭环；该付费测试不进入默认检查。

## 11. 完成任务前

确认后再报告完成：

1. 未扩大核心文档定义的范围，代码位于正确职责模块。
2. 未新增未经批准的依赖、框架、抽象层或第二事实来源。
3. 世界、分支、时间、位置、信息隔离、原子提交和密钥边界仍成立。
4. Schema、API、生成类型、迁移、测试和中文注释已同步。
5. 已运行与改动匹配的最新检查并阅读完整结果；真实 AI 未验证时明确说明。
6. `git diff` 只含任务所需改动，没有覆盖用户文件或生成无关噪声。
7. 最终回复说明改动、实际验证结果及任何未验证项。

不得用“预计通过”代替实际验证结果。
