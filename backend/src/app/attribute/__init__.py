"""动态属性定义、组合与受控更新能力。"""

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

__all__ = [
    "AttributeDataType",
    "AttributeDefinition",
    "AttributeDefinitionError",
    "AttributeDefinitionMaps",
    "AttributeOperation",
    "AttributeScalar",
    "AttributeUpdateError",
    "AttributeUpdateIntent",
    "apply_attribute_updates",
    "decode_attribute_definitions",
    "encode_attribute_definitions",
    "resolve_effective_attributes",
    "validate_attribute_definitions",
]
