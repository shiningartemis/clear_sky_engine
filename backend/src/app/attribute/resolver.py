"""动态属性定义校验、最终值组合与更新计算。"""

from collections.abc import Mapping, Sequence, Set
from typing import TypeGuard

from pydantic import ValidationError

from app.attribute.models import (
    AttributeDefinition,
    AttributeDefinitionError,
    AttributeOperation,
    AttributeScalar,
    AttributeUpdateIntent,
)


class AttributeUpdateError(ValueError):
    """受控属性更新意图不能安全应用。"""


def _validation_message(error: ValidationError) -> str:
    first_error = error.errors()[0]
    context = first_error.get("ctx")
    if isinstance(context, dict):
        cause = context.get("error")
        if isinstance(cause, ValueError):
            return str(cause)
    return first_error["msg"]


def validate_attribute_definitions(
    definitions: Sequence[AttributeDefinition],
) -> tuple[AttributeDefinition, ...]:
    """校验完整定义集合，避免分列 JSON 被不同规则解释。"""
    keys = [item.key for item in definitions]
    if len(keys) != len(set(keys)):
        raise AttributeDefinitionError("属性 key 不能重复")

    checked: list[AttributeDefinition] = []
    for item in definitions:
        try:
            checked.append(AttributeDefinition.model_validate(item.model_dump(mode="python")))
        except ValidationError as error:
            raise AttributeDefinitionError(_validation_message(error)) from error
    return tuple(checked)


def is_compatible_change(
    definition: AttributeDefinition,
    value: AttributeScalar | None,
) -> bool:
    """显式区分 bool 与 int，防止 Python 的继承关系污染持久化语义。"""
    if value is None:
        return False
    if definition.data_type == "integer":
        return type(value) is int
    if definition.data_type == "number":
        return type(value) in {int, float}
    if definition.data_type == "boolean":
        return type(value) is bool
    if definition.data_type == "enum":
        return type(value) is str and value in definition.enum_options
    return type(value) is str


def _numeric_add(
    definition: AttributeDefinition,
    left: AttributeScalar,
    right: AttributeScalar,
) -> int | float:
    if definition.data_type == "integer":
        return int(left) + int(right)
    return float(left) + float(right)


def _numeric_subtract(
    definition: AttributeDefinition,
    left: AttributeScalar,
    right: AttributeScalar,
) -> int | float:
    if definition.data_type == "integer":
        return int(left) - int(right)
    return float(left) - float(right)


def _clamp_numeric(definition: AttributeDefinition, value: int | float) -> int | float:
    """仅读取既存变化值时收敛旧数据，新意图必须走拒绝路径。"""
    result = value
    if definition.minimum is not None and result < definition.minimum:
        result = definition.minimum
    if definition.maximum is not None and result > definition.maximum:
        result = definition.maximum
    if definition.data_type == "integer":
        return int(result)
    return float(result)


def resolve_effective_attributes(
    definitions: Sequence[AttributeDefinition],
    changes: Mapping[str, AttributeScalar],
) -> dict[str, AttributeScalar]:
    """只遍历角色主表 key；数值变化相加，其余变化替换。"""
    result: dict[str, AttributeScalar] = {}
    for definition in definitions:
        change = changes.get(definition.key)
        if change is None or not is_compatible_change(definition, change):
            result[definition.key] = definition.base_value
        elif definition.data_type in {"integer", "number"}:
            result[definition.key] = _clamp_numeric(
                definition,
                _numeric_add(definition, definition.base_value, change),
            )
        else:
            result[definition.key] = change
    return result


def _is_compatible_numeric_operand(
    value: AttributeScalar,
    definition: AttributeDefinition,
) -> TypeGuard[int | float]:
    if definition.data_type == "integer":
        return type(value) is int
    return type(value) in {int, float}


def _validate_numeric_constraints(
    definition: AttributeDefinition,
    value: int | float,
) -> None:
    if definition.minimum is not None and value < definition.minimum:
        raise AttributeUpdateError("属性值不能小于最小值")
    if definition.maximum is not None and value > definition.maximum:
        raise AttributeUpdateError("属性值不能大于最大值")


def _calculate_next_change(
    definition: AttributeDefinition,
    *,
    current_change: AttributeScalar | None,
    operation: AttributeOperation,
    operand: AttributeScalar,
) -> AttributeScalar:
    if definition.data_type not in {"integer", "number"}:
        if operation != "replace" or not is_compatible_change(definition, operand):
            raise AttributeUpdateError("非数值属性只允许同类型 replace")
        return operand

    if not _is_compatible_numeric_operand(operand, definition):
        raise AttributeUpdateError("数值操作的值类型无效")
    compatible_change = (
        current_change
        if current_change is not None and is_compatible_change(definition, current_change)
        else 0
    )
    current_final = _numeric_add(definition, definition.base_value, compatible_change)
    if operation == "replace":
        target_final = operand
    elif operation == "increment":
        target_final = _numeric_add(definition, current_final, operand)
    else:
        target_final = _numeric_subtract(definition, current_final, operand)
    _validate_numeric_constraints(definition, target_final)
    return _numeric_subtract(definition, target_final, definition.base_value)


def apply_attribute_updates(
    definitions: Sequence[AttributeDefinition],
    current_changes: Mapping[str, AttributeScalar],
    intents: Sequence[AttributeUpdateIntent],
    *,
    role_id: int,
    current_version: int,
    valid_event_keys: Set[str],
) -> dict[str, AttributeScalar]:
    """在内存副本原子应用意图，失败时不改变调用方的旧变化映射。"""
    next_changes = dict(current_changes)
    by_key = {item.key: item for item in definitions}
    for intent in intents:
        if intent.role_id != role_id:
            raise AttributeUpdateError("属性更新角色不匹配")
        if intent.expected_version != current_version:
            raise AttributeUpdateError("角色属性版本已变化")
        if intent.source_event_id is not None and intent.source_event_id not in valid_event_keys:
            raise AttributeUpdateError("属性更新依据不属于当前轮次")
        definition = by_key.get(intent.attribute_key)
        if definition is None or intent.operation not in definition.allowed_operations:
            raise AttributeUpdateError("属性或操作无效")
        next_changes[intent.attribute_key] = _calculate_next_change(
            definition,
            current_change=next_changes.get(intent.attribute_key),
            operation=intent.operation,
            operand=intent.value,
        )
    resolve_effective_attributes(definitions, next_changes)
    return next_changes
