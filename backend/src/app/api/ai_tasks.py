"""应用级固定 AI 任务设置 API。"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.ai.service import AiSettingsService
from app.ai.types import JsonValue
from app.workflow.settings import (
    ReasoningEffort,
    StructuredOutputMode,
    TaskKey,
    TaskSettingConfigurationError,
    TaskSettingNotFoundError,
    TaskSettingPersistenceError,
    TaskSettingRecord,
    TaskSettingUpdate,
    TaskSettingValidationError,
)


class TaskSettingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_key: TaskKey
    model_id: int | None
    temperature: float | None
    max_output_tokens: int | None
    reasoning_effort: ReasoningEffort | None
    timeout_seconds: int
    extra_prompt: str
    structured_output_mode: StructuredOutputMode
    provider_options: dict[str, JsonValue]
    memory_target_chars: int | None
    memory_max_chars: int | None
    version: int
    updated_at: datetime


class _SafeValidationIssue(BaseModel):
    """422 只保留定位信息，禁止回显可能包含密钥的原始 input/ctx。"""

    type: str
    loc: tuple[str | int, ...]
    msg: str


_VALIDATION_ISSUES = TypeAdapter(list[_SafeValidationIssue])


async def safe_request_validation_error(
    _request: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    issues = _VALIDATION_ISSUES.validate_python(error.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": [issue.model_dump(mode="json") for issue in issues]},
    )


def _response(record: TaskSettingRecord) -> TaskSettingResponse:
    return TaskSettingResponse.model_validate(record)


def create_ai_task_router(service: AiSettingsService) -> APIRouter:
    """路由只处理 DTO 与 HTTP 映射，配置校验和事务留在 Service。"""

    router = APIRouter(prefix="/api/ai-task-settings")

    def _list_settings() -> list[TaskSettingResponse]:
        return [_response(item) for item in service.list_task_settings()]

    def _update_setting(
        task_key: TaskKey,
        payload: TaskSettingUpdate,
    ) -> TaskSettingResponse:
        try:
            return _response(service.update_task_setting(task_key, payload))
        except TaskSettingNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from None
        except (TaskSettingValidationError, TaskSettingConfigurationError) as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from None
        except TaskSettingPersistenceError as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(error),
            ) from None

    router.add_api_route(
        "", _list_settings, methods=["GET"], response_model=list[TaskSettingResponse]
    )
    router.add_api_route(
        "/{task_key}",
        _update_setting,
        methods=["PUT"],
        response_model=TaskSettingResponse,
    )
    return router
