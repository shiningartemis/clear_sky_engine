"""无 I/O 的星期、NPC 位置与地点容量裁决。"""

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

LOCATION_IDS = (
    "the_home",
    "the_dungeon",
    "the_mall",
    "the_guild",
    "the_hotel",
    "the_school",
)
OFF_SCENE = "off_scene"
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

RoleKind = Literal["player", "npc"]
LocationMode = Literal["fixed", "random"]


@dataclass(frozen=True)
class LocationCandidate:
    location_id: str
    weight: int


@dataclass(frozen=True)
class LocationRule:
    weekday_mask: int
    time_slot: str
    mode: str
    priority: int
    enabled: bool
    candidates: tuple[LocationCandidate, ...]


@dataclass(frozen=True)
class RolePresence:
    role_id: int
    kind: RoleKind
    location_id: str
    enabled: bool = True


def weekday_for_day(day: int) -> str:
    """星期只由从 1 开始的 day 推导，不形成第二个可写状态。"""

    if day < 1:
        raise ValueError("day 必须从 1 开始")
    return WEEKDAYS[(day - 1) % len(WEEKDAYS)]


def deterministic_rng(*, world_id: int, day: int, time_slot: str, role_id: int) -> random.Random:
    """稳定摘要隔离 Python 随机 hash，保证恢复和重试得到同一位置。"""

    digest = hashlib.sha256(f"{world_id}:{day}:{time_slot}:{role_id}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _weekday_bit(day: int) -> int:
    return 1 << ((day - 1) % len(WEEKDAYS))


def resolve_npc_location(
    rules: Sequence[LocationRule],
    *,
    world_id: int,
    day: int,
    time_slot: str,
    role_id: int,
) -> str:
    """选择最高优先级匹配规则；没有规则时 NPC 处于受控离屏状态。"""

    weekday_for_day(day)
    matching = [
        rule
        for rule in rules
        if rule.enabled
        and rule.time_slot == time_slot
        and rule.weekday_mask & _weekday_bit(day)
        and rule.candidates
    ]
    if not matching:
        return OFF_SCENE
    selected = max(matching, key=lambda item: item.priority)
    if selected.mode == "fixed":
        return selected.candidates[0].location_id

    candidates = [item.location_id for item in selected.candidates]
    weights = [item.weight for item in selected.candidates]
    rng = deterministic_rng(
        world_id=world_id,
        day=day,
        time_slot=time_slot,
        role_id=role_id,
    )
    return rng.choices(candidates, weights=weights, k=1)[0]


def enforce_location_capacity(
    presences: Sequence[RolePresence],
) -> tuple[RolePresence, ...]:
    """每地点主角优先且最多六人；启用的溢出 NPC 仍作为离屏事实返回。"""

    enabled = [item for item in presences if item.enabled]
    location_order: list[str] = []
    # 先按主角输入顺序建立地点顺序，避免更早出现的 NPC 改变主角相对顺序。
    ordered_for_locations = [item for item in enabled if item.kind == "player"] + enabled
    for item in ordered_for_locations:
        if item.location_id != OFF_SCENE and item.location_id not in location_order:
            location_order.append(item.location_id)

    visible: list[RolePresence] = []
    overflow: list[RolePresence] = []
    for location_id in location_order:
        at_location = [item for item in enabled if item.location_id == location_id]
        players = [item for item in at_location if item.kind == "player"]
        npcs = sorted(
            (item for item in at_location if item.kind == "npc"),
            key=lambda item: item.role_id,
        )
        remaining = max(0, 6 - len(players))
        visible.extend(players)
        visible.extend(npcs[:remaining])
        overflow.extend(replace(item, location_id=OFF_SCENE) for item in npcs[remaining:])

    already_off_scene = [item for item in enabled if item.location_id == OFF_SCENE]
    return tuple((*visible, *overflow, *already_off_scene))
