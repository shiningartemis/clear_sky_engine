"""第一版仅有的两个稳定 AI 任务定义。"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel

from app.workflow.schemas import AttributeMemoryAnalysisOutput, LocationSimulationOutput
from app.workflow.settings import TaskKey


@dataclass(frozen=True)
class TaskDefinition:
    """固定任务只声明稳定 key、边界 Schema 和不可由用户替换的系统约束。"""

    task_key: TaskKey
    output_model: type[BaseModel]
    system_prompt: str


LOCATION_SIMULATION = TaskDefinition(
    task_key=TaskKey.LOCATION_SIMULATION,
    output_model=LocationSimulationOutput,
    system_prompt=(
        "你负责推演一个程序冻结地点内的全部角色。玩家输入只是主角准备尝试的行动, "
        "NPC 可以拒绝、忽略或自行互动; 主角没有成功保证或因果优先级。地图是直接互动"
        "范围, 不得让其他地图角色参与。位置完全由程序裁决, 输出不得暗示或提交位置变更。"
        "每篇角色纪事只能包含该角色亲历、感知、被告知或公开可知的内容, 不得在同一次"
        "全图生成中泄露其他角色视角。互动优先但不强迫, 单人组合法; 只有一名角色时只"
        "生成特别简短的一句话纪事, 不得为凑篇幅虚构无意义事件。"
    ),
)

ATTRIBUTE_MEMORY_ANALYSIS = TaskDefinition(
    task_key=TaskKey.ATTRIBUTE_MEMORY_ANALYSIS,
    output_model=AttributeMemoryAnalysisOutput,
    system_prompt=(
        "你只分析当前冻结地点本轮已经校验的纪事和事件。每名角色仅依据自己的纪事、"
        "可知事件、当前最终属性及对应更新规则提交结构化属性更新意图和一段记忆摘要。"
        "不得直接写状态, 不得引用其他地点、未知事件或其他角色不可知的内容。"
    ),
)

TASK_DEFINITIONS: Mapping[TaskKey, TaskDefinition] = MappingProxyType(
    {
        TaskKey.LOCATION_SIMULATION: LOCATION_SIMULATION,
        TaskKey.ATTRIBUTE_MEMORY_ANALYSIS: ATTRIBUTE_MEMORY_ANALYSIS,
    }
)
