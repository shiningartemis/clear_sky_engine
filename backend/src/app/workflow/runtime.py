"""仅在进程内保存的轮次运行状态。"""

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from uuid import uuid4

from app.workflow.context import (
    AttributeMemoryContext,
    LocationSimulationContext,
    TurnContextSnapshot,
)
from app.workflow.schemas import AttributeMemoryAnalysisOutput, LocationSimulationOutput


class NodeKey(StrEnum):
    """固定节点标识不复用配置层的 TaskKey，避免运行进度耦合配置存储。"""

    LOCATION_SIMULATION = "location_simulation"
    ATTRIBUTE_MEMORY_ANALYSIS = "attribute_memory_analysis"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class MapChainRun:
    """一张地图的两个串联节点；失败后保留状态，绝不保留可被误结算的输出。"""

    location: LocationSimulationContext
    status: RunStatus = RunStatus.PENDING
    location_output: LocationSimulationOutput | None = None
    attribute_context: AttributeMemoryContext | None = None
    attribute_output: AttributeMemoryAnalysisOutput | None = None
    location_attempt: int | None = None
    attribute_attempt: int | None = None
    failed_node: NodeKey | None = None
    safe_error: str | None = None

    @property
    def location_id(self) -> str:
        return self.location.location_id

    def discard_outputs(self) -> None:
        """任何地图链失败都会使整轮失效，防止部分 AI 结果越过原子结算边界。"""

        self.location_output = None
        self.attribute_context = None
        self.attribute_output = None


@dataclass(frozen=True)
class TurnRunSummary:
    """状态查询只保留这一份安全摘要，禁止把地图输入或 AI 输出留在内存历史中。"""

    run_id: str
    status: RunStatus
    turn_id: int | None
    error: str | None


@dataclass(frozen=True)
class ProgressEvent:
    """供后续 NDJSON 层投影的安全进度，不携带 Prompt、响应或原始异常。"""

    run_id: str
    kind: str
    location_id: str | None
    node: NodeKey | None
    attempt: int | None
    max_attempts: int
    retrying: bool
    completed_maps: int
    total_maps: int
    elapsed_ms: int
    error: str | None = None


@dataclass
class TurnRun:
    """一轮的冻结地图输入与临时输出，生命周期仅限当前 Python 进程。"""

    run_id: str
    map_runs: dict[str, MapChainRun]
    snapshot: TurnContextSnapshot | None = None
    memory_max_chars: int | None = None
    status: RunStatus = RunStatus.PENDING
    events: list[ProgressEvent] = field(default_factory=lambda: list[ProgressEvent]())
    error: str | None = None
    started_at: float | None = None
    terminal_emitted: bool = False

    @classmethod
    def create(
        cls,
        source: TurnContextSnapshot | tuple[LocationSimulationContext, ...],
        *,
        memory_max_chars: int | None = None,
    ) -> TurnRun:
        if isinstance(source, TurnContextSnapshot):
            snapshot: TurnContextSnapshot | None = source
            locations = source.locations
        else:
            snapshot = None
            locations = source
        if len({location.location_id for location in locations}) != len(locations):
            raise ValueError("冻结地图不能重复")
        return cls(
            run_id=str(uuid4()),
            map_runs={
                location.location_id: MapChainRun(location=location) for location in locations
            },
            snapshot=snapshot,
            memory_max_chars=memory_max_chars,
        )

    @property
    def total_maps(self) -> int:
        return len(self.map_runs)

    @property
    def completed_maps(self) -> int:
        return sum(item.status is RunStatus.SUCCEEDED for item in self.map_runs.values())

    def start(self, now: float | None = None) -> None:
        if self.status is not RunStatus.PENDING:
            raise RuntimeError("轮次只能从等待状态启动一次")
        self.status = RunStatus.RUNNING
        self.started_at = monotonic() if now is None else now

    def fail(self, error: str) -> None:
        if self.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            return
        # AI 节点成功只是待结算状态；结算拒绝时必须撤销成功并丢弃全部输出。
        self.status = RunStatus.FAILED
        self.error = error
        self._discard_all_outputs()

    def cancel(self) -> None:
        if self.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            return
        # 结算前收到取消时，已完成的 AI 结果仍不可被提交。
        self.status = RunStatus.CANCELLED
        self._discard_all_outputs()

    def succeed(self) -> None:
        if self.status is not RunStatus.RUNNING:
            raise RuntimeError("只有运行中的轮次可以成功")
        self.status = RunStatus.SUCCEEDED

    def _discard_all_outputs(self) -> None:
        for map_run in self.map_runs.values():
            map_run.discard_outputs()

    def clear_payload(self) -> None:
        """结算完成或失败后立即释放冻结上下文和 AI 输出，防止内存历史无限增长。"""

        self._discard_all_outputs()
        self.map_runs.clear()
        self.events.clear()
        self.snapshot = None
        self.memory_max_chars = None

    def summary(self, turn_id: int | None = None) -> TurnRunSummary:
        return TurnRunSummary(
            run_id=self.run_id,
            status=self.status,
            turn_id=turn_id,
            error=self.error,
        )


_TERMINAL_STATUSES = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED})


def terminal_kind(status: RunStatus) -> str:
    """终态事件名称是后续流协议契约，非终态输入是程序错误。"""

    match status:
        case RunStatus.SUCCEEDED:
            return "run_succeeded"
        case RunStatus.FAILED:
            return "run_failed"
        case RunStatus.CANCELLED:
            return "run_cancelled"
        case _:
            raise ValueError("非终态没有终态事件名称")
