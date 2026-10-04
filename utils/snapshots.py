"""snapshots — 检出帧快照: 每个"最终判定有虫"的帧存一张带框标注的整帧图。

部署链路中被第二遍重绘（utils/render.py）复用（参数唯一来源 = 项目根 configs.yaml 的
snapshots 节，本模块不再自带默认值）:

    saver = SnapshotSaver(cfg["snapshots"], out_dir)
    ...
    if writer is not None or saver.will_save(visible):
        drawn = render.draw_frame(...)     # 只在真要写盘时才绘制，避免白画
    if writer is not None:
        writer.write(drawn)
    saver.save(drawn, visible, frame_idx, processed)
    ...
    result["snapshots"] = saver.summary()

粒度是"帧"而非"轨迹": 一帧里检出几只虫都只落一张图（画面已画出全部框），
所以不会出现同一帧被写多份、内容完全相同的冗余副本。
写入时 visible 的 key 已是最终 ID（id_map 转换过），落盘的必然都是计入最终结果的帧。

顶层只 import cv2 与 utils.config（保持模块轻量）。
"""

from pathlib import Path

import cv2

from utils.config import PIPELINE_CONFIG


class SnapshotSaver:
    """按帧保存检出帧快照（一个"有虫帧"一张图）。

    Args:
        cfg: 覆盖 configs.yaml 的 snapshots 节（只覆盖传入的 key）
        out_dir: 输出根目录（快照写到 out_dir/dir_name/ 下）
    """

    def __init__(self, cfg: dict = None, out_dir=None):
        self.cfg = dict(PIPELINE_CONFIG["snapshots"])
        self.cfg.update(cfg or {})
        self.dir = (Path(out_dir) / self.cfg["dir_name"]) if out_dir is not None else None
        self.frames = {}          # frame_idx -> {"path", "ids", "max_score", "proc"}
        self._dir_ready = False

    @property
    def enabled(self) -> bool:
        return bool(self.cfg["enabled"]) and self.dir is not None

    # ------------------------------------------------------------------ 写入

    def will_save(self, visible: dict) -> bool:
        """本帧是否有达标轨迹（没有就不必绘制、不必写盘）。"""
        return bool(self._hits(visible))

    def save(self, drawn, visible: dict, frame_idx: int, processed: int) -> int:
        """把本帧存成一张快照，返回写盘张数（0 或 1）。

        Args:
            drawn: 已绘制标注的整帧（None = 本帧未绘制，直接跳过）
            visible: 本帧可见轨迹 {最终ID: (bbox, score)}
            frame_idx: 原视频帧号（写进文件名与清单）
            processed: 已处理帧序号（写进清单）
        """
        if not self.enabled or drawn is None:
            return 0
        hits = self._hits(visible)
        if not hits:
            return 0

        if not self._dir_ready:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._dir_ready = True

        path = self.dir / self._name(frame_idx, hits)
        if not cv2.imwrite(str(path), drawn, self._imwrite_params()):
            return 0

        self.frames[int(frame_idx)] = {
            "path": path, "ids": sorted(hits),
            "max_score": max(hits.values()), "proc": int(processed),
        }
        return 1

    def _hits(self, visible: dict) -> dict:
        """本帧达标的轨迹 {最终ID: score}。"""
        if not self.enabled or not visible:
            return {}
        floor = float(self.cfg["min_score"])
        return {int(t): float(s) for t, (_, s) in visible.items() if float(s) >= floor}

    def _name(self, frame_idx: int, hits: dict) -> str:
        return (f"{self.cfg['prefix']}_f{int(frame_idx):06d}"
                f"_n{len(hits)}_s{max(hits.values()):.2f}.{self.cfg['fmt']}")

    def _imwrite_params(self) -> list:
        if str(self.cfg["fmt"]).lower() in ("jpg", "jpeg"):
            return [cv2.IMWRITE_JPEG_QUALITY, int(self.cfg["quality"])]
        return []

    # ------------------------------------------------------------------ 汇总

    def summary(self) -> dict:
        """组装 result.json 里的 snapshots 段（帧号升序）。"""
        items = []
        for frame_idx, rec in sorted(self.frames.items()):
            items.append({
                "frame": frame_idx,
                "file": rec["path"].name,
                "track_ids": rec["ids"],          # 该帧画面上出现的最终轨迹 ID
                "n": len(rec["ids"]),
                "max_score": round(rec["max_score"], 3),
            })

        return {
            "enabled": self.enabled,
            "dir": str(self.dir) if self.dir is not None else None,
            "count": len(items),                  # 落盘图片数 = 有虫帧数
            "items": items,
        }