"""成功轮次及角色隔离历史的同步 SQLAlchemy 查询。"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.types import JsonValue
from app.story.models import StateChange, Turn, TurnEvent, TurnEventParticipant, TurnStory

KnowledgeLevel = Literal["participant", "observer", "told", "public"]


class StoryDataError(ValueError):
    """持久化故事数据违反已发布约束，不能进入后续角色上下文。"""


@dataclass(frozen=True)
class KnownEventRecord:
    event_id: int
    event_type: str
    fact: dict[str, JsonValue]
    knowledge_level: KnowledgeLevel
    perspective_notes: str


@dataclass(frozen=True)
class RecentRoleTurnRecord:
    turn_id: int
    day: int
    time_slot: str
    own_chronicle: str
    known_events: tuple[KnownEventRecord, ...]


def _knowledge_level(value: str) -> KnowledgeLevel:
    match value:
        case "participant":
            return "participant"
        case "observer":
            return "observer"
        case "told":
            return "told"
        case "public":
            return "public"
        case _:
            raise StoryDataError("事件知识级别无效")


class StoryStore:
    """历史查询从 SQL 层只选择目标角色纪事，避免调用方误拿全局纪事。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_turn(self, turn: Turn) -> None:
        self._session.add(turn)
        self._session.flush()

    def add_story(self, story: TurnStory) -> None:
        self._session.add(story)
        self._session.flush()

    def add_event(self, event: TurnEvent) -> None:
        self._session.add(event)
        self._session.flush()

    def add_event_participant(self, participant: TurnEventParticipant) -> None:
        self._session.add(participant)

    def add_state_change(self, change: StateChange) -> None:
        self._session.add(change)

    def list_turns(self, *, world_id: int, branch_id: int) -> tuple[Turn, ...]:
        """完整历史按最新轮次优先返回，不分页也不裁剪旧轮次。"""

        statement = (
            select(Turn)
            .where(Turn.world_id == world_id, Turn.branch_id == branch_id)
            .order_by(Turn.id.desc())
        )
        return tuple(self._session.scalars(statement))

    def list_turn_stories(self, turn_id: int) -> tuple[TurnStory, ...]:
        return tuple(
            self._session.scalars(
                select(TurnStory)
                .where(TurnStory.turn_id == turn_id)
                .order_by(TurnStory.sort_order, TurnStory.role_id)
            )
        )

    def list_turn_events(self, turn_id: int) -> tuple[TurnEvent, ...]:
        return tuple(
            self._session.scalars(
                select(TurnEvent).where(TurnEvent.turn_id == turn_id).order_by(TurnEvent.id)
            )
        )

    def list_turn_state_changes(self, turn_id: int) -> tuple[StateChange, ...]:
        return tuple(
            self._session.scalars(
                select(StateChange).where(StateChange.turn_id == turn_id).order_by(StateChange.id)
            )
        )

    def list_recent_role_turns(
        self,
        *,
        world_id: int,
        branch_id: int,
        role_id: int,
        limit: int = 5,
    ) -> tuple[RecentRoleTurnRecord, ...]:
        """以 turn_story 是否存在定义有效轮次，offline 自然不会占用名额。"""

        if limit < 1:
            return ()
        statement = (
            select(Turn, TurnStory)
            .join(TurnStory, TurnStory.turn_id == Turn.id)
            .where(
                Turn.world_id == world_id,
                Turn.branch_id == branch_id,
                TurnStory.role_id == role_id,
            )
            .order_by(Turn.id.desc())
            .limit(limit)
        )
        descending_rows = list(self._session.execute(statement).tuples())
        turn_ids = [turn.id for turn, _story in descending_rows]
        events_by_turn: dict[int, list[KnownEventRecord]] = {turn_id: [] for turn_id in turn_ids}
        if turn_ids:
            event_statement = (
                select(TurnEvent, TurnEventParticipant)
                .join(
                    TurnEventParticipant,
                    TurnEventParticipant.event_id == TurnEvent.id,
                )
                .where(
                    TurnEvent.turn_id.in_(turn_ids),
                    TurnEventParticipant.role_id == role_id,
                )
                .order_by(TurnEvent.turn_id, TurnEvent.id)
            )
            for event, participant in self._session.execute(event_statement).tuples():
                events_by_turn[event.turn_id].append(
                    KnownEventRecord(
                        event_id=event.id,
                        event_type=event.event_type,
                        fact=event.fact_json,
                        knowledge_level=_knowledge_level(participant.knowledge_level),
                        perspective_notes=participant.perspective_notes,
                    )
                )

        # Prompt 采用自然时间顺序，最近一轮稳定放在最后。
        return tuple(
            RecentRoleTurnRecord(
                turn_id=turn.id,
                day=turn.day,
                time_slot=turn.time_slot,
                own_chronicle=story.content,
                known_events=tuple(events_by_turn[turn.id]),
            )
            for turn, story in reversed(descending_rows)
        )
