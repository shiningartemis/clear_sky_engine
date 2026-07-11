"""Provider 与模型目录的同步 SQLAlchemy Store。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import AiModel, AiProvider


class AiSettingsStore:
    """只封装持久化查询，不拥有提交或业务错误转换。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_providers(self) -> list[AiProvider]:
        return list(self._session.scalars(select(AiProvider).order_by(AiProvider.id)))

    def get_provider(self, provider_id: int) -> AiProvider | None:
        return self._session.get(AiProvider, provider_id)

    def add_provider(self, provider: AiProvider) -> None:
        self._session.add(provider)

    def delete_provider(self, provider: AiProvider) -> None:
        self._session.delete(provider)

    def list_models(self, provider_id: int | None) -> list[AiModel]:
        statement = select(AiModel).order_by(AiModel.id)
        if provider_id is not None:
            statement = statement.where(AiModel.provider_id == provider_id)
        return list(self._session.scalars(statement))

    def get_model(self, model_id: int) -> AiModel | None:
        return self._session.get(AiModel, model_id)

    def add_model(self, model: AiModel) -> None:
        self._session.add(model)

    def delete_model(self, model: AiModel) -> None:
        self._session.delete(model)
