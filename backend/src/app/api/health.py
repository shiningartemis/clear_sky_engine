"""应用健康检查 API。"""

import sqlite3
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Engine, text


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app_version: str
    database: Literal["ok"]
    sqlite_version: str


def create_health_router(engine: Engine, app_version: str) -> APIRouter:
    router = APIRouter()

    def _get_health() -> HealthResponse:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
        return HealthResponse(
            status="ok",
            app_version=app_version,
            database="ok",
            sqlite_version=sqlite3.sqlite_version,
        )

    router.add_api_route(
        "/api/health",
        _get_health,
        methods=["GET"],
        response_model=HealthResponse,
    )
    return router
