"""两个固定 AI 任务的严格输出 Schema 与程序边界校验。"""

from collections.abc import Mapping, Set
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.attribute import AttributeUpdateIntent


class OutputBoundaryError(ValueError):
    """AI 输出违反冻结地点、角色、知识或状态命令边界。"""


class StrictOutputModel(BaseModel):
    """AI 输出不得携带程序未声明、因而无法安全解释的字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EventKnowledge(StrictOutputModel):
    role_id: int = Field(gt=0)
    level: Literal["participant", "observer", "told", "public"]
    perspective_notes: str = ""


class ObjectiveEventOutput(StrictOutputModel):
    event_key: str = Field(min_length=1, max_length=80)
    group_id: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=80)
    fact: dict[str, JsonValue]
    knowledge: list[EventKnowledge]


class RoleChronicleOutput(StrictOutputModel):
    role_id: int = Field(gt=0)
    content: str = Field(min_length=1)
    known_event_keys: list[str]


class InteractionGroupOutput(StrictOutputModel):
    group_id: str = Field(min_length=1, max_length=80)
    role_ids: list[int] = Field(min_length=1)


class LocationSimulationOutput(StrictOutputModel):
    location_id: str = Field(min_length=1, max_length=40)
    groups: list[InteractionGroupOutput] = Field(min_length=1)
    events: list[ObjectiveEventOutput]
    chronicles: list[RoleChronicleOutput] = Field(min_length=1)


class RoleAttributeMemoryOutput(StrictOutputModel):
    role_id: int = Field(gt=0)
    attribute_update_intents: list[AttributeUpdateIntent]
    memory_append: str = Field(min_length=1)


class AttributeMemoryAnalysisOutput(StrictOutputModel):
    location_id: str = Field(min_length=1, max_length=40)
    roles: list[RoleAttributeMemoryOutput] = Field(min_length=1)


def _require_unique(values: list[str] | list[int], message: str) -> None:
    if len(values) != len(set(values)):
        raise OutputBoundaryError(message)


def validate_location_simulation_output(
    output: LocationSimulationOutput,
    *,
    expected_location_id: str,
    expected_role_ids: Set[int],
) -> LocationSimulationOutput:
    """用程序冻结事实校验全图输出，AI 不拥有地点和角色集合裁决权。"""

    if output.location_id != expected_location_id:
        raise OutputBoundaryError("地点推演输出与冻结地点不一致")

    group_ids = [group.group_id for group in output.groups]
    _require_unique(group_ids, "互动组 ID 不能重复")
    grouped_role_ids = [role_id for group in output.groups for role_id in group.role_ids]
    if len(grouped_role_ids) != len(set(grouped_role_ids)) or set(grouped_role_ids) != set(
        expected_role_ids
    ):
        raise OutputBoundaryError("分组角色必须完整且唯一")

    chronicle_role_ids = [chronicle.role_id for chronicle in output.chronicles]
    if len(chronicle_role_ids) != len(set(chronicle_role_ids)) or set(chronicle_role_ids) != set(
        expected_role_ids
    ):
        raise OutputBoundaryError("角色纪事必须完整且唯一")

    event_keys = [event.event_key for event in output.events]
    _require_unique(event_keys, "事件 key 不能重复")
    event_key_set = set(event_keys)
    group_id_set = set(group_ids)
    known_by_role: dict[int, set[str]] = {role_id: set() for role_id in expected_role_ids}
    for event in output.events:
        if event.group_id not in group_id_set:
            raise OutputBoundaryError("事件引用了未知互动组")
        knowledge_role_ids = [item.role_id for item in event.knowledge]
        _require_unique(knowledge_role_ids, "同一事件的角色知识不能重复")
        if not set(knowledge_role_ids) <= set(expected_role_ids):
            raise OutputBoundaryError("事件知识包含跨地点角色")
        for item in event.knowledge:
            known_by_role[item.role_id].add(event.event_key)

    for chronicle in output.chronicles:
        _require_unique(chronicle.known_event_keys, "纪事事件引用不能重复")
        if not set(chronicle.known_event_keys) <= event_key_set:
            raise OutputBoundaryError("纪事引用了未知事件")
        if set(chronicle.known_event_keys) != known_by_role[chronicle.role_id]:
            raise OutputBoundaryError("事件知识与角色纪事不一致")
    return output


def validate_attribute_memory_output(
    output: AttributeMemoryAnalysisOutput,
    *,
    expected_location_id: str,
    expected_role_ids: Set[int],
    valid_event_keys_by_role: Mapping[int, Set[str]],
    memory_max_chars: int,
) -> AttributeMemoryAnalysisOutput:
    """属性和记忆节点只接受本地图完整角色集及冻结事件引用。"""

    if output.location_id != expected_location_id:
        raise OutputBoundaryError("属性与记忆输出与冻结地点不一致")
    role_ids = [role.role_id for role in output.roles]
    if len(role_ids) != len(set(role_ids)) or set(role_ids) != set(expected_role_ids):
        raise OutputBoundaryError("属性与记忆角色必须完整且唯一")
    if memory_max_chars < 1:
        raise OutputBoundaryError("记忆摘要硬上限无效")
    if set(valid_event_keys_by_role) != set(expected_role_ids):
        raise OutputBoundaryError("角色事件知识边界不完整")

    for role in output.roles:
        if "__" in role.memory_append or len(role.memory_append) > memory_max_chars:
            raise OutputBoundaryError("记忆摘要含分隔符或超过硬上限")
        for intent in role.attribute_update_intents:
            if intent.role_id != role.role_id:
                raise OutputBoundaryError("属性更新意图角色不匹配")
            if (
                intent.source_event_id is not None
                and intent.source_event_id not in valid_event_keys_by_role[role.role_id]
            ):
                raise OutputBoundaryError("属性更新意图引用了未知事件")
    return output
