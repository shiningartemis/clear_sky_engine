"""程序拥有的地图位置裁决规则。"""

from app.game.locations import (
    LOCATION_IDS,
    OFFLINE,
    WEEKDAYS,
    LocationCandidate,
    LocationRule,
    RolePresence,
    allocate_role_presences,
    deterministic_rng,
    resolve_npc_location,
    weekday_for_day,
)

__all__ = [
    "LOCATION_IDS",
    "OFFLINE",
    "WEEKDAYS",
    "LocationCandidate",
    "LocationRule",
    "RolePresence",
    "allocate_role_presences",
    "deterministic_rng",
    "resolve_npc_location",
    "weekday_for_day",
]
