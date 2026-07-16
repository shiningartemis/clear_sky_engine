import hashlib
import random
from itertools import chain

import pytest

from app.game import locations
from app.game.locations import (
    LocationCandidate,
    LocationRule,
    RolePresence,
    resolve_npc_location,
    weekday_for_day,
)


def _rule(
    *candidates: tuple[str, int],
    weekday_mask: int = 1,
    time_slot: str = "morning",
    mode: str = "random",
    priority: int = 0,
    enabled: bool = True,
) -> LocationRule:
    return LocationRule(
        weekday_mask=weekday_mask,
        time_slot=time_slot,
        mode=mode,
        priority=priority,
        enabled=enabled,
        candidates=tuple(
            LocationCandidate(location_id=location_id, weight=weight)
            for location_id, weight in candidates
        ),
    )


def test_weekday_is_derived_from_one_based_day() -> None:
    assert weekday_for_day(1) == "monday"
    assert weekday_for_day(8) == "monday"


def test_weekday_rejects_non_positive_day() -> None:
    try:
        weekday_for_day(0)
    except ValueError as error:
        assert str(error) == "day 必须从 1 开始"
    else:
        raise AssertionError("非正数 day 必须被拒绝")


def _allocate(
    presences: list[RolePresence],
    *,
    world_id: int = 7,
    day: int = 1,
    time_slot: str = "morning",
) -> tuple[RolePresence, ...]:
    return locations.allocate_role_presences(
        presences,
        world_id=world_id,
        day=day,
        time_slot=time_slot,
    )


def _player(location_id: str = "the_home") -> RolePresence:
    return RolePresence(role_id=99, kind="player", location_id=location_id)


def _npcs(
    location_id: str,
    role_ids: range | tuple[int, ...],
) -> list[RolePresence]:
    return [
        RolePresence(role_id=role_id, kind="npc", location_id=location_id) for role_id in role_ids
    ]


def _npc_locations(presences: tuple[RolePresence, ...]) -> dict[int, str]:
    return {item.role_id: item.location_id for item in presences if item.kind == "npc"}


@pytest.mark.parametrize(
    ("presences", "expected_locations"),
    [
        (
            [_player(), *_npcs("the_home", range(1, 6))],
            {role_id: "the_home" for role_id in range(1, 6)},
        ),
        (
            [
                _player(),
                *_npcs("the_home", (1, 2)),
                *_npcs("the_school", (3, 4, 5)),
            ],
            {
                1: "the_home",
                2: "the_home",
                3: "the_school",
                4: "the_school",
                5: "the_school",
            },
        ),
        ([_player()], {}),
        ([], {}),
    ],
    ids=["exactly-five", "empty-overflow", "no-npcs", "no-roles"],
)
def test_allocation_keeps_under_capacity_primary_locations(
    presences: list[RolePresence],
    expected_locations: dict[int, str],
) -> None:
    result = _allocate(presences)

    assert _npc_locations(result) == expected_locations
    assert all(isinstance(item.location_id, str) and item.location_id for item in result)


def test_single_location_overflow_uses_next_location_and_reserves_player_slot() -> None:
    result = _allocate([_player("the_school"), *_npcs("the_home", range(1, 8))])

    assert sum(item.kind == "npc" and item.location_id == "the_home" for item in result) == 5
    assert {
        item.location_id for item in result if item.kind == "npc" and item.role_id in {6, 7}
    } == {"the_dungeon"}
    assert len([item for item in result if item.location_id == "the_school"]) == 1


def test_overflow_backfills_partially_occupied_locations_in_manifest_order() -> None:
    result = _allocate(
        [
            _player(),
            *_npcs("the_home", range(1, 8)),
            *_npcs("the_dungeon", (8, 9, 10)),
        ]
    )

    assert sum(item.kind == "npc" and item.location_id == "the_home" for item in result) == 5
    assert sum(item.kind == "npc" and item.location_id == "the_dungeon" for item in result) == 5
    assert all(item.location_id != "the_mall" for item in result)


