"""动态属性的严格边界模型与持久化映射。"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

AttributeScalar = int | float | str | bool
AttributeDataType = Literal["integer", "number", "string", "boolean", "enum"]
AttributeOperation = Literal["replace", "increment", "decrement"]


class AttributeDefinitionError(ValueError):
    """属性定义之间或持久化定义映射不一致。"""


class AttributeDefinition(BaseModel):
    """角色主表拥有的单个平铺属性定义。"""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    display_name: Annotated[str, Field(min_length=1, max_length=80)]
    data_type: AttributeDataType
    base_value: AttributeScalar
    description: Annotated[str, Field(min_length=1, max_length=1000)]
    update_rule: Annotated[str, Field(min_length=1, max_length=4000)]
    allowed_operations: frozenset[AttributeOperation]
    minimum: float | None = None
    maximum: float | None = None
    enum_options: tuple[str, ...] = ()
    update_example: str | None = None
    no_update_example: str | None = None

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        """类型定义是持久化值解释方式，必须在写入边界一次校准。"""
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("最小值不能大于最大值")

        numeric = self.data_type in {"integer", "number"}
        if not numeric and (self.minimum is not None or self.maximum is not None):
            raise ValueError("非数值属性不能设置数值范围")

        if self.data_type == "integer" and type(self.base_value) is not int:
            raise ValueError("整数基础值类型无效")
        if self.data_type == "number" and type(self.base_value) not in {int, float}:
            raise ValueError("数值基础值类型无效")
        if self.data_type == "string" and type(self.base_value) is not str:
            raise ValueError("字符串基础值类型无效")
        if self.data_type == "boolean" and type(self.base_value) is not bool:
            raise ValueError("布尔基础值类型无效")
        if self.data_type in {"integer", "number"} and (
            type(self.base_value) is int or type(self.base_value) is float
        ):
            numeric_base = self.base_value
            if self.minimum is not None and numeric_base < self.minimum:
                raise ValueError("基础值不能小于最小值")
            if self.maximum is not None and numeric_base > self.maximum:
                raise ValueError("基础值不能大于最大值")

        if self.data_type == "enum":
            if any(not option for option in self.enum_options):
                raise ValueError("枚举选项不能为空")
            if len(self.enum_options) != len(set(self.enum_options)):
                raise ValueError("枚举选项不能重复")
            if type(self.base_value) is not str or self.base_value not in self.enum_options:
                raise ValueError("枚举基础值必须属于选项")
        elif self.enum_options:
            raise ValueError("只有枚举属性可以设置选项")

        supported_operations: frozenset[AttributeOperation]
        if numeric:
            supported_operations = frozenset({"replace", "increment", "decrement"})
        else:
            supported_operations = frozenset({"replace"})
        if not self.allowed_operations <= supported_operations:
            raise ValueError("当前类型不支持该操作")
        return self


class AttributeUpdateIntent(BaseModel):
    """AI 只能提交该结构化意图，不能直接修改世界属性。"""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    role_id: int = Field(gt=0)
    attribute_key: str
    operation: AttributeOperation
    value: AttributeScalar
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    source_event_id: Annotated[str, Field(min_length=1, max_length=80)] | None
    expected_version: int = Field(ge=1)


@dataclass(frozen=True)
class AttributeDefinitionMaps:
    """角色主表中分列保存的属性定义 JSON。"""

    base_values: dict[str, AttributeScalar]
    types: dict[str, str]
    labels: dict[str, str]
    descriptions: dict[str, str]
    update_rules: dict[str, str]
    constraints: dict[str, JsonValue]
    allowed_operations: dict[str, JsonValue]
    examples: dict[str, JsonValue]


def encode_attribute_definitions(
    definitions: Sequence[AttributeDefinition],
) -> AttributeDefinitionMaps:
    """按角色主表的分列 JSON 契约无损编码属性定义。"""
    from app.attribute.resolver import validate_attribute_definitions

    checked = validate_attribute_definitions(definitions)
    allowed_operations: dict[str, JsonValue] = {}
    for item in checked:
        operations: list[JsonValue] = [operation for operation in sorted(item.allowed_operations)]
        allowed_operations[item.key] = operations

    return AttributeDefinitionMaps(
        base_values={item.key: item.base_value for item in checked},
        types={item.key: item.data_type for item in checked},
        labels={item.key: item.display_name for item in checked},
        descriptions={item.key: item.description for item in checked},
        update_rules={item.key: item.update_rule for item in checked},
        constraints={
            item.key: {
                "minimum": item.minimum,
                "maximum": item.maximum,
                "enum_options": list(item.enum_options),
            }
            for item in checked
            if item.minimum is not None or item.maximum is not None or item.enum_options
        },
        allowed_operations=allowed_operations,
        examples={
            item.key: {
                "update": item.update_example,
                "no_update": item.no_update_example,
            }
            for item in checked
            if item.update_example is not None or item.no_update_example is not None
        },
    )


def _optional_object(values: dict[str, JsonValue], key: str, *, label: str) -> dict[str, JsonValue]:
    value = values.get(key, {})
    if not isinstance(value, dict):
        raise AttributeDefinitionError(f"属性定义{label}格式无效")
    return value


def _string_array(value: JsonValue, *, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AttributeDefinitionError(f"属性定义{label}格式无效")
    return [item for item in value if isinstance(item, str)]


def decode_attribute_definitions(
    maps: AttributeDefinitionMaps,
) -> tuple[AttributeDefinition, ...]:
    """只按基础值 key 解码，并拒绝必填分列错位造成的规则串用。"""
    from app.attribute.resolver import validate_attribute_definitions

    base_keys = set(maps.base_values)
    required_key_sets = (
        set(maps.types),
        set(maps.labels),
        set(maps.descriptions),
        set(maps.update_rules),
        set(maps.allowed_operations),
    )
    if any(keys != base_keys for keys in required_key_sets):
        raise AttributeDefinitionError("属性定义必填映射 key 必须一致")

    definitions: list[AttributeDefinition] = []
    for key, base_value in maps.base_values.items():
        constraints = _optional_object(maps.constraints, key, label="约束")
        examples = _optional_object(maps.examples, key, label="示例")
        allowed_operations = _string_array(maps.allowed_operations[key], label="允许操作")
        enum_options = _string_array(constraints.get("enum_options", []), label="枚举选项")
        values: dict[str, object] = {
            "key": key,
            "display_name": maps.labels[key],
            "data_type": maps.types[key],
            "base_value": base_value,
            "description": maps.descriptions[key],
            "update_rule": maps.update_rules[key],
            "allowed_operations": frozenset(allowed_operations),
            "minimum": constraints.get("minimum"),
            "maximum": constraints.get("maximum"),
            "enum_options": tuple(enum_options),
            "update_example": examples.get("update"),
            "no_update_example": examples.get("no_update"),
        }
        try:
            definitions.append(AttributeDefinition.model_validate(values))
        except ValueError as error:
            raise AttributeDefinitionError("属性定义持久化数据无效") from error
    return validate_attribute_definitions(definitions)
