"""固定 AI 输出 Schema 与程序裁决边界测试。"""

import pytest

from app.attribute import AttributeUpdateIntent
from app.workflow.schemas import (
    AttributeMemoryAnalysisOutput,
    EventKnowledge,
    InteractionGroupOutput,
    LocationSimulationOutput,
    ObjectiveEventOutput,
    OutputBoundaryError,
    RoleAttributeMemoryOutput,
    RoleChronicleOutput,
    validate_attribute_memory_output,
    validate_location_simulation_output,
)


def _location_output(
    *,
    groups: list[InteractionGroupOutput] | None = None,
    events: list[ObjectiveEventOutput] | None = None,
    chronicles: list[RoleChronicleOutput] | None = None,
) -> LocationSimulationOutput:
    return LocationSimulationOutput(
        location_id="the_home",
        groups=groups or [InteractionGroupOutput(group_id="all", role_ids=[1, 2])],
        events=(
            events
            if events is not None
            else [
                ObjectiveEventOutput(
                    event_key="greeting",
                    group_id="all",
                    event_type="conversation",
                    fact={"summary": "两人打了招呼"},
                    knowledge=[
                        EventKnowledge(role_id=1, level="participant"),
                        EventKnowledge(role_id=2, level="observer"),
                    ],
                )
            ]
        ),
        chronicles=(
            chronicles
            if chronicles is not None
            else [
                RoleChronicleOutput(
                    role_id=1,
                    content="我向对方打了招呼。",
                    known_event_keys=["greeting"],
                ),
                RoleChronicleOutput(
                    role_id=2,
                    content="我看见对方向我打招呼。",
                    known_event_keys=["greeting"],
                ),
            ]
        ),
    )


def test_location_output_rejects_missing_role() -> None:
    output = _location_output(
        groups=[InteractionGroupOutput(group_id="solo", role_ids=[1])],
    )

    with pytest.raises(OutputBoundaryError, match="分组角色必须完整且唯一"):
        validate_location_simulation_output(
            output,
            expected_location_id="the_home",
            expected_role_ids={1, 2},
        )


@pytest.mark.parametrize(
    "groups",
    [
        [InteractionGroupOutput(group_id="all", role_ids=[1, 1, 2])],
        [
            InteractionGroupOutput(group_id="one", role_ids=[1]),
            InteractionGroupOutput(group_id="two", role_ids=[1, 2]),
        ],
        [
            InteractionGroupOutput(group_id="same", role_ids=[1]),
            InteractionGroupOutput(group_id="same", role_ids=[2]),
        ],
    ],
)
def test_location_output_rejects_duplicate_groups_or_roles(
    groups: list[InteractionGroupOutput],
) -> None:
    with pytest.raises(OutputBoundaryError):
        validate_location_simulation_output(
            _location_output(groups=groups),
            expected_location_id="the_home",
            expected_role_ids={1, 2},
        )


def test_location_output_rejects_cross_location_role() -> None:
    output = _location_output(
        groups=[InteractionGroupOutput(group_id="all", role_ids=[1, 2, 99])],
        chronicles=[
            RoleChronicleOutput(role_id=1, content="主角纪事", known_event_keys=[]),
            RoleChronicleOutput(role_id=2, content="同图纪事", known_event_keys=[]),
            RoleChronicleOutput(role_id=99, content="跨图纪事", known_event_keys=[]),
        ],
        events=[],
    )

    with pytest.raises(OutputBoundaryError, match="分组角色必须完整且唯一"):
        validate_location_simulation_output(
            output,
            expected_location_id="the_home",
            expected_role_ids={1, 2},
        )


def test_location_output_rejects_unknown_event_reference() -> None:
    output = _location_output(
        events=[],
        chronicles=[
            RoleChronicleOutput(role_id=1, content="主角纪事", known_event_keys=["missing"]),
            RoleChronicleOutput(role_id=2, content="NPC 纪事", known_event_keys=[]),
        ],
    )

    with pytest.raises(OutputBoundaryError, match="纪事引用了未知事件"):
        validate_location_simulation_output(
            output,
            expected_location_id="the_home",
            expected_role_ids={1, 2},
        )


def test_location_output_accepts_no_events_and_single_role_group() -> None:
    output = LocationSimulationOutput(
        location_id="the_school",
        groups=[InteractionGroupOutput(group_id="alone", role_ids=[7])],
        events=[],
        chronicles=[
            RoleChronicleOutput(
                role_id=7,
                content="我独自看了一眼空教室。",
                known_event_keys=[],
            )
        ],
    )

    assert (
        validate_location_simulation_output(
            output,
            expected_location_id="the_school",
            expected_role_ids={7},
        )
        is output
    )


