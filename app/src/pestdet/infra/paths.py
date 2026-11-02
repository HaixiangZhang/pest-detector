"""paths — 项目路径常量 / 文件类型 / 时间戳。

工作根解析顺序:
    1. 环境变量 ``PESTDET_HOME``（部署到服务器时指向数据根目录）
    2. 默认: 本文件向上 3 级 → 仓库根（``src/pestdet/infra/paths.py`` → 仓库根）

本模块顶层只 import stdlib（无 cv2/torch/yaml），是 infra 层的地基。
"""

import os
from datetime import datetime
from pathlib import Path


def _resolve_root() -> Path:
    env = os.environ.get("PESTDET_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


# 工作根（configs.yaml / runs/ / videos/ 都相对它解析）
PROJECT_ROOT = _resolve_root()

# 用户数据根: 存放用户上传的源视频等"用户产生、需要跨会话保留"的内容。
# 与 runs/（任务产物，按次生成）分开，便于部署时单独挂盘 / 备份。
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"

# 支持的视频扩展名（pipeline 校验输入、sahi CLI 识别误传的视频）
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"}


def new_timestamp() -> str:
    """生成 YYYY-MM-DD_HHMMSS 时间戳（输出目录命名用）。"""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")