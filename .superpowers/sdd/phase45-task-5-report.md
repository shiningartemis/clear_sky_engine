# 合并阶段 4+5 任务 5 实施报告

日期：2026-07-17
基线提交：`565ccae0015f918eceb28105157276ab5ad2468c`
提交主题：`feat: add isolated turn contexts and ai schemas`

## 实现结果

- 新增两个固定任务的严格 Pydantic 输出 Schema，以及基于程序冻结地点、角色集合、事件集合和记忆 hard max 的校验函数。
- 地点推演校验覆盖地点一致、互动组 ID 唯一、角色完整且唯一、纪事完整且唯一、事件 key 唯一、事件组存在、知识角色不跨图、纪事事件引用存在，以及事件 knowledge 与纪事 known events 双向一致。
- 属性与记忆校验覆盖地图角色完整且唯一、每个意图角色一致、记忆非空、不得含 `__`、不得超过冻结 hard max，以及非空来源必须引用本地图事件。
- `AttributeUpdateIntent.source_event_id` 改为受长度约束的 `str | None`；通用属性函数允许无事件来源，仍拒绝未知非空 `event_key`。
- 新增两个不可配置结构的固定任务定义。地点系统约束明确玩家意图只是尝试、NPC 可拒绝或自主互动、主角无成功或因果优先级、地图是直接互动边界、AI 不得改变程序位置、角色纪事不得跨视角泄漏，并明确独处角色只生成一句极短纪事。
- 新增 `StoryStore.list_recent_role_turns`。SQL 查询从入口即按 `world_id + branch_id + role_id` 过滤目标角色自己的 `turn_story`；有效轮次由 `turn_story` 是否存在精确定义，倒序取最近 5 条后按自然时间顺序返回。事件查询只读取该角色自己的 `turn_event_participant` 行。
- 新增 `ContextBuilder`。一次短 Session 内读取角色人设、提示词、世界书、最终属性、对应更新规则、完整长期记忆和最近 5 个有效轮次；关闭 Session 后只返回不可变 dataclass、tuple、深冻结事件 JSON 和只读 Mapping。
- 冻结快照保存 `world_id`、`branch_id`、day/time、`world_state_version`、主角 ID、全部角色非空位置和每个有角色地图的上下文；校验提交时间与持久化分支一致。主角意图仅进入主角地图；offline 角色不创建地图链。
- 属性与记忆节点上下文只从当前地图冻结上下文和当前地图已校验地点输出构建；每个角色只获得自己的纪事、可知事件、最终属性、更新规则和属性版本，不携带长期记忆或其他地图内容。

## 变更文件

生产代码：

- `backend/src/app/workflow/definitions.py`
- `backend/src/app/workflow/schemas.py`
- `backend/src/app/workflow/context.py`
- `backend/src/app/story/store.py`
- `backend/src/app/attribute/models.py`
- `backend/src/app/attribute/resolver.py`

测试与记录：

- `backend/tests/workflow/test_schemas.py`
- `backend/tests/workflow/test_context.py`
- `backend/tests/attribute/test_resolver.py`
- `plan.md`
- `.superpowers/sdd/phase45-task-5-report.md`

未新增依赖、迁移、API、生成类型、前端代码、工作流 CRUD、DAG、循环、脚本节点或兼容层。

## TDD 证据

### 初始 RED

命令：

```powershell
uv run pytest backend/tests/workflow/test_schemas.py backend/tests/workflow/test_context.py backend/tests/attribute/test_resolver.py -q
```

首次沙箱内执行因现有 uv 缓存路径初始化错误退出，随后按权限规则在沙箱外运行同一命令。有效 RED 输出：

```text
ERROR backend/tests/workflow/test_schemas.py
ModuleNotFoundError: No module named 'app.workflow.schemas'
ERROR backend/tests/workflow/test_context.py
ModuleNotFoundError: No module named 'app.workflow.context'
ERROR backend/tests/attribute/test_resolver.py
ValidationError: source_event_id Input should be a valid integer
3 errors in 0.97s
```

失败原因与待实现功能精确一致：两个新模块尚不存在，属性来源仍只接受数据库整数事件 ID。

### 初始 GREEN

同一命令输出：

```text
53 passed in 1.27s
```

### 补充状态快照 RED → GREEN

自审发现初始快照未冻结分支 `state_version`，也未拒绝调用方传入与持久化分支不同的 day/time。先增加测试，再运行：

```powershell
uv run pytest backend/tests/workflow/test_context.py -q
```

RED：

```text
2 failed, 3 passed in 1.35s
AttributeError: 'TurnContextSnapshot' object has no attribute 'world_state_version'
Failed: DID NOT RAISE ContextBuildError
```

加入最小版本冻结和时间一致性校验后，重跑全部任务 5 聚焦测试：

```text
54 passed in 1.70s
```

## 静态检查与完整检查

聚焦 Ruff/Pyright：

```powershell
uv run ruff format --check <任务 5 文件>
uv run ruff check <任务 5 文件>
uv run pyright <任务 5 文件>
```

最终输出：

```text
9 files already formatted
All checks passed!
0 errors, 0 warnings, 0 informations
```

完整检查第一次运行准确发现 `test_context.py` 新增导入的排序问题并以非零退出；使用项目 Ruff 机械修复后重新运行完整命令：

```powershell
./scripts/check.ps1
```

最终完整输出摘要（exit code 0，已读取完整输出）：

```text
97 files already formatted
All checks passed!
0 errors, 0 warnings, 0 informations
245 passed, 6 deselected in 19.60s
Checked 49 files in 71ms. No fixes applied.
Test Files 15 passed (15)
Tests 140 passed (140)
vite build: 46 modules transformed, built in 761ms
```

Vite 仍报告既有的单个构建 chunk 大于 1500 kB 警告；本任务没有前端变更，也未扩大范围处理该既有警告。

## 自审

- 信息隔离：历史 Store 的首个查询已经限定目标 `role_id`，返回结构不提供其他角色纪事；事件查询也限定相同角色参与者行。玩家可查看的全局纪事不会从该 Store 进入普通角色上下文。
- 地图隔离：ContextBuilder 只为调用方提供的程序冻结非 offline 位置分组，并在每地图上下文内保存本地图角色；主角意图只赋给主角冻结地点。
- 有效轮次：查询以内连接 `turn_story` 定义有效轮次，因此程序合成的 offline 说明没有行且不计数；独处角色仍有 AI `turn_story`，自然计数。
- 记忆：完整 `WorldRoleMemory.memory` 原样冻结；未去重、未截断、未设置累计上限或增长警告。第二节点不重复注入长期记忆。
- 状态事实：快照记录分支版本并拒绝 day/time 不一致；AI 输出无任何位置变更字段。
- 原子性边界：本任务只构建内存输出与状态命令，没有写轮次、记忆或属性；最终原子结算仍留在任务 8。
- 类型与依赖：没有使用 `Any`/`any`、无检查断言或新依赖；关键边界有中文注释/文档字符串。
- 范围：未创建运行持久化表、分支/快照 UI、工作流 CRUD、任意 DAG、长期记忆压缩或 Provider fallback。

## 顾虑与未验证项

- 本任务没有改动 Provider 传输或真实 AI 调用路径，未运行会产生费用的 `pytest -m live_ai`；真实 AI 结构化输出调用、重试和 prompt/native 路径属于任务 6，当前不能宣称真实 AI 集成已验证。
- 本任务没有前端或浏览器流程变更，未运行 Playwright；完整轮次真实 AI Playwright 仍属于后续任务 13。
- 尝试的内部只读审查代理未在时限内返回具体结论且已中止；已完成任务范围内逐文件自审，正式独立审查由控制器继续执行。
- 干净 Windows 11 x64 冒烟仍是最终发布门禁，与本任务无关且未验证。
