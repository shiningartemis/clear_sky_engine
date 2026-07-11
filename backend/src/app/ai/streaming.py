"""流式 Tool Call 分片的确定性聚合。"""

from dataclasses import dataclass

from app.ai.dto import FunctionCall, ToolCall, ToolCallDelta


@dataclass
class _PartialToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


class ToolCallAccumulator:
    """按稳定 index 聚合分片，完成时再校验必填字段。"""

    def __init__(self) -> None:
        self._calls: dict[int, _PartialToolCall] = {}

    def add(self, delta: ToolCallDelta) -> None:
        partial = self._calls.setdefault(delta.index, _PartialToolCall())
        if delta.id is not None:
            partial.id = delta.id
        partial.name += delta.name_delta
        partial.arguments += delta.arguments_delta

    def finish(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for index, partial in sorted(self._calls.items()):
            if not partial.id or not partial.name:
                raise ValueError("Tool Call 流缺少 id 或函数名")
            calls.append(
                ToolCall(
                    id=partial.id,
                    index=index,
                    function=FunctionCall(name=partial.name, arguments=partial.arguments),
                )
            )
        return calls
