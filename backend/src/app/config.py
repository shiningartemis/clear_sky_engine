"""应用配置与 Windows 可写目录约定。"""

import os
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict

from app import APP_VERSION


class AppPaths(BaseModel):
    """应用在 LocalAppData 中拥有的全部可写路径。"""

    model_config = ConfigDict(frozen=True)

    root: Path
    database_path: Path
    maps_dir: Path
    characters_dir: Path
    logs_dir: Path
    backups_dir: Path

    @classmethod
    def from_local_app_data(cls, local_app_data: Path | None = None) -> Self:
        if local_app_data is None:
            configured_path = os.environ.get("LOCALAPPDATA")
            if not configured_path:
                raise RuntimeError("LOCALAPPDATA is required on Windows.")
            local_app_data = Path(configured_path)

        root = local_app_data / "ClearSkyEngine"
        return cls(
            root=root,
            database_path=root / "data" / "app.db",
            maps_dir=root / "content" / "maps",
            characters_dir=root / "content" / "characters",
            logs_dir=root / "logs",
            backups_dir=root / "backups",
        )

    def create_directories(self) -> None:
        """只创建约定目录，不创建数据库或覆盖用户内容。"""

        for directory in (
            self.database_path.parent,
            self.maps_dir,
            self.characters_dir,
            self.logs_dir,
            self.backups_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


class AppConfig(BaseModel):
    """应用进程启动后保持不变的配置。"""

    model_config = ConfigDict(frozen=True)

    app_version: str = APP_VERSION
    paths: AppPaths

    @classmethod
    def for_local_app_data(cls, local_app_data: Path | None = None) -> Self:
        return cls(paths=AppPaths.from_local_app_data(local_app_data))
