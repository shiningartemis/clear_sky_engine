"""首次启动时准备可替换的默认地图。"""

import shutil
from pathlib import Path

from app.resources.catalog import MAP_EXTENSIONS, InvalidResourceNameError, safe_child


def ensure_default_maps(default_maps_dir: Path, maps_dir: Path) -> None:
    """只补齐缺失文件主体；任何现有 JPG 或 PNG 都代表用户已接管该地图。"""

    resolved_defaults = default_maps_dir.resolve()
    maps_dir.mkdir(parents=True, exist_ok=True)
    resolved_target = maps_dir.resolve()
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
        # copy2 只在目标不存在时执行；启动升级绝不能覆盖用户替换的同名资源。
        shutil.copy2(source, destination)
