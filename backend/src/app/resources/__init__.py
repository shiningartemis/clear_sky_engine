"""源码与 PyInstaller 运行时共享的只读资源定位。"""

import sys
from pathlib import Path


def resource_root(frozen_root: Path | None = None) -> Path:
    """冻结包只能从 `_MEIPASS` 读取随包资源，绝不回退到当前工作目录。"""

    if frozen_root is not None:
        return frozen_root

    bundle_root = getattr(sys, "_MEIPASS", None)
    if isinstance(bundle_root, str):
        return Path(bundle_root)
    return Path(__file__).parents[4]
