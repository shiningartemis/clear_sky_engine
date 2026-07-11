"""应用进程控制 API。"""

import secrets
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, SecretStr


class ShutdownResponse(BaseModel):
    status: Literal["shutting_down"]


def create_application_router(
    shutdown_token: SecretStr,
    shutdown_callback: Callable[[], None],
) -> APIRouter:
    router = APIRouter()

    def _shutdown(
        supplied_token: Annotated[
            str | None,
            Header(alias="X-Clear-Sky-Shutdown-Token"),
        ] = None,
    ) -> ShutdownResponse:
        expected_token = shutdown_token.get_secret_value()
        if supplied_token is None or not secrets.compare_digest(supplied_token, expected_token):
            raise HTTPException(status_code=403, detail="Forbidden")
        shutdown_callback()
        return ShutdownResponse(status="shutting_down")

    router.add_api_route(
        "/api/app/shutdown",
        _shutdown,
        methods=["POST"],
        response_model=ShutdownResponse,
    )
    return router
