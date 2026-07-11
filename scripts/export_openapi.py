"""在隔离临时目录中导出后端 OpenAPI，避免生成过程触碰真实用户数据。"""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import AppConfig
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    with TemporaryDirectory(prefix="clear-sky-openapi-") as temporary_directory:
        app = create_app(AppConfig.for_local_app_data(Path(temporary_directory)))
        schema = app.openapi()

    arguments.output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
