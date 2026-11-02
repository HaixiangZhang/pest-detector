"""snapshots — 检出帧快照。

两种粒度（configs.yaml `snapshots.mode`）:

    frame  每个"最终判定有虫"的帧存一张带框标注的整帧图（同帧多虫只落一张，
           张数 = 有虫帧数）。
    track  每只虫（最终轨迹）只存一张代表图，取该虫置信度最高的那一帧，
           张数 = 虫数。代表帧尽量互不重复（贪心: 峰值高的虫先挑未被占用的帧），
           实在没有空闲帧时才允许两只虫共用一帧。

被第二遍重绘（core.render）复用（参数由调用方注入，本模块不读全局配置）:

    saver = SnapshotSaver(cfg["snapshots"], out_dir)
    saver.plan(frame_visible, id_map)          # track 模式: 预先为每只虫选定代表帧
    ...
    if writer is not None or saver.will_save(visible, processed):
        drawn = render.draw_frame(...)     # 只在真要写盘时才绘制，避免白画
    if writer is not None:
        writer.write(drawn)
    saver.save(drawn, visible, frame_idx, processed)
    ...
    result["snapshots"] = saver.summary()

写入时 visible 的 key 已是最终 ID（id_map 转换过），落盘的必然都是计入最终结果的帧/虫。

顶层只 import cv2 与标准库（保持模块轻量）。
"""

from pathlib import Path

import cv2


class SnapshotSaver:
    """按帧或按轨迹保存检出快照（粒度由 config 的 mode 决定）。

    Args:
        config: configs.yaml 的 snapshots 节（必填，由调用方注入完整配置）
        out_dir: 输出根目录（快照写到 out_dir/dir_name/ 下）
    """

    def __init__(self, config: dict, out_dir=None):
        self.cfg = dict(config)
        self.mode = str(self.cfg.get("mode", "frame"))
        self.dir = (Path(out_dir) / self.cfg["dir_name"]) if out_dir is not None else None
        self.frames = {}          # frame_idx -> {"path","ids","rep","max_score","proc"}
        self._dir_ready = False
        self._reps = {}           # processed -> [最终ID...]（track 模式的代表帧计划）

    @property
    def enabled(self) -> bool:
        return bool(self.cfg["enabled"]) and self.dir is not None

    # ------------------------------------------------------------------ 计划

    def plan(self, frame_visible, id_map) -> None:
        """track 模式: 为每只最终虫选定代表帧（processed 序号）。frame 模式为空操作。

        Args:
            frame_visible: 逐帧的在线可见轨迹 [{在线ID: (bbox, score)}, ...]
            id_map: 在线 ID → 最终 ID（后处理产物；被过滤/合并的在线 ID 也在表内）
        """
        self._reps = {}
        if not self.enabled or self.mode != "track":
            return

        per_track = {}                     # 最终ID -> {processed: 该帧最高分}
        for proc, vis in enumerate(frame_visible):
            for tid, (_bbox, score) in vis.items():
                fid = id_map.get(tid)
                if fid is None:
                    continue
                s = float(score)
                slot = per_track.setdefault(fid, {})
                if s > slot.get(proc, -1.0):
                    slot[proc] = s

        floor = float(self.cfg["min_score"])
        taken = set()
        # 峰值置信度高的虫先挑帧，好帧优先给更可信的目标
        order = sorted(per_track, key=lambda f: (-max(per_track[f].values()), f))
        for fid in order:
            cands = sorted(per_track[fid].items(), key=lambda kv: (-kv[1], kv[0]))
            if cands[0][1] < floor:        # 该虫最高分都不达标 → 不存
                continue
            chosen = next((p for p, _ in cands if p not in taken), cands[0][0])
            taken.add(chosen)
            self._reps.setdefault(chosen, []).append(fid)

    # ------------------------------------------------------------------ 写入

    def will_save(self, visible: dict, processed: int = -1) -> bool:
        """本帧是否有要落盘的轨迹（没有就不必绘制、不必写盘）。"""
        return bool(self._select(visible, processed))

    def save(self, drawn, visible: dict, frame_idx: int, processed: int) -> int:
        """把本帧存成一张快照，返回写盘张数（0 或 1）。

        Args:
            drawn: 已绘制标注的整帧（None = 本帧未绘制，直接跳过）
            visible: 本帧可见轨迹 {最终ID: (bbox, score)}
            frame_idx: 原视频帧号（写进文件名与清单）
            processed: 已处理帧序号（写进清单；track 模式用它查代表帧计划）
        """
        if not self.enabled or drawn is None:
            return 0
        hits = self._select(visible, processed)
        if not hits:
            return 0

        if not self._dir_ready:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._dir_ready = True

        rep = sorted(hits) if self.mode == "track" else []
        path = self.dir / self._name(frame_idx, hits, rep)
        if not cv2.imwrite(str(path), drawn, self._imwrite_params()):
            return 0

        self.frames[int(frame_idx)] = {
            "path": path, "ids": sorted(hits), "rep": rep,
            "max_score": max(hits.values()), "proc": int(processed),
        }
        return 1

    def _select(self, visible: dict, processed: int) -> dict:
        """本帧要落盘的轨迹 {最终ID: score}。"""
        if not self.enabled or not visible:
            return {}
        if self.mode == "track":
            want = self._reps.get(int(processed), [])
            return {fid: float(visible[fid][1]) for fid in want if fid in visible}
        floor = float(self.cfg["min_score"])
        return {int(t): float(s) for t, (_, s) in visible.items() if float(s) >= floor}

    def _name(self, frame_idx: int, hits: dict, rep: list) -> str:
        score = max(hits.values())
        if self.mode == "track":
            tag = "-".join(f"{t:04d}" for t in rep)
            return (f"{self.cfg['prefix']}_t{tag}"
                    f"_f{int(frame_idx):06d}_s{score:.2f}.{self.cfg['fmt']}")
        return (f"{self.cfg['prefix']}_f{int(frame_idx):06d}"
                f"_n{len(hits)}_s{score:.2f}.{self.cfg['fmt']}")

    def _imwrite_params(self) -> list:
        if str(self.cfg["fmt"]).lower() in ("jpg", "jpeg"):
            return [cv2.IMWRITE_JPEG_QUALITY, int(self.cfg["quality"])]
        return []

    # ------------------------------------------------------------------ 汇总

    def summary(self) -> dict:
        """组装 result.json 里的 snapshots 段（帧号升序）。"""
        items = []
        for frame_idx, rec in sorted(self.frames.items()):
            item = {
                "frame": frame_idx,
                "file": rec["path"].name,
                "track_ids": rec["ids"],          # 该帧画面上出现的最终轨迹 ID
                "n": len(rec["ids"]),
                "max_score": round(rec["max_score"], 3),
            }
            if self.mode == "track":
                item["tracks"] = rec["rep"]       # 该代表图对应的虫（最终轨迹 ID）
            items.append(item)

        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "dir": str(self.dir) if self.dir is not None else None,
            "count": len(items),                  # 落盘图片数（frame=有虫帧数 / track=虫数）
            "items": items,
        }