# DeepSeek Live Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the supplied DeepSeek connection in the local application database, validate Flash's complete capability matrix and Pro connectivity, and close phase 2 without starting phase 3.

**Architecture:** Add a live-test-only configuration loader that reuses `AppConfig`, the SQLite session factory, and `AiSettingsService`; production API and secret boundaries remain unchanged. Live tests resolve enabled models by exact remote model ID, call the existing stateless `DeepSeekProvider`, and emit only a safe capability/token ledger.

**Tech Stack:** Python 3.14.6, Pydantic 2, SQLAlchemy 2.0 synchronous sessions, SQLite, HTTPX, pytest/pytest-asyncio, Ruff, Pyright, PowerShell.

## Global Constraints

- Store the API Key only in `%LOCALAPPDATA%\ClearSkyEngine\data\app.db`; never add it to source, environment files, logs, exceptions, prompts, snapshots, or test IDs.
- Use the existing `AiSettingsService`, `AiSettingsStore`, ORM models, Alembic migrations, and `DeepSeekProvider`; do not create a second configuration source or Provider implementation.
- `deepseek-v4-flash` runs normal, streaming, thinking, JSON Output, and Tool Calls tests; `deepseek-v4-pro` runs one normal non-streaming connectivity test.
- Do not add dependencies, fallback models, phase 3 code, or unrelated refactors.
- Preserve existing user changes in `.gitignore`, `.idea/`, `AGENTS.md`, and the staged live-test draft; stage only files named by each task.
- Record the actual `sqlite3.sqlite_version` during final validation.

---

## File Map

- Create `backend/tests/ai/live_config.py`: live-test-only database lookup and typed connection/model resolution.
- Create `backend/tests/ai/test_live_config.py`: isolated temporary-database regression tests for lookup, missing configuration, and secret-safe errors.
- Modify `backend/tests/ai/test_deepseek_live.py`: consume database settings, run the Flash capability suite, and add the Pro connectivity case.
- Modify `plan.md`: mark task 2.6 and phase 2 acceptance from actual evidence, append the validation record, and state that development stops before phase 3.
- Create no credential file and modify no production schema or API.

### Task 1: Resolve live DeepSeek settings from SQLite

**Files:**
- Create: `backend/tests/ai/live_config.py`
- Create: `backend/tests/ai/test_live_config.py`

**Interfaces:**
- Consumes: `AppConfig.for_local_app_data()`, `create_sqlite_engine(Path)`, `create_session_factory(Engine)`, `AiSettingsService.list_providers()`, `get_provider_connection(int)`, and `list_models(int | None)`.
- Produces: `LiveModelSettings(connection: ProviderConnection, model_id: str)` and `load_live_model(remote_model: str, database_path: Path | None = None) -> LiveModelSettings`.

- [ ] **Step 1: Write isolated failing tests for database resolution**

Create `backend/tests/ai/test_live_config.py` with tests that migrate a temporary database, create an enabled `DeepSeek Official` Provider plus both models through `AiSettingsService`, and assert:

```python
settings = load_live_model("deepseek-v4-flash", database_path)
assert settings.model_id == "deepseek-v4-flash"
assert settings.connection.provider_id == provider.id
assert settings.connection.base_url == DEEPSEEK_BASE_URL
assert settings.connection.api_key.get_secret_value() == "test-secret"
```

Add separate tests where the named Provider is disabled and where the model is absent. Assert `LiveAiConfigurationError` and assert `"test-secret" not in str(captured.value)` in both cases.

- [ ] **Step 2: Run the new tests and verify the expected import failure**

Run:

```powershell
uv run pytest backend/tests/ai/test_live_config.py -q
```

The test imports `from live_config import LiveAiConfigurationError, load_live_model`. Expected: collection fails with `ModuleNotFoundError: No module named 'live_config'` because pytest adds the test module directory to its import path but the helper does not exist yet.

- [ ] **Step 3: Implement the typed live configuration loader**

Create `backend/tests/ai/live_config.py` with this behavior:

