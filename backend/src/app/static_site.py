"""生产前端静态文件与 SPA fallback。"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from starlette.responses import FileResponse, Response


def configure_static_site(app: FastAPI, static_dir: Path) -> None:
    """静态路径必须留在构建目录内，未知 API 不得被 index.html 掩盖。"""

    root = static_dir.resolve()
    index_path = root / "index.html"
    if not index_path.is_file():
        raise RuntimeError(f"Static index is missing: {index_path}")

    def _serve_static(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = (root / path).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_path)

    app.add_api_route(
        "/{path:path}",
        _serve_static,
        methods=["GET"],
        include_in_schema=False,
    )
