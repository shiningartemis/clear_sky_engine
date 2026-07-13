from app.game.locations import (
    OFF_SCENE,
    LocationCandidate,
    LocationRule,
    RolePresence,
    enforce_location_capacity,
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


def test_location_capacity_keeps_player_and_lowest_five_role_ids() -> None:
    presences = [RolePresence(role_id=99, kind="player", location_id="the_home")]
    presences += [
        RolePresence(role_id=role_id, kind="npc", location_id="the_home") for role_id in range(1, 8)
    ]

    result = enforce_location_capacity(presences)

    assert [item.role_id for item in result if item.location_id == "the_home"] == [
        99,
        1,
        2,
        3,
        4,
        5,
    ]
    assert [item.role_id for item in result if item.location_id == OFF_SCENE] == [6, 7]


def test_capacity_excludes_disabled_npcs_and_keeps_enabled_overflow_off_scene() -> None:
    presences = [RolePresence(role_id=20, kind="player", location_id="the_school")]
    presences += [
        RolePresence(
            role_id=role_id,
            kind="npc",
            location_id="the_school",
            enabled=role_id != 2,
        )
        for role_id in range(1, 8)
    ]

    result = enforce_location_capacity(presences)

    assert all(item.role_id != 2 for item in result)
    assert [item.role_id for item in result if item.location_id == "the_school"] == [
        20,
        1,
        3,
        4,
        5,
        6,
    ]
    assert [item.role_id for item in result if item.location_id == OFF_SCENE] == [7]


def test_capacity_processes_locations_independently_without_reordering_players() -> None:
    presences = [
        RolePresence(role_id=80, kind="player", location_id="the_home"),
        RolePresence(role_id=70, kind="player", location_id="the_school"),
        RolePresence(role_id=3, kind="npc", location_id="the_school"),
        RolePresence(role_id=2, kind="npc", location_id="the_home"),
        RolePresence(role_id=1, kind="npc", location_id="the_home"),
    ]

    result = enforce_location_capacity(presences)

    assert [item.role_id for item in result] == [80, 1, 2, 70, 3]


def test_capacity_preserves_player_order_when_an_npc_mentions_later_location_first() -> None:
    presences = [
        RolePresence(role_id=3, kind="npc", location_id="the_school"),
        RolePresence(role_id=80, kind="player", location_id="the_home"),
        RolePresence(role_id=70, kind="player", location_id="the_school"),
    ]

    result = enforce_location_capacity(presences)

    assert [item.role_id for item in result if item.kind == "player"] == [80, 70]


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


def test_no_matching_rule_returns_off_scene() -> None:
    rules = (_rule(("the_home", 1), weekday_mask=2),)

    assert (
        resolve_npc_location(rules, world_id=2, day=1, time_slot="morning", role_id=8) == OFF_SCENE
    )
