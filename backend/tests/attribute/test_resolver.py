"""动态属性定义、组合与受控更新测试。"""

import pytest
from pydantic import ValidationError

from app.attribute.models import (
    AttributeDataType,
    AttributeDefinition,
    AttributeDefinitionError,
    AttributeDefinitionMaps,
    AttributeOperation,
    AttributeScalar,
    AttributeUpdateIntent,
    decode_attribute_definitions,
    encode_attribute_definitions,
)
from app.attribute.resolver import (
    AttributeUpdateError,
    apply_attribute_updates,
    resolve_effective_attributes,
    validate_attribute_definitions,
)


def definition(
    key: str,
    data_type: AttributeDataType,
    base_value: AttributeScalar,
    *,
    operations: set[AttributeOperation] | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    enum_options: tuple[str, ...] = (),
) -> AttributeDefinition:
    """用未校验构造支持集中验证函数的无效定义测试。"""
    return AttributeDefinition.model_construct(
        key=key,
        display_name=key,
        data_type=data_type,
        base_value=base_value,
        description=f"{key} 描述",
        update_rule=f"{key} 更新规则",
        allowed_operations=frozenset(operations or {"replace"}),
        minimum=minimum,
        maximum=maximum,
        enum_options=enum_options,
        update_example=None,
        no_update_example=None,
    )


def update_intent(
    *,
    role_id: int = 7,
    attribute_key: str = "level",
    operation: AttributeOperation = "replace",
    value: AttributeScalar = 15,
    source_event_id: int = 101,
    expected_version: int = 3,
) -> AttributeUpdateIntent:
    return AttributeUpdateIntent(
        role_id=role_id,
        attribute_key=attribute_key,
        operation=operation,
        value=value,
        reason="本轮事件导致属性变化",
        source_event_id=source_event_id,
        expected_version=expected_version,
    )


@pytest.mark.parametrize(
    ("definitions", "changes", "expected"),
    [
        ([definition("level", "integer", 10)], {"level": 1}, {"level": 11}),
        ([definition("money", "number", 1000.0)], {"money": -50}, {"money": 950.0}),
        ([definition("title", "string", "学徒")], {"title": "大魔法师"}, {"title": "大魔法师"}),
        ([definition("alive", "boolean", True)], {"alive": False}, {"alive": False}),
        ([definition("level", "integer", 10)], {"removed": 99}, {"level": 10}),
        ([definition("level", "integer", 10)], {"level": "wrong"}, {"level": 10}),
        ([definition("level", "integer", 10)], {"level": True}, {"level": 10}),
    ],
)
def test_effective_attributes_follow_role_master(
    definitions: list[AttributeDefinition],
    changes: dict[str, AttributeScalar],
    expected: dict[str, AttributeScalar],
) -> None:
    assert resolve_effective_attributes(definitions, changes) == expected


@pytest.mark.parametrize(
    ("definitions", "message"),
    [
        (
            [definition("level", "integer", 1), definition("level", "integer", 2)],
            "属性 key 不能重复",
        ),
        (
            [definition("title", "enum", "学徒", enum_options=("法师",))],
            "枚举基础值必须属于选项",
        ),
        (
            [definition("title", "string", "学徒", operations={"increment"})],
            "当前类型不支持该操作",
        ),
        (
            [definition("level", "integer", 1, minimum=10, maximum=2)],
            "最小值不能大于最大值",
        ),
    ],
)
def test_invalid_definitions_are_rejected(
    definitions: list[AttributeDefinition], message: str
) -> None:
    with pytest.raises(AttributeDefinitionError, match=message):
        validate_attribute_definitions(definitions)


