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
OFFLINE = "offline"
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
    """选择最高优先级匹配规则；没有规则时 NPC 处于显式离线状态。"""

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
        return OFFLINE
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


def allocate_role_presences(
    presences: Sequence[RolePresence],
    *,
    world_id: int,
    day: int,
    time_slot: str,
) -> tuple[RolePresence, ...]:
    """按主地点、二次缓存和永久主角预留位返回全部启用角色的非空位置事实。"""

    weekday_for_day(day)
    enabled = [item for item in presences if item.enabled]
    players = sorted(
        (item for item in enabled if item.kind == "player"),
        key=lambda item: item.role_id,
    )
    npcs = sorted(
        (item for item in enabled if item.kind == "npc"),
        key=lambda item: item.role_id,
    )
    allocated: dict[int, RolePresence] = {}
    overflow: list[RolePresence] = []

    for location_id in LOCATION_IDS:
        at_location = [item for item in npcs if item.location_id == location_id]
        for item in at_location[:5]:
            allocated[item.role_id] = item
        overflow.extend(at_location[5:])

    # offline 和未知地点都不是可补位的主地点，避免后续创建无效地图链。
    for item in npcs:
        if item.location_id not in LOCATION_IDS:
            allocated[item.role_id] = replace(item, location_id=OFFLINE)

    # 先按角色 ID 建立稳定输入，再用固定摘要种子打乱，隔离调用方输入顺序。
    overflow.sort(key=lambda item: item.role_id)
    digest = hashlib.sha256(f"{world_id}:{day}:{time_slot}:overflow".encode()).digest()
    random.Random(int.from_bytes(digest[:8], "big")).shuffle(overflow)

    overflow_index = 0
    for location_id in LOCATION_IDS:
        occupied = sum(item.location_id == location_id for item in allocated.values())
        for _ in range(5 - occupied):
            if overflow_index >= len(overflow):
                break
            item = overflow[overflow_index]
            allocated[item.role_id] = replace(item, location_id=location_id)
            overflow_index += 1

    for item in overflow[overflow_index:]:
        allocated[item.role_id] = replace(item, location_id=OFFLINE)

    return tuple((*players, *(allocated[item.role_id] for item in npcs)))
