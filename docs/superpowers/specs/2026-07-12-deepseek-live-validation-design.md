# DeepSeek 真实配置与阶段 2 验收设计

## 目标与范围

本轮完成阶段 2 的 DeepSeek 真实配置和付费集成验证，然后停止开发，不进入阶段 3。

- 在本机正式 SQLite 数据库中保存一个启用的 DeepSeek 官方 Provider。
- 在该 Provider 下配置并启用 `deepseek-v4-flash` 与 `deepseek-v4-pro`。
- `deepseek-v4-flash` 验证普通响应、流式响应、thinking、JSON Output 和 Tool Calls。
- `deepseek-v4-pro` 只验证一次普通非流式调用能否联通。
- 完成阶段 2 的离线与真实验证，并明确报告任何因远端能力或环境导致的未验证项。

本轮不实现世界、角色、地图或阶段 3 的任何能力。

## 配置与密钥边界

复用现有 `AiSettingsService`、Store、ORM 模型和 Alembic 迁移，把 Provider、模型和 API Key 写入 `%LOCALAPPDATA%\ClearSkyEngine\data\app.db`。不新增环境文件、凭据文件或第二套配置来源。

真实测试从本机正式数据库读取已启用的 DeepSeek Provider 和目标模型。API Key 只以 `SecretStr` 进入 Provider 调用边界，不进入 API 查询响应、测试参数 ID、日志、异常、Prompt、响应台账、快照或仓库文件。测试失败只报告模型、能力和脱敏后的统一错误语义。

数据库写入必须可重复执行：同名 Provider 或同一远端模型已存在时更新到目标配置，不创建重复记录，也不删除用户的其他 Provider 或模型。

## 测试结构与数据流

真实测试夹具按以下顺序工作：

1. 定位本机正式数据库并确认迁移版本已到 `head`。
2. 通过现有 Service 读取启用的 DeepSeek Provider 连接信息。
3. 按远端模型名读取已启用模型，缺失配置时以“真实 AI 集成未验证”明确失败或跳过。
4. 为单个测试建立短生命周期 `httpx.AsyncClient`，调用现有无业务状态 `DeepSeekProvider`。
5. 只输出 provider、model、capability、result 和 token usage 的安全台账。

普通与流式测试继续验证统一 DTO 语义。thinking 必须同时得到 reasoning 与最终文本；JSON Output 必须能解析为 JSON 对象；Tool Calls 必须返回指定函数调用。联通测试只要求 `deepseek-v4-pro` 返回非空普通文本。

## 错误处理

- 数据库不存在、迁移未完成、Provider 未启用、Key 缺失或目标模型未启用时，不尝试远端调用，并明确指出缺失配置。
- 认证、余额、限流、网络和远端服务错误沿用现有脱敏 `AiProviderError` 分类。
- 不因真实测试失败自动切换模型，也不实现模型 fallback。
- 临时网络错误只沿用 Provider 已有的有限重试规则；产生有效输出后不重试。

## 验证与完成标准

按风险从小到大执行：

1. 聚焦离线 Provider、DeepSeek、设置 Service/API 与迁移测试。
2. Ruff format/check、Pyright 和完整 `scripts\check.ps1`。
3. 使用数据库凭据运行 `pytest -m live_ai -q -s`，确认 Flash 五项与 Pro 一项的安全台账。
4. 检查实际 SQLite 版本、数据库中两个模型的启用状态，以及 API 查询不会返回完整 Key。
5. 检查 `git diff` 与 `git diff --check`，确认没有密钥或无关改动进入提交。

只有离线检查和上述六个真实用例均得到实际结果，阶段 2 才可报告为完整验证。若远端模型不支持指定能力或服务不可用，保留证据并将对应项报告为未验证，不用推测代替结果。阶段 2 验收报告完成后停止，不开始阶段 3。
