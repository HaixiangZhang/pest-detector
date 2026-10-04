"""paths — 项目路径常量 / 文件类型 / 时间戳。

用法:
    from utils.paths import PROJECT_ROOT, VIDEO_EXTS, new_timestamp

本模块顶层只 import stdlib（无 torch/ultralytics/yaml），是 utils 包的地基：
config / registry（PROJECT_ROOT）、pipeline（PROJECT_ROOT / new_timestamp / VIDEO_EXTS）都依赖它。
"""

from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent   # utils/paths.py → 仓库根

# 支持的视频扩展名（pipeline 校验输入、sahi CLI 识别误传的视频）
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"}


def new_timestamp() -> str:
    """生成 YYYY-MM-DD_HHMMSS 时间戳（输出目录命名用）。"""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")
