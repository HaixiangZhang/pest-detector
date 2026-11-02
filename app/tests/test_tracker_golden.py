"""golden test：固定帧序列 → 固定计数。

锁死"跨帧关联 + 轨迹后处理"的去重计数行为 —— 这是本项目精度的决定环节，
参数或逻辑一旦改动导致计数漂移，这里必须第一时间变红。

全部用合成框喂 IoUTracker，不加载模型、不读视频、不碰 GPU。
"""

import numpy as np

from pestdet.core.tracker import IoUTracker, postprocess_tracks


def make_tracker_config(**over) -> dict:
    """与 configs.yaml 默认值一致的 tracker 节（可覆盖单项）。"""
    cfg = {
        "high_thresh": 0.25,
        "low_thresh": 0.10,
        "new_track_thresh": 0.25,
        "match_thresh": 0.25,
        "second_match_thresh": 0.30,
        "boot_match_iou": 0.10,
        "match_dist_gate": 3.5,
        "track_buffer": 3,
        "min_track_frames": 3,
        "merge_gap_frames": 12,
        "merge_dist_threshold": 500.0,
        "merge_speed_max": 150.0,
        "spatial_overlap": 0.50,
        "confirm_enabled": False,
        "confirm_window": 0,
        "confirm_min_hits": 0,
    }
    cfg.update(over)
    return cfg


def feed(tracker: IoUTracker, boxes, scores=None) -> dict:
    """喂一帧检测框（boxes 可为空），返回本帧可见轨迹。"""
    arr = np.asarray(boxes, dtype=float).reshape(-1, 4)
    if scores is None:
        scores = np.full(len(arr), 0.9)
    return tracker.update(arr, scores)


def run_sequence(per_frame, cfg) -> tuple:
    """按帧序列跑一遍 tracker + 后处理，返回 (tracks, stats, tracker)。"""
    tr = IoUTracker(cfg)
    for boxes in per_frame:
        feed(tr, boxes)
    tracks, stats, _ = postprocess_tracks(tr.finalize(), cfg)
    return tracks, stats, tr


# ---------------------------------------------------------------- 场景

def test_single_moving_bug_counts_one():
    """一只虫匀速移动 10 帧 → 计 1 只。"""
    seq = [[[100 + 10 * f, 100, 130 + 10 * f, 130]] for f in range(10)]
    tracks, stats, _ = run_sequence(seq, make_tracker_config())
    assert len(tracks) == 1
    assert stats["tracks_final"] == 1


def test_two_separate_bugs_count_two():
    """两只相距很远的虫各动 10 帧 → 计 2 只。"""
    seq = [[[100 + 10 * f, 100, 130 + 10 * f, 130],
            [800, 400, 830, 430]] for f in range(10)]
    tracks, stats, _ = run_sequence(seq, make_tracker_config())
    assert len(tracks) == 2


def test_reappearance_reuses_id_within_gap():
    """消失 4 帧后在附近重现 → 在线复活沿用旧 ID，仍计 1 只。"""
    seq = [[[100 + 5 * f, 100, 130 + 5 * f, 130]] for f in range(5)]     # 0..4 可见
    seq += [[] for _ in range(4)]                                        # 5..8 消失
    seq += [[[100 + 5 * f, 100, 130 + 5 * f, 130]] for f in range(9, 14)]  # 9..13 重现
    tracks, stats, tr = run_sequence(seq, make_tracker_config())
    assert len(tracks) == 1
    assert tr._revive_count == 1
    assert len(tracks[1]["frames"]) == 10        # 5 + 5 帧，中间 4 帧未命中


def test_short_spurious_detection_filtered():
    """只出现 1 帧的误检被短轨迹过滤，不计数。"""
    seq = []
    for f in range(10):
        boxes = [[100 + 10 * f, 100, 130 + 10 * f, 130]]
        if f == 3:
            boxes.append([900, 700, 930, 730])   # 一闪而过的误检
        seq.append(boxes)
    tracks, stats, _ = run_sequence(seq, make_tracker_config())
    assert len(tracks) == 1
    assert stats["filtered_short"] >= 1


def test_duplicate_same_frame_deduped():
    """同一时刻同一位置被检出两次 → 空间去重合并为 1 只。"""
    seq = [[[100, 100, 130, 130], [100, 100, 130, 130]] for _ in range(8)]
    tracks, stats, _ = run_sequence(seq, make_tracker_config())
    assert len(tracks) == 1
    assert stats["merged_spatial"] >= 1


def test_long_gap_creates_new_id():
    """间隔超过 merge_gap_frames 的重现 → 视为新虫，计 2 只。"""
    cfg = make_tracker_config(merge_gap_frames=5)
    seq = [[[100, 100, 130, 130]] for _ in range(5)]     # 0..4
    seq += [[] for _ in range(10)]                       # 5..14 长时间消失
    seq += [[[100, 100, 130, 130]] for _ in range(5)]    # 15..19 原地重现
    tracks, _, tr = run_sequence(seq, cfg)
    assert len(tracks) == 2
    assert tr._revive_count == 0


def test_confirm_gate_rejects_unstable_track():
    """稳定确认门控: 只活 3 帧的轨迹在 5 帧窗口内未达标 → 不导出。"""
    cfg = make_tracker_config(confirm_enabled=True, confirm_window=5, confirm_min_hits=5)
    seq = [[[100 + 5 * f, 100, 130 + 5 * f, 130]] for f in range(3)]
    seq += [[] for _ in range(10)]
    tr = IoUTracker(cfg)
    for boxes in seq:
        feed(tr, boxes)
    assert tr.finalize() == {}


def test_confirm_gate_keeps_stable_track():
    """稳定确认门控: 连续命中满窗口 → 确认并计入。"""
    cfg = make_tracker_config(confirm_enabled=True, confirm_window=5, confirm_min_hits=5)
    seq = [[[100 + 5 * f, 100, 130 + 5 * f, 130]] for f in range(8)]
    tracks, _, tr = run_sequence(seq, cfg)
    assert len(tracks) == 1
    assert tr.gate_summary()["tracks_confirmed"] == 1