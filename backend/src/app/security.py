"""生产环境 loopback Host 与同源 Origin 安全边界。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class LocalSecurity(BaseModel):
    """只描述本次启动的本地来源，令牌不得进入响应或日志。"""

    model_config = ConfigDict(frozen=True)

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    shutdown_token: SecretStr

    @property
    def host_header(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def origin(self) -> str:
        return f"http://{self.host_header}"


class LocalSecurityMiddleware:
    """在路由前拒绝伪造 Host 和跨来源修改请求。"""

    def __init__(self, app: ASGIApp, security: LocalSecurity) -> None:
        self.app = app
        self.security = security

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if headers.get("host") != self.security.host_header:
            await PlainTextResponse("Invalid Host", status_code=400)(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method in MUTATING_METHODS and headers.get("origin") != self.security.origin:
            await PlainTextResponse("Forbidden", status_code=403)(scope, receive, send)
            return

        await self.app(scope, receive, send)
