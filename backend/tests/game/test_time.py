"""成功轮次的纯时间推进规则测试。"""

import pytest

from app.game.time import advance_time


@pytest.mark.parametrize(
    ("day", "time_slot", "expected"),
    [
        (3, "morning", (3, "midday")),
        (3, "midday", (3, "evening")),
        (3, "evening", (3, "night")),
        (3, "night", (4, "morning")),
    ],
)
def test_advance_time_uses_four_stable_slots_and_rolls_over_after_night(
    day: int,
    time_slot: str,
    expected: tuple[int, str],
) -> None:
    assert advance_time(day, time_slot) == expected


def test_advance_time_rejects_invalid_day_and_slot() -> None:
    with pytest.raises(ValueError, match="day"):
        advance_time(0, "morning")
    with pytest.raises(ValueError, match="时间段"):
        advance_time(1, "dawn")
