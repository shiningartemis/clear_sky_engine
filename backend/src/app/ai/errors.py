"""AI Provider 的统一、安全错误语义。"""

from enum import StrEnum


class AiErrorCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK = "network"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    CANCELLED = "cancelled"


class AiProviderError(Exception):
    """只保存脱敏诊断；原始请求、响应和异常链不得进入此对象。"""

    def __init__(
        self,
        *,
        category: AiErrorCategory,
        message: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code


class UnknownProviderError(LookupError):
    """注册表中不存在请求的 Provider 类型。"""
