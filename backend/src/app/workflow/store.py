"""固定 AI 任务配置的同步 SQLAlchemy Store。"""

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.workflow.models import AiTaskSetting
from app.workflow.settings import TaskKey


class TaskSettingsStore:
    """只拥有两条固定配置的查询，不提交事务或解释业务语义。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_settings(self) -> list[AiTaskSetting]:
        stable_order = case(
            (AiTaskSetting.task_key == TaskKey.LOCATION_SIMULATION, 0),
            (AiTaskSetting.task_key == TaskKey.ATTRIBUTE_MEMORY_ANALYSIS, 1),
            else_=2,
        )
        return list(self._session.scalars(select(AiTaskSetting).order_by(stable_order)))

    def get_setting(self, task_key: TaskKey) -> AiTaskSetting | None:
        return self._session.scalar(
            select(AiTaskSetting).where(AiTaskSetting.task_key == task_key.value)
        )
