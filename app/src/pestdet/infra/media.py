"""media — 视频文件的通用小工具（时长探测 / 文件名净化 / 体积格式化）。

只依赖 stdlib + cv2（延迟 import），供 api 层与 infra 层复用。
"""

import re
import unicodedata
from pathlib import Path

from pestdet.infra.paths import VIDEO_EXTS

# 文件名里允许保留的字符（其余一律替换成下划线）: 中英文、数字、点、横线、下划线、括号
_UNSAFE_RE = re.compile(r"[^\w.\-()（）\u4e00-\u9fff]+", re.UNICODE)


def safe_filename(name: str, default: str = "upload.mp4") -> str:
    """把用户上传的文件名净化成安全的纯文件名（去掉目录、控制字符、奇怪符号）。

    防止路径穿越（``../``、绝对路径、盘符）与非法字符；保留中文，便于用户辨认。
    """
    base = Path(name or "").name                      # 丢掉任何目录部分
    base = unicodedata.normalize("NFKC", base).strip()
    base = _UNSAFE_RE.sub("_", base).strip("._") or default
    return base[:120]                                 # 限制长度，避免超长文件名


def probe_duration(path: Path):
    """读视频时长（秒）；读取失败返回 None（不因单个坏文件拖垮整个列表）。"""
    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        cap.release()
        return round(frames / fps, 2) if fps > 0 else None
    except Exception:
        return None


def is_video(path: Path) -> bool:
    """按扩展名判断是否为受支持的视频。"""
    return path.suffix.lower() in VIDEO_EXTS


def size_mb(path: Path) -> float:
    """文件体积（MB，两位小数）。"""
    return round(path.stat().st_size / (1024 * 1024), 2)