def test_location_output_accepts_multiple_independent_groups() -> None:
    output = _location_output(
        groups=[
            InteractionGroupOutput(group_id="pair", role_ids=[1, 2]),
            InteractionGroupOutput(group_id="alone", role_ids=[3]),
        ],
        events=[],
        chronicles=[
            RoleChronicleOutput(role_id=1, content="角色一纪事", known_event_keys=[]),
            RoleChronicleOutput(role_id=2, content="角色二纪事", known_event_keys=[]),
            RoleChronicleOutput(role_id=3, content="角色三独处纪事", known_event_keys=[]),
        ],
    )

    assert (
        validate_location_simulation_output(
            output,
            expected_location_id="the_home",
            expected_role_ids={1, 2, 3},
        )
        is output
    )


def test_location_output_requires_knowledge_and_chronicles_to_agree() -> None:
    output = _location_output(
        chronicles=[
            RoleChronicleOutput(role_id=1, content="主角纪事", known_event_keys=[]),
            RoleChronicleOutput(role_id=2, content="NPC 纪事", known_event_keys=["greeting"]),
        ]
    )

    with pytest.raises(OutputBoundaryError, match="事件知识与角色纪事不一致"):
        validate_location_simulation_output(
            output,
            expected_location_id="the_home",
            expected_role_ids={1, 2},
        )


def _memory_output(
    *,
    source_event_id: str | None = None,
    memory_append: str = "记住了这次短暂的相遇",
) -> AttributeMemoryAnalysisOutput:
    return AttributeMemoryAnalysisOutput(
        location_id="the_home",
        roles=[
            RoleAttributeMemoryOutput(
                role_id=1,
                attribute_update_intents=[
                    AttributeUpdateIntent(
                        role_id=1,
                        attribute_key="mood",
                        operation="replace",
                        value="平静",
                        reason="角色本轮情绪趋于平静",
                        source_event_id=source_event_id,
                        expected_version=3,
                    )
                ],
                memory_append=memory_append,
            )
        ],
    )


def test_attribute_memory_output_accepts_update_without_objective_event() -> None:
    output = _memory_output()

    assert (
        validate_attribute_memory_output(
            output,
            expected_location_id="the_home",
            expected_role_ids={1},
            valid_event_keys_by_role={1: set()},
            memory_max_chars=50,
        )
        is output
    )


@pytest.mark.parametrize("memory_append", ["前半__后半", "字" * 51])
def test_attribute_memory_output_rejects_separator_or_hard_max(
    memory_append: str,
) -> None:
    with pytest.raises(OutputBoundaryError, match="记忆摘要"):
        validate_attribute_memory_output(
            _memory_output(memory_append=memory_append),
            expected_location_id="the_home",
            expected_role_ids={1},
            valid_event_keys_by_role={1: set()},
            memory_max_chars=50,
        )


def test_attribute_memory_output_rejects_unknown_nonempty_event_key() -> None:
    with pytest.raises(OutputBoundaryError, match="未知事件"):
        validate_attribute_memory_output(
            _memory_output(source_event_id="missing"),
            expected_location_id="the_home",
            expected_role_ids={1},
            valid_event_keys_by_role={1: {"known"}},
            memory_max_chars=50,
        )


def test_attribute_memory_output_rejects_event_known_only_by_another_role() -> None:
    output = AttributeMemoryAnalysisOutput(
        location_id="the_home",
        roles=[
            RoleAttributeMemoryOutput(
                role_id=1,
                attribute_update_intents=[
                    AttributeUpdateIntent(
                        role_id=1,
                        attribute_key="mood",
                        operation="replace",
                        value="平静",
                        reason="错误引用了另一名角色的事件",
                        source_event_id="role-2-event",
                        expected_version=3,
                    )
                ],
                memory_append="角色一的记忆",
            ),
            RoleAttributeMemoryOutput(
                role_id=2,
                attribute_update_intents=[],
                memory_append="角色二的记忆",
            ),
        ],
    )

    with pytest.raises(OutputBoundaryError, match="未知事件"):
        validate_attribute_memory_output(
            output,
            expected_location_id="the_home",
            expected_role_ids={1, 2},
            valid_event_keys_by_role={1: set(), 2: {"role-2-event"}},
            memory_max_chars=50,
        )