@pytest.mark.parametrize(
    ("definitions", "current_changes", "intent", "expected", "message"),
    [
        (
            [definition("level", "integer", 10)],
            {"removed": 99},
            update_intent(value=15),
            {"removed": 99, "level": 5},
            None,
        ),
        (
            [definition("level", "integer", 10)],
            {},
            update_intent(role_id=8),
            None,
            "属性更新角色不匹配",
        ),
        (
            [definition("level", "integer", 10)],
            {},
            update_intent(source_event_id=202),
            None,
            "属性更新依据不属于当前轮次",
        ),
        (
            [definition("level", "integer", 10)],
            {},
            update_intent(expected_version=4),
            None,
            "角色属性版本已变化",
        ),
    ],
)
def test_updates_are_checked_and_preserve_stale_values(
    definitions: list[AttributeDefinition],
    current_changes: dict[str, AttributeScalar],
    intent: AttributeUpdateIntent,
    expected: dict[str, AttributeScalar] | None,
    message: str | None,
) -> None:
    if message is not None:
        with pytest.raises(AttributeUpdateError, match=message):
            apply_attribute_updates(
                definitions,
                current_changes,
                [intent],
                role_id=7,
                current_version=3,
                valid_event_ids={101},
            )
        return

    assert (
        apply_attribute_updates(
            definitions,
            current_changes,
            [intent],
            role_id=7,
            current_version=3,
            valid_event_ids={101},
        )
        == expected
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"data_type": "integer", "base_value": True}, "整数基础值类型无效"),
        (
            {"data_type": "enum", "base_value": "法师", "enum_options": ("",)},
            "枚举选项不能为空",
        ),
        (
            {"data_type": "enum", "base_value": "法师", "enum_options": ("法师", "法师")},
            "枚举选项不能重复",
        ),
    ],
)
def test_boundary_model_rejects_invalid_definition(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "key": "level",
        "display_name": "等级",
        "data_type": "integer",
        "base_value": 1,
        "description": "角色等级",
        "update_rule": "仅在成长时更新",
        "allowed_operations": frozenset({"replace"}),
    }
    values.update(kwargs)

    with pytest.raises(ValidationError, match=message):
        AttributeDefinition.model_validate(values)


def test_read_path_clamps_legacy_numeric_value() -> None:
    definitions = [definition("level", "integer", 10, minimum=0, maximum=12)]

    assert resolve_effective_attributes(definitions, {"level": 99}) == {"level": 12}


def test_new_update_outside_numeric_constraints_is_rejected() -> None:
    definitions = [definition("level", "integer", 10, minimum=0, maximum=12)]

    with pytest.raises(AttributeUpdateError, match="属性值不能大于最大值"):
        apply_attribute_updates(
            definitions,
            {},
            [update_intent(value=13)],
            role_id=7,
            current_version=3,
            valid_event_ids={101},
        )


def test_attribute_definition_codec_round_trip_is_lossless() -> None:
    original = AttributeDefinition(
        key="level",
        display_name="等级",
        data_type="integer",
        base_value=10,
        description="角色成长等级",
        update_rule="仅在明确成长时更新",
        allowed_operations=frozenset({"replace", "increment", "decrement"}),
        minimum=0,
        maximum=99,
        update_example="完成训练后增加一级",
        no_update_example="普通闲聊不改变等级",
    )

    encoded = encode_attribute_definitions([original])

    assert decode_attribute_definitions(encoded) == (original,)


def test_decode_rejects_mismatched_required_keys() -> None:
    maps = AttributeDefinitionMaps(
        base_values={"level": 10},
        types={"level": "integer"},
        labels={"level": "等级"},
        descriptions={"level": "角色成长等级"},
        update_rules={},
        constraints={},
        allowed_operations={"level": ["replace"]},
        examples={},
    )

    with pytest.raises(AttributeDefinitionError, match="属性定义必填映射 key 必须一致"):
        decode_attribute_definitions(maps)


def test_decode_ignores_stale_optional_map_keys() -> None:
    maps = AttributeDefinitionMaps(
        base_values={"level": 10},
        types={"level": "integer"},
        labels={"level": "等级"},
        descriptions={"level": "角色成长等级"},
        update_rules={"level": "仅在明确成长时更新"},
        constraints={"removed": {"minimum": 0}},
        allowed_operations={"level": ["replace"]},
        examples={"removed": {"update": "旧示例"}},
    )

    decoded = decode_attribute_definitions(maps)

    assert tuple(item.key for item in decoded) == ("level",)
