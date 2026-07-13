"""程序拥有的地图位置裁决规则。"""

from app.game.locations import (
    LOCATION_IDS,
    OFF_SCENE,
    WEEKDAYS,
    LocationCandidate,
    LocationRule,
    RolePresence,
    deterministic_rng,
    enforce_location_capacity,
    resolve_npc_location,
    weekday_for_day,
)

__all__ = [
    "LOCATION_IDS",
    "OFF_SCENE",
    "WEEKDAYS",
    "LocationCandidate",
    "LocationRule",
    "RolePresence",
    "deterministic_rng",
    "enforce_location_capacity",
    "resolve_npc_location",
    "weekday_for_day",
]
