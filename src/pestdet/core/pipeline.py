"""pipeline — 端到端视频工作流: 检测 → 跨帧关联 → 去重计数 → 视频 + JSON。

检测模式（sahi / direct）只决定用哪个检测器（core.detector），其余流程完全共用。

设计约束（见 docs/PLAN_web_mvp.md 2.2）:
    - 配置由调用方注入（不再读全局 PIPELINE_CONFIG 单例），每任务一份独立配置
    - 不 print、不 sys.exit；阶段输出走注入的 logger，进度走 progress_cb 回调
    - 帧循环内协作式取消: 每帧检查 cancel()，命中抛 JobCancelled（由上层决定呈现）

调用方式（CLI / services 层负责 load_config + 合并覆盖 + 装配 logger）:
    cfg = merge_overrides(load_config(), over)
    pipe = VideoPipeline(cfg, mode="sahi", logger=logger)
    result = pipe.run("videos/test0.mp4", progress_cb=..., cancel=...)

三件产物（默认 runs/<视频名>_<时间戳>/）:
    tracked.mp4   推理后视频（框 + track ID + 轨迹尾迹 + 计数面板）
    frames/       检出帧快照（粒度由 snapshots.mode 决定: track=每只虫一张代表图，
                  取该虫置信度最高的帧，张数=虫数；frame=每个判定有虫的帧一张，
                  同帧多虫只落一张，张数=有虫帧数）
    result.json   暂存数据（unique_count / per_frame / tracks / roi / snapshots / config）

注意: 视频上的标注文字一律用 ASCII —— cv2.putText 不支持中文，写中文会渲染成乱码，
      中文说明只出现在日志与 result.json 里。
"""

import copy
import json
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from pestdet.core.detector import build_detector, detect_batch
from pestdet.core.errors import JobCancelled
from pestdet.core.render import render_pass
from pestdet.core.roi import GrassMasker, filter_boxes_inside_quad
from pestdet.core.snapshots import SnapshotSaver
from pestdet.core.tracker import IoUTracker, postprocess_tracks
from pestdet.infra.logging import get_logger
from pestdet.infra.paths import PROJECT_ROOT, VIDEO_EXTS, new_timestamp
from pestdet.infra.registry import latest_pest, resolve_pest


