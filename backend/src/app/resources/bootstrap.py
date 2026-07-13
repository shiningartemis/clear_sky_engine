"""首次启动时准备可替换的默认地图。"""

import shutil
from pathlib import Path

from app.resources.catalog import (
    MAP_EXTENSIONS,
    InvalidResourceNameError,
    safe_child,
    safe_content_root,
)


def _copy_exclusive(source: Path, destination: Path) -> None:
    """目标竞态出现时保留先到达的用户文件。"""

    try:
        # xb 把“目标仍不存在”与创建合并为一个原子文件操作，竞态失败时保留用户内容。
        with source.open("rb") as source_file, destination.open("xb") as destination_file:
            shutil.copyfileobj(source_file, destination_file)
    except FileExistsError:
        return


def ensure_default_maps(default_maps_dir: Path, maps_dir: Path) -> None:
    """只补齐缺失文件主体；任何现有 JPG 或 PNG 都代表用户已接管该地图。"""

    resolved_defaults = default_maps_dir.resolve()
    target = safe_content_root(maps_dir)
    target.mkdir(parents=True, exist_ok=True)
    resolved_target = safe_content_root(target)
    copied_stems: set[str] = set()
    for source_entry in sorted(resolved_defaults.iterdir(), key=lambda path: path.name):
        extension = source_entry.suffix.lower()
        if extension not in MAP_EXTENSIONS or source_entry.stem in copied_stems:
            continue
        source = safe_child(resolved_defaults, source_entry.name)
        if not source.is_file():
            raise InvalidResourceNameError(f"默认地图不是普通文件: {source_entry.name!r}")
        copied_stems.add(source_entry.stem)
        if any(
            (resolved_target / f"{source_entry.stem}{candidate}").exists()
            for candidate in MAP_EXTENSIONS
        ):
            continue
        destination = safe_child(resolved_target, source_entry.name)
        _copy_exclusive(source, destination)
