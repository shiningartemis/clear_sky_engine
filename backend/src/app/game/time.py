"""成功轮次唯一使用的时间推进纯函数。"""

from typing import Literal

TimeSlot = Literal["morning", "midday", "evening", "night"]

TIME_SLOT_ORDER: tuple[TimeSlot, ...] = (
    "morning",
    "midday",
    "evening",
    "night",
)


def advance_time(day: int, time_slot: str) -> tuple[int, TimeSlot]:
    """只在原子结算成功路径推进一格；夜晚结束后进入次日早晨。"""

    if day < 1:
        raise ValueError("day 必须从 1 开始")
    if time_slot not in TIME_SLOT_ORDER:
        raise ValueError("时间段无效")
    index = TIME_SLOT_ORDER.index(time_slot)
    if index == len(TIME_SLOT_ORDER) - 1:
        return day + 1, "morning"
    return day, TIME_SLOT_ORDER[index + 1]