def test_full_locations_leave_shuffled_overflow_explicitly_offline() -> None:
    primary = list(
        chain.from_iterable(
            _npcs(location_id, range(index * 6 + 1, index * 6 + 7))
            for index, location_id in enumerate(locations.LOCATION_IDS)
        )
    )

    result = _allocate([_player(), *primary])

    for location_id in locations.LOCATION_IDS:
        assert sum(item.kind == "npc" and item.location_id == location_id for item in result) == 5
    assert sum(item.location_id == locations.OFFLINE for item in result) == 6


def test_offline_and_disabled_npcs_never_enter_overflow_cache() -> None:
    result = _allocate(
        [
            _player(),
            RolePresence(role_id=1, kind="npc", location_id=locations.OFFLINE),
            RolePresence(role_id=2, kind="npc", location_id="the_home", enabled=False),
            *_npcs("the_home", range(3, 9)),
        ]
    )

    assert _npc_locations(result)[1] == locations.OFFLINE
    assert 2 not in _npc_locations(result)
    assert sum(item.kind == "npc" and item.location_id == "the_dungeon" for item in result) == 1


def test_allocation_sorts_before_sha256_shuffle_and_is_input_order_independent() -> None:
    presences = [_player(), *_npcs("the_home", range(1, 13))]
    expected_overflow = list(range(6, 13))
    digest = hashlib.sha256(b"7:1:morning:overflow").digest()
    random.Random(int.from_bytes(digest[:8], "big")).shuffle(expected_overflow)

    first = _allocate(presences)
    repeated = _allocate(presences)
    reversed_input = _allocate(list(reversed(presences)))

    assert first == repeated == reversed_input
    assert [item.role_id for item in first] == [99, *range(1, 13)]
    assert {item.role_id for item in first if item.location_id == "the_dungeon"} == set(
        expected_overflow[:5]
    )
    assert {item.role_id for item in first if item.location_id == "the_mall"} == set(
        expected_overflow[5:]
    )


def test_different_time_seed_changes_overflow_assignment() -> None:
    presences = [_player(), *_npcs("the_home", range(1, 13))]

    morning = _npc_locations(_allocate(presences, day=1, time_slot="morning"))
    evening = _npc_locations(_allocate(presences, day=1, time_slot="evening"))

    assert morning != evening


def test_player_movement_does_not_reallocate_npcs_in_same_snapshot() -> None:
    npcs = _npcs("the_home", range(1, 13))

    at_home = _npc_locations(_allocate([_player("the_home"), *npcs]))
    at_school = _npc_locations(_allocate([_player("the_school"), *npcs]))

    assert at_home == at_school


def test_every_map_keeps_at_most_five_npcs_even_without_player_on_that_map() -> None:
    result = _allocate([_player("the_school"), *_npcs("the_home", range(1, 31))])

    assert all(
        sum(item.kind == "npc" and item.location_id == location_id for item in result) <= 5
        for location_id in locations.LOCATION_IDS
    )


def test_random_location_is_repeatable_for_same_world_time_and_role() -> None:
    rule = _rule(("the_home", 1), ("the_school", 3))

    first = resolve_npc_location((rule,), world_id=2, day=1, time_slot="morning", role_id=8)
    second = resolve_npc_location((rule,), world_id=2, day=1, time_slot="morning", role_id=8)

    assert first == second


def test_highest_priority_matching_rule_wins() -> None:
    rules = (
        _rule(("the_home", 1), mode="fixed", priority=2),
        _rule(("the_school", 1), mode="fixed", priority=5),
        _rule(("the_mall", 1), mode="fixed", priority=9, time_slot="night"),
    )

    assert (
        resolve_npc_location(rules, world_id=2, day=1, time_slot="morning", role_id=8)
        == "the_school"
    )


def test_no_matching_rule_returns_offline() -> None:
    rules = (_rule(("the_home", 1), weekday_mask=2),)

    assert (
        resolve_npc_location(rules, world_id=2, day=1, time_slot="morning", role_id=8)
        == locations.OFFLINE
    )
