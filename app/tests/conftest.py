"""pytest 公共夹具：真实配置、临时输出配置、假检测器。

所有测试都在 CPU 上跑，不加载模型、不碰 GPU。
"""

import copy
import sys
from pathlib import Path

import numpy as np
import pytest

# 未 pip install 时也能直接 pytest（与根 cli.py 的兜底一致）
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pestdet.config import load_config  # noqa: E402


@pytest.fixture(scope="session")
def base_config():
    """项目根 configs.yaml 校验后的完整配置（只读，勿原地改）。"""
    return load_config()


@pytest.fixture
def tmp_config(base_config, tmp_path):
    """真实配置基础上关掉 JSON/遮罩/快照、指向临时目录，供轻量端到端测试用。

    标注视频无法关闭（始终输出），故测试需容忍"编码器不可用 → video=None"。
    """
    cfg = copy.deepcopy(base_config)
    cfg["output_root"] = str(tmp_path / "runs")
    cfg["save_json"] = False
    cfg["mask"]["enabled"] = False
    cfg["snapshots"]["enabled"] = False
    return cfg


class FakeDetector:
    """按脚本逐帧吐检测框的假检测器（不加载模型、不用 GPU）。

    Args:
        per_frame: 每帧一行，形如 ``[[x1, y1, x2, y2, score], ...]``；
                   超出脚本长度的帧返回空检测。
    """

    def __init__(self, per_frame):
        self.per_frame = [np.asarray(f, dtype=float).reshape(-1, 5) for f in per_frame]
        self.calls = 0

    def detect(self, frame, valid_mask=None):
        i = self.calls
        self.calls += 1
        rows = self.per_frame[i] if i < len(self.per_frame) else np.zeros((0, 5))
        if len(rows) == 0:
            return np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int)
        return rows[:, :4].copy(), rows[:, 4].copy(), np.zeros(len(rows), dtype=int)


@pytest.fixture
def fake_detector():
    """返回 FakeDetector 构造器: ``fake_detector(per_frame)`` → 检测器实例。"""
    return FakeDetector