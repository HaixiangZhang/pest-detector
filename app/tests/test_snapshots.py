"""快照粒度测试：frame（每有虫帧一张）与 track（每只虫一张代表图）。

只测 SnapshotSaver 本身（不跑视频、不碰 GPU）：构造逐帧在线轨迹 + id_map，
直接驱动 plan / will_save / save，断言落盘张数与代表帧选取得当。
"""

import numpy as np

from pestdet.core.snapshots import SnapshotSaver

_IMG = np.zeros((16, 16, 3), dtype=np.uint8)


def _cfg(mode="track", min_score=0.0, enabled=True):
    return {
        "enabled": enabled,
        "mode": mode,
        "dir_name": "frames",
        "prefix": "pest",
        "fmt": "jpg",
        "quality": 95,
        "min_score": min_score,
    }


def _drive(saver, frame_visible, id_map):
    """按第二遍渲染的顺序逐帧喂给 saver，返回落盘张数。"""
    saved = 0
    for proc, vis in enumerate(frame_visible):
        final = {id_map[t]: v for t, v in vis.items() if t in id_map}
        if saver.will_save(final, proc):
            saved += saver.save(_IMG, final, proc, proc)
    return saved


# 两只虫：ID0 峰值在 processed=1，ID1 峰值在 processed=2（代表帧互不冲突）
_TWO_BUGS = [
    {10: ((0, 0, 10, 10), 0.50), 20: ((20, 20, 30, 30), 0.60)},
    {10: ((0, 0, 10, 10), 0.90), 20: ((20, 20, 30, 30), 0.80)},
    {10: ((0, 0, 10, 10), 0.70), 20: ((20, 20, 30, 30), 0.95)},
]
_MAP = {10: 0, 20: 1}


# ---------------------------------------------------------------- track 模式

def test_track_mode_one_rep_per_insect(tmp_path):
    saver = SnapshotSaver(_cfg(mode="track"), tmp_path)
    saver.plan(_TWO_BUGS, _MAP)

    assert _drive(saver, _TWO_BUGS, _MAP) == 2   # 张数 = 虫数

    snap = saver.summary()
    assert snap["mode"] == "track"
    assert snap["count"] == 2
    # 每只虫恰好出现一次，且各自取到置信度最高的那一帧
    reps = {item["tracks"][0]: item["frame"] for item in snap["items"]}
    assert reps == {0: 1, 1: 2}


def test_track_mode_displaces_to_free_frame(tmp_path):
    """两只虫的峰值撞在同一帧时，峰值低的让位到自己次优的空闲帧。"""
    frames = [
        {10: ((0, 0, 10, 10), 0.99), 20: ((20, 20, 30, 30), 0.98)},
        {10: ((0, 0, 10, 10), 0.50)},
        {20: ((20, 20, 30, 30), 0.40)},
    ]
    saver = SnapshotSaver(_cfg(mode="track"), tmp_path)
    saver.plan(frames, _MAP)

    assert _drive(saver, frames, _MAP) == 2
    reps = {item["tracks"][0]: item["frame"] for item in saver.summary()["items"]}
    assert reps == {0: 0, 1: 2}                  # ID1 让出 0，改落 2


def test_track_mode_min_score_skips_low_peak(tmp_path):
    """某只虫的峰值低于 min_score → 整只不落盘。"""
    saver = SnapshotSaver(_cfg(mode="track", min_score=0.92), tmp_path)
    saver.plan(_TWO_BUGS, _MAP)

    assert _drive(saver, _TWO_BUGS, _MAP) == 1    # ID0 峰值 0.90 < 0.92 被跳过
    items = saver.summary()["items"]
    assert [it["tracks"] for it in items] == [[1]]


def test_track_mode_ignores_unmapped_online_ids(tmp_path):
    """被后处理过滤掉的在线 ID 不在 id_map 中 → 不参与选帧。"""
    frames = [{99: ((0, 0, 5, 5), 0.99)}]         # 99 未登记 → 无最终轨迹
    saver = SnapshotSaver(_cfg(mode="track"), tmp_path)
    saver.plan(frames, _MAP)
    assert _drive(saver, frames, _MAP) == 0
    assert saver.summary()["count"] == 0


# ---------------------------------------------------------------- frame 模式

def test_frame_mode_one_per_insect_frame(tmp_path):
    saver = SnapshotSaver(_cfg(mode="frame"), tmp_path)
    saver.plan(_TWO_BUGS, _MAP)                    # frame 模式: 空操作

    assert _drive(saver, _TWO_BUGS, _MAP) == 3     # 张数 = 有虫帧数
    snap = saver.summary()
    assert snap["mode"] == "frame"
    assert snap["count"] == 3
    assert "tracks" not in snap["items"][0]        # frame 模式不带代表虫字段


def test_frame_mode_min_score_filters_frames(tmp_path):
    """某帧所有轨迹都低于 min_score → 该帧不落盘。"""
    saver = SnapshotSaver(_cfg(mode="frame", min_score=0.85), tmp_path)
    assert _drive(saver, _TWO_BUGS, _MAP) == 2     # 仅 processed=1/2 达标
    assert [it["frame"] for it in saver.summary()["items"]] == [1, 2]


# ---------------------------------------------------------------- 总开关

def test_disabled_saver_writes_nothing(tmp_path):
    saver = SnapshotSaver(_cfg(enabled=False), tmp_path)
    saver.plan(_TWO_BUGS, _MAP)
    assert not saver.enabled
    assert not saver.will_save({0: ((0, 0, 1, 1), 0.9)}, 0)
    assert saver.save(_IMG, {0: ((0, 0, 1, 1), 0.9)}, 0, 0) == 0
    assert saver.summary()["count"] == 0