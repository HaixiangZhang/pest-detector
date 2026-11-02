"""端到端冒烟：注入假检测器 + 临时生成的短视频，跑通整条 VideoPipeline。

验证迁移后的装配（配置注入 → 检测 → 关联 → 后处理 → 计数 → 结果结构）与
协作式取消，全部在 CPU 上完成，不需要 GPU、权重或 ffmpeg。
"""

import numpy as np
import pytest

from pestdet.core.errors import JobCancelled
from pestdet.core.pipeline import VideoPipeline

_W, _H = 320, 240


def _write_video(path, n_frames: int) -> None:
    """用 MJPG 写一段短视频（无编码器则跳过，避免环境差异导致假失败）。"""
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (_W, _H))
    if not writer.isOpened():
        pytest.skip("本机 OpenCV 无 MJPG 编码器，跳过端到端冒烟")
    for i in range(n_frames):
        frame = np.zeros((_H, _W, 3), dtype=np.uint8)
        cv2.rectangle(frame, (100 + 2 * i, 100), (130 + 2 * i, 130), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


def test_pipeline_single_bug_end_to_end(tmp_config, fake_detector, tmp_path):
    n = 12
    video = tmp_path / "clip.avi"
    _write_video(video, n)

    script = [[[100 + 2 * i, 100, 130 + 2 * i, 130, 0.9]] for i in range(n)]
    pipe = VideoPipeline(tmp_config, detector=fake_detector(script), mode="direct")
    result = pipe.run(str(video), verbose=False)

    assert result["counting"]["unique_count"] == 1
    assert result["video"]["processed_frames"] == n
    assert result["outputs"]["json"] is None                    # JSON 输出关闭
    # 标注视频始终尝试输出：编码器可用则为路径，不可用则为 None
    video_out = result["outputs"]["video"]
    assert video_out is None or video_out.endswith(".mp4")


def test_pipeline_two_bugs_end_to_end(tmp_config, fake_detector, tmp_path):
    n = 12
    video = tmp_path / "clip2.avi"
    _write_video(video, n)

    script = [[[100 + 2 * i, 100, 130 + 2 * i, 130, 0.9],
               [260, 60, 290, 90, 0.9]] for i in range(n)]
    pipe = VideoPipeline(tmp_config, detector=fake_detector(script), mode="direct")
    result = pipe.run(str(video), verbose=False)

    assert result["counting"]["unique_count"] == 2


def test_pipeline_cancel_raises(tmp_config, fake_detector, tmp_path):
    video = tmp_path / "clip3.avi"
    _write_video(video, 20)

    script = [[[100, 100, 130, 130, 0.9]] for _ in range(20)]
    pipe = VideoPipeline(tmp_config, detector=fake_detector(script), mode="direct")

    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    with pytest.raises(JobCancelled) as exc:
        pipe.run(str(video), cancel=cancel, verbose=False)
    assert exc.value.processed == 3