class VideoPipeline:
    """端到端工作流: 检测 → 跨帧关联 → 去重计数 → 视频 + JSON。

    Args:
        config: 完整部署配置 dict（必填，由调用方 load_config + 合并覆盖后注入）
        model_path: 覆盖 config 的模型路径（None → 用 config 里的；空串 → 取最新登记权重）
        mode: 覆盖 config 的检测模式 "sahi" | "direct"（None → 用 config 里的）
        detector: 注入自定义检测器（测试用；给了就不再建模型）
        logger: 注入 logger（None → 用 pestdet.core.pipeline 的默认 logger）
    """

    def __init__(self, config: dict, model_path=None, mode=None, detector=None, logger=None):
        self.config = copy.deepcopy(config)
        if model_path is not None:
            self.config["model_path"] = model_path
        if mode is not None:
            self.config["mode"] = mode
        self.detector = detector
        self._owns_detector = detector is None     # 自建模型才由本流程负责释放显存
        self.logger = logger or get_logger(__name__)
        self.out_dir = None
        self._verbose = True

    # ------------------------------------------------------------------ 主流程

    def run(self, source: str, progress_cb=None, cancel=None, verbose: bool = True) -> dict:
        """跑完整工作流。

        Args:
            source: 视频路径
            progress_cb: 可选回调 progress_cb(已处理帧, 计划帧数, 已用秒数)，供 UI 接进度条
            cancel: 可选无参回调，返回 True 表示请求取消（帧循环内每帧检查一次）
            verbose: 是否输出各阶段日志

        Returns:
            dict: 结果摘要（同时写入 result.json）

        Raises:
            FileNotFoundError / ValueError: 输入非法
            JobCancelled: 运行途中收到取消信号（已产出的中间产物保留，不写最终 JSON）
        """
        self._verbose = verbose
        t0 = time.time()
        cfg = self.config

        # ---------------- 1/6 校验输入 ----------------
        video = Path(source)
        if not video.exists():
            raise FileNotFoundError(f"视频不存在: {source}")
        if video.suffix.lower() not in VIDEO_EXTS:
            raise ValueError(f"不支持的视频格式: {video.suffix}（支持: {sorted(VIDEO_EXTS)}）")
        if self.detector is not None:
            # 注入检测器（测试/自定义后端）时不需要权重路径
            model_path = f"(注入检测器: {type(self.detector).__name__})"
        else:
            model_path = self._resolve_model(cfg["model_path"])
        self.out_dir = self._plan_out_dir(video)
        self._log_header(video, model_path)

        # ---------------- 2/6 加载检测器 ----------------
        if self.detector is None:
            self.detector = build_detector(cfg["mode"], model_path, cfg)

        # ---------------- 3/6 逐帧检测 + 跨帧关联 ----------------
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"无法打开视频: {source}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        stride = max(1, int(cfg["frame_stride"]))
        max_frames = int(cfg["max_frames"])
        n_plan = (total_frames + stride - 1) // stride if total_frames > 0 else 0
        if max_frames:
            n_plan = min(n_plan, max_frames) if n_plan else max_frames

        tracker = IoUTracker(cfg["tracker"])
        masker = GrassMasker(cfg["mask"])
        saver = SnapshotSaver(cfg["snapshots"], self.out_dir)
        per_frame, raw_det_count, masked_out = [], 0, 0
        frame_visible, quads = [], []      # 逐帧在线轨迹与遮罩四边形，留给第二遍重绘
        frame_idx, processed = -1, 0
        # 帧批只在 direct 模式生效（sahi 在帧内已按切片批处理）；batch=1 即逐帧
        batch_size = int(cfg["direct"]["batch"]) if cfg["mode"] == "direct" else 1

        def run_batch(batch):
            """对一批已遮罩帧做一次前向，再按帧序回放给 tracker。

            tracker 是时序状态机，结果必须按帧序喂 —— 批只减少前向次数，
            不改变关联与计数结果（batch=1 时与逐帧处理完全等价）。
            """
            nonlocal raw_det_count, masked_out, processed
            results = detect_batch(self.detector, [b[1] for b in batch],
                                   [b[2] for b in batch])
            for (fidx, _infer, _mask, quad), (boxes, scores, labels) in zip(batch, results):
                n_raw = len(boxes)
                if cfg["mask"]["filter_outside"]:
                    boxes, scores, labels = filter_boxes_inside_quad(
                        boxes, scores, labels, quad)
                    masked_out += n_raw - len(boxes)
                raw_det_count += len(boxes)

                visible = tracker.update(boxes, scores, labels)
                visible = tracker.visible_confirmed(visible)
                per_frame.append({
                    "frame": fidx,
                    "n": len(visible),
                    "ids": sorted(int(i) for i in visible),
                })

                # 本帧的在线轨迹与遮罩四边形留到第二遍重绘（那时才拿得到最终 ID）
                frame_visible.append({int(t): (tuple(float(v) for v in b), float(s))
                                      for t, (b, s) in visible.items()})
                quads.append(quad)

                processed += 1
                self._progress(processed, n_plan, t0, progress_cb)

        pending = []                       # 帧批缓冲: (frame_idx, 遮罩后帧, valid_mask, quad)
        while True:
            if cancel is not None and cancel():
                cap.release()
                self.logger.info("任务被取消，已处理 %d 帧", processed)
                raise JobCancelled(processed)
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1
            if frame_idx % stride:
                continue
            if max_frames and processed + len(pending) >= max_frames:
                break

            # 遮罩只作用于送进网络的像素；frame 原样保留给绘制与输出
            infer_frame = masker.apply(frame)
            quad = None if masker.quad is None else masker.quad.copy()
            pending.append((frame_idx, infer_frame, masker.mask, quad))
            if len(pending) >= batch_size:
                run_batch(pending)
                pending = []

        if pending:                        # 尾批
            run_batch(pending)
        cap.release()

        # 检测阶段结束，模型不再需要: 立即释放显存（否则长驻服务里显存要等进程退出才降）
        self.close()

        # ---------------- 4/6 轨迹后处理 ----------------
        tracks, pp_stats, id_map = postprocess_tracks(tracker.finalize(), cfg["tracker"])
        gate_stats = tracker.gate_summary()
        self._log_postprocess(masker, masked_out, gate_stats, pp_stats)

        # ---------------- 5/6 重绘输出（视频 / 快照）----------------
        # 绘制统一挪到后处理之后: 用 id_map 把在线 ID 换成最终 ID 重画，
        # 保证画面里的框与 ID 和最终计数严格一致（未进入最终结果的轨迹不再出现）。
        self._info("[5/6] 重绘输出:   用最终 ID 重绘 %d 帧（视频/快照）", len(frame_visible))
        writer = render_pass(video, cfg, self.out_dir, frame_visible, quads, id_map,
                             tracker, saver, fps, width, height, n_plan, cancel=cancel)
        if saver.enabled:
            snap = saver.summary()
            unit = "每只虫一张代表图" if snap["mode"] == "track" else "有虫帧"
            self._info("[5/6] 检出帧快照: %s %d 张 → %s", unit, snap["count"], snap["dir"])

        # ---------------- 6/6 写出产物 ----------------
        meta = {
            "fps": round(float(fps), 3),
            "out_fps": round(float(fps) / stride, 3),
            "width": width,
            "height": height,
            "total_frames": total_frames,
            "processed_frames": processed,
            "frame_stride": stride,
        }
        result = self._build_result(video, model_path, meta, per_frame,
                                    raw_det_count, tracks, pp_stats, t0,
                                    masker=masker, masked_out=masked_out, saver=saver,
                                    gate_stats=gate_stats)

        video_out = None
        if writer is not None:
            video_out = str(self.out_dir / cfg["video_name"])
        json_out = None
        if cfg["save_json"]:
            json_out = str(self.out_dir / cfg["json_name"])
        result["outputs"] = {"video": video_out, "json": json_out}

        if cfg["save_json"]:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with open(json_out, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        self._log_footer(result, video_out, json_out)
        return result

    # ------------------------------------------------------------------ 辅助

    def close(self) -> None:
        """释放自建检测器占用的 GPU 显存（幂等，任务正常结束与取消/异常路径都应调用）。

        长驻服务里模型不会随 run() 返回自动归还显存 —— PyTorch 缓存分配器会保留
        空闲块，nvidia-smi 看不到下降，必须显式 empty_cache。注入的检测器由调用方
        负责（不在此关闭），以免影响复用。
        """
        det = self.detector
        self.detector = None
        if det is None or not self._owns_detector:
            return
        close_fn = getattr(det, "close", None)
        if close_fn is None:
            return
        try:
            close_fn()
        except Exception:
            self.logger.warning("检测器释放失败（忽略，继续收尾）", exc_info=True)

    @staticmethod
    def _resolve_model(model: str) -> str:
        """解析模型路径: 直接路径 → 已登记名 pest{N} → 最新登记权重。"""
        if model:
            p = Path(model)
            if p.exists():
                return str(p)
            registered = resolve_pest(str(model))
            if registered and Path(registered).exists():
                return registered
            raise FileNotFoundError(f"模型路径不存在，也不是已登记的权重名: {model}")

        latest = latest_pest()
        if latest:
            return latest
        raise ValueError(
            "model_path 为空，且 runs/registry.json 中没有可用登记权重。\n"
            "  请用 --model 指定权重路径，或把部署权重放到 best.pt"
        )

    def _plan_out_dir(self, video: Path) -> Path:
        """规划输出目录路径: <output_root>/<视频名>_<时间戳>/（每次运行独立，不覆盖历史）。

        只算路径、不建目录 —— 目录留到真正要写文件时再建（见 render.make_writer 与
        run() 写 JSON 处）。这样"一个产物都没写"的运行（输出全关、或中途报错）
        不会在 runs/ 下留下空目录。
        """
        root = Path(self.config["output_root"])
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        return root / f"{video.stem}_{new_timestamp()}"

    def _progress(self, done: int, total: int, t0: float, cb):
        """进度上报（回调给 UI + 按 progress_every 打日志）。"""
        elapsed = time.time() - t0
        if cb is not None:
            cb(done, total, elapsed)
        if not self._verbose:
            return
        every = max(1, int(self.config["progress_every"]))
        if done % every and done != total:
            return
        if total:
            pct = 100.0 * done / total
            eta = elapsed / done * (total - done) if done else 0.0
        else:
            pct, eta = 0.0, 0.0
        self.logger.info("[3/6] 逐帧检测+关联: %d/%s 帧 (%.1f%%) 已用 %.1fs ETA %.1fs",
                         done, total or "?", pct, elapsed, eta)

    def _build_result(self, video, model_path, meta, per_frame, raw_det_count,
                      tracks, pp_stats, t0, masker=None, masked_out=0, saver=None,
                      gate_stats=None) -> dict:
        """组装 result.json 内容（暂存数据，供 UI / 下游读取）。"""
        cfg = self.config
        track_list = []
        for tid, trk in sorted(tracks.items()):
            item = {
                "id": tid,
                "start_frame": trk["start_frame"],
                "end_frame": trk["end_frame"],
                "n_frames": len(trk["frames"]),
                "online_ids": trk.get("origins", []),   # 合并前的在线 ID（被并成一只的几段）
                "confidence_avg": round(float(np.mean(trk["confs"])), 3),
                "envelope": [int(v) for v in trk["envelope"]],     # [x1, y1, x2, y2]
            }
            if cfg["save_track_path"]:
                item["path"] = [[round(float(c[0]), 1), round(float(c[1]), 1)]
                                for c in trk["centers"]]
            track_list.append(item)

        return {
            "source": str(video),
            "source_name": video.name,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": model_path,
            "mode": cfg["mode"],
            "method": f"{cfg['mode']}检测 + IoU 关联 + 轨迹后处理",
            "video": meta,
            "counting": {
                "unique_count": len(tracks),        # 去重后虫数（最终答案）
                "raw_detections": raw_det_count,    # 逐帧检测框总数（去重前，对比用）
                **pp_stats,
                **(gate_stats or {}),               # 稳定确认门控统计
            },
            "tracks": track_list,
            "per_frame": per_frame,
            "roi": {
                "enabled": bool(cfg["mask"]["enabled"]),
                "mode": cfg["mask"]["mode"],
                "quad": None if masker is None or masker.quad is None
                        else [[int(x), int(y)] for x, y in masker.quad],
                "refit_count": 0 if masker is None else masker.refit_count,
                "fit_fail_count": 0 if masker is None else masker.fail_count,
                "jitter_reject_count": 0 if masker is None else masker.jitter_reject_count,
                "filter_outside": bool(cfg["mask"]["filter_outside"]),
                "filtered_boxes": masked_out,
            },
            "snapshots": (saver.summary() if saver is not None and saver.enabled
                          else {"enabled": False, "dir": None, "count": 0, "items": []}),
            "config": {
                "mode": cfg["mode"],
                "detector": cfg["sahi"] if cfg["mode"] == "sahi" else cfg["direct"],
                "tracker": cfg["tracker"],
                "mask": cfg["mask"],
                "snapshots": cfg["snapshots"],
                "frame_stride": cfg["frame_stride"],
                "max_frames": cfg["max_frames"],
            },
            "outputs": {"video": None, "json": None},   # run() 内回填
            "elapsed_s": round(time.time() - t0, 2),
        }

    # ------------------------------------------------------------------ 日志

    def _info(self, msg, *args) -> None:
        if self._verbose:
            self.logger.info(msg, *args)

    def _log_header(self, video: Path, model_path: str) -> None:
        if not self._verbose:
            return
        cfg = self.config
        self.logger.info("=" * 66)
        self.logger.info("  开始工作（检测 → 去重计数 → 视频/数据输出）")
        self.logger.info("=" * 66)
        self.logger.info("  [1/6] 输入视频:   %s", video)
        self.logger.info("  [1/6] 检测模型:   %s", model_path)
        mode_desc = (f"（切片大小 {cfg['sahi']['slice_size']} 重叠 {cfg['sahi']['overlap_ratio']} "
                     f"batch = {cfg['sahi']['batch']}）"
                     if cfg["mode"] == "sahi"
                     else f"（整帧 imgsz={cfg['direct']['imgsz']} batch = {cfg['direct']['batch']}）")
        self.logger.info("  [1/6] 检测模式:   %s%s", cfg["mode"], mode_desc)
        self.logger.info("  [1/6] 草地遮罩:   %s", self._describe_mask(cfg["mask"]))
        self.logger.info("  [1/6] 检出帧快照: %s", self._describe_snapshots(cfg["snapshots"]))
        self.logger.info("  [1/6] 输出目录:   %s", self.out_dir)

    def _log_postprocess(self, masker, masked_out, gate_stats, pp_stats) -> None:
        if not self._verbose:
            return
        cfg = self.config
        self.logger.info("  [4/6] 草地遮罩:   %s", masker.describe())
        if cfg["mask"]["filter_outside"]:
            self.logger.info("  [4/6] 越界框过滤: 剔除 %d 个中心点落在四边形外的检测框", masked_out)
        if gate_stats["confirm_enabled"] and gate_stats["confirm_window"] > 0:
            self.logger.info(
                "  [4/6] 稳定确认:   %d 帧窗口内需命中 %d 帧 → 确认 %d 条，剔除不稳定 %d 条",
                gate_stats["confirm_window"], gate_stats["confirm_min_hits"],
                gate_stats["tracks_confirmed"], gate_stats["rejected_unconfirmed"])
        else:
            self.logger.info("  [4/6] 稳定确认:   已关闭（不做窗口门控）")
        if gate_stats.get("revived_online", 0):
            self.logger.info("  [4/6] 在线复活:     归档轨迹被捞回 %d 次（沿用旧 ID，不新建）",
                             gate_stats["revived_online"])
        self.logger.info(
            "  [4/6] 轨迹后处理: 原始 %d 条 → 过滤短轨迹 %d / 合并断轨 %d / 空间去重 %d → 最终 %d 只",
            pp_stats["tracks_raw"], pp_stats["filtered_short"],
            pp_stats["merged_broken"], pp_stats["merged_spatial"], pp_stats["tracks_final"])

    def _log_footer(self, result: dict, video_out, json_out) -> None:
        if not self._verbose:
            return
        counting = result["counting"]
        self.logger.info("  [5/6] 推理视频:   %s", video_out or "（未输出）")
        self.logger.info("  [6/6] 暂存数据:   %s", json_out or "（未输出）")
        self.logger.info("-" * 66)
        self.logger.info("  处理帧数:         %s", result["video"]["processed_frames"])
        self.logger.info("  逐帧检测框累计:   %d 次（去重前）", counting["raw_detections"])
        self.logger.info("  去重后虫数:       %d 只", counting["unique_count"])
        self.logger.info("  耗时:             %s s", result["elapsed_s"])
        self.logger.info("=" * 66)

    @staticmethod
    def _describe_snapshots(s: dict) -> str:
        if not s["enabled"]:
            return "未启用"
        grain = "每只虫一张代表图" if s.get("mode") == "track" else "每个有虫帧一张"
        return (f"启用（{grain}，{s['fmt'].upper()} 质量 {s['quality']}）"
                f" → {s['dir_name']}/")

    @staticmethod
    def _describe_mask(m: dict) -> str:
        if not m["enabled"]:
            return "未启用（整帧推理）"
        mode = "自动绿色分割拟合四边形" if m["mode"] == "auto" else "手动四边形坐标"
        n = int(m["refresh_every"])
        refresh = "逐帧重拟合" if n == 1 else (f"每 {n} 帧重拟合" if n > 0 else "首帧拟合后固定")
        filt = "越界框过滤开启" if m["filter_outside"] else "不过滤越界框"
        return f"启用（{mode}，{refresh}，{filt}）"