```python
@dataclass(frozen=True)
class LiveModelSettings:
    connection: ProviderConnection
    model_id: str


class LiveAiConfigurationError(RuntimeError):
    """真实测试配置不可用；错误文本不得携带数据库值或密钥。"""


def load_live_model(
    remote_model: str, database_path: Path | None = None
) -> LiveModelSettings:
    resolved_path = database_path or AppConfig.for_local_app_data().paths.database_path
    if not resolved_path.is_file():
        raise LiveAiConfigurationError("本机应用数据库不存在，真实 AI 集成未验证")

    engine = create_sqlite_engine(resolved_path)
    try:
        service = AiSettingsService(create_session_factory(engine))
        providers = [
            item
            for item in service.list_providers()
            if item.name == "DeepSeek Official"
            and item.provider_type == "deepseek"
            and item.enabled
        ]
        if len(providers) != 1:
            raise LiveAiConfigurationError("启用的 DeepSeek Official 配置不唯一")
        provider = providers[0]
        models = [
            item
            for item in service.list_models(provider.id)
            if item.remote_model == remote_model and item.enabled
        ]
        if len(models) != 1:
            raise LiveAiConfigurationError("目标 DeepSeek 模型未启用")
        record = service.get_provider_connection(provider.id)
        return LiveModelSettings(
            connection=ProviderConnection(
                provider_id=record.provider_id,
                base_url=record.base_url,
                api_key=record.api_key,
                options=record.options,
            ),
            model_id=models[0].remote_model,
        )
    finally:
        engine.dispose()
```

Both `backend/tests/ai/test_live_config.py` and `backend/tests/ai/test_deepseek_live.py` import the helper with `from live_config import ...`; keep the helper test-only and do not add a production module.

- [ ] **Step 4: Run focused tests and static checks**

Run:

```powershell
uv run pytest backend/tests/ai/test_live_config.py -q
uv run ruff format --check backend/tests/ai/live_config.py backend/tests/ai/test_live_config.py
uv run ruff check backend/tests/ai/live_config.py backend/tests/ai/test_live_config.py
uv run pyright backend/tests/ai/live_config.py backend/tests/ai/test_live_config.py
```

Expected: all loader tests pass; Ruff and Pyright report no errors.

- [ ] **Step 5: Commit only the loader and its tests**

```powershell
git add backend/tests/ai/live_config.py backend/tests/ai/test_live_config.py
git commit -m "test: load live ai settings from database"
```

### Task 2: Build the requested Flash/Pro live test matrix

**Files:**
- Modify: `backend/tests/ai/test_deepseek_live.py`

**Interfaces:**
- Consumes: `load_live_model(remote_model: str) -> LiveModelSettings` from Task 1 and the existing `DeepSeekProvider.complete()` / `stream()` methods.
- Produces: five paid tests for `deepseek-v4-flash`, one paid connectivity test for `deepseek-v4-pro`, and `record_result(model, capability, usage)` with no sensitive response data.

- [ ] **Step 1: Replace the environment-variable fixture with failing database-backed assertions**

Remove `os`, `SecretStr`, `DEEPSEEK_BASE_URL`, the global `MODEL`, and `live_connection()`. Import `load_live_model`, define:

```python
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"
```

Change `record_result` to accept `model: str` and use that argument in the JSON ledger. Add:

```python
@pytest.mark.live_ai
async def test_live_pro_connectivity() -> None:
    settings = load_live_model(PRO_MODEL)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await DeepSeekProvider(client).complete(
            ChatRequest(
                model_id=settings.model_id,
                messages=[ChatMessage(role="user", content="Reply with exactly OK.")],
                max_output_tokens=16,
                thinking=ThinkingConfig(type="disabled"),
            ),
            settings.connection,
        )
    assert bool(response.text.strip()), "Pro 普通响应应包含文本"
    record_result(
        PRO_MODEL,
        "connectivity",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
```

Each Flash test must call `settings = load_live_model(FLASH_MODEL)`, pass `settings.model_id` and `settings.connection`, and record `FLASH_MODEL`.

- [ ] **Step 2: Collect the tests without making paid calls**

Run:

```powershell
uv run pytest backend/tests/ai/test_deepseek_live.py --collect-only -q
```

Expected: exactly six tests are collected; no network request is made.

- [ ] **Step 3: Run focused formatting, lint, and typing**

Run:

```powershell
uv run ruff format backend/tests/ai/test_deepseek_live.py
uv run ruff check backend/tests/ai/test_deepseek_live.py
uv run pyright backend/tests/ai/test_deepseek_live.py
```

Expected: all commands succeed with no Key, Prompt, response body, or reasoning printed.

- [ ] **Step 4: Commit only the live test matrix**

```powershell
git add backend/tests/ai/test_deepseek_live.py
git commit -m "test: add deepseek live capability matrix"
```

### Task 3: Persist the supplied Provider and models in the formal database

**Files:**
- Modify outside Git: `%LOCALAPPDATA%\ClearSkyEngine\data\app.db`
- No repository file contains the Key.

**Interfaces:**
- Consumes: existing migrations, `AiSettingsService.create_provider()`, `update_provider()`, `create_model()`, and `update_model()`.
- Produces: one enabled `DeepSeek Official` Provider and enabled `deepseek-v4-flash` / `deepseek-v4-pro` model rows.

- [ ] **Step 1: Back up and migrate the formal database**

Run the existing `backup_database()` then `upgrade_database()` against `AppConfig.for_local_app_data().paths.database_path`. Expected: backup is created under `%LOCALAPPDATA%\ClearSkyEngine\backups`, Alembic reports `head`, and the command prints only paths/version metadata.

- [ ] **Step 2: Upsert the supplied secret and model metadata through the Service**

Execute a one-time in-memory Python command whose secret value comes from the current user message and is never printed or written to a script. Use `AiSettingsService` to:

```python
provider_name = "DeepSeek Official"
provider_type = "deepseek"
base_url = DEEPSEEK_BASE_URL
models = (
    ("DeepSeek V4 Flash", "deepseek-v4-flash"),
    ("DeepSeek V4 Pro", "deepseek-v4-pro"),
)
```

If `provider_name` exists, call `update_provider(..., ProviderChanges(..., api_key_supplied=True, api_key=secret))`; otherwise call `create_provider(...)`. For each model, update the existing row under that Provider or create it with `enabled=True`, capability metadata matching the preset, and empty defaults. Do not delete or change unrelated rows.

- [ ] **Step 3: Read back only non-secret metadata**

Query through `AiSettingsService` and print only:

```text
provider=DeepSeek Official type=deepseek enabled=True has_api_key=True
model=deepseek-v4-flash enabled=True
model=deepseek-v4-pro enabled=True
sqlite=<actual sqlite3.sqlite_version>
```

Also call the Provider list API in an isolated client and assert the serialized response contains `has_api_key: true` and does not contain the supplied secret. Do not run a raw `SELECT api_key` readback.

- [ ] **Step 4: Confirm Git contains no secret**

Search tracked and untracked repository text for the Key using a command that reports only the count and filenames on failure, never matching lines. Expected: zero repository files contain it. This task changes no Git file and therefore has no commit.

### Task 4: Run paid validation and close phase 2

**Files:**
- Modify: `plan.md`

**Interfaces:**
- Consumes: six live tests, the full offline suite, root validation scripts, and safe ledger output.
- Produces: an evidence-backed phase 2 completion record or an explicit list of unverified capabilities; never starts phase 3.

- [ ] **Step 1: Run focused offline regressions**

Run:

```powershell
uv run pytest backend/tests/ai backend/tests/test_provider_api.py backend/tests/test_provider_migrations.py -q -m "not live_ai"
uv run ruff format --check backend
uv run ruff check backend
uv run pyright backend/src backend/tests
```

Expected: all offline tests and static checks pass.

- [ ] **Step 2: Run the complete repository checks**

Run:

```powershell
.\scripts\generate-api.ps1 -Check
.\scripts\check.ps1
```

Expected: OpenAPI has no drift; backend tests, Ruff, Pyright, Biome, TypeScript, Vitest, and Vite build all pass. Record the actual test counts and SQLite version from output.

- [ ] **Step 3: Run the paid DeepSeek tests once**

Run:

```powershell
uv run pytest backend/tests/ai/test_deepseek_live.py -m live_ai -q -s
```

Expected: six tests pass and six safe JSON ledger lines are printed—five for Flash and one `connectivity` line for Pro. If the remote service rejects a model or capability, preserve the sanitized error category and mark that exact item unverified; do not add fallback behavior or silently substitute a model.

- [ ] **Step 4: Update the phase 2 checklist from actual evidence**

In `plan.md`, check task 2.6 and phase 2 acceptance items only when supported by the commands above. Append a dated validation row containing commands, pass counts, both model IDs, safe capability results, token usage totals, and actual SQLite version. Replace the existing task 2.6 wording that says to expand phase 3 with an explicit statement that work stops after phase 2 per user direction.

- [ ] **Step 5: Verify documentation and diff hygiene**

Run:

```powershell
git diff --check
git diff -- plan.md backend/tests/ai/live_config.py backend/tests/ai/test_live_config.py backend/tests/ai/test_deepseek_live.py
git status --short
```

Expected: only the planned files plus pre-existing user changes appear; no Key, generated-file drift, unrelated formatting, or phase 3 implementation is present.

- [ ] **Step 6: Commit the phase 2 evidence**

```powershell
git add plan.md
git commit -m "docs: record phase 2 ai validation"
```

- [ ] **Step 7: Stop after reporting phase 2**

Report repository changes, exact offline and paid-test results, model/capability ledger, SQLite version, and any unverified item. Do not create a phase 3 plan or modify world, character, map, or turn code.
