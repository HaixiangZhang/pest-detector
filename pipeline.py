"""pipeline — 视频检测工作流实现（无独立入口，由 cli.py 的 sahi / direct 子命令调用）。

检测模式只决定用哪个检测器，其余流程（遮罩 → 检测 → 跨帧去重计数 → 产物）完全共用。

用法（统一入口 = cli.py；6 个阶段的进度会实时打印）:
    python cli.py sahi   --source videos/test0.mp4                  # 切片检测（模型留空 → 取最新登记权重）
    python cli.py direct --source videos/test0.mp4                  # 整帧直推
    python cli.py sahi   --source videos/test0.mp4 --model pest1

三件产物（默认 runs/<视频名>_<时间戳>/）:
    tracked.mp4   推理后视频（框 + track ID + 轨迹尾迹 + 计数面板）
    frames/       检出帧快照（每个判定有虫的帧一张，带框标注的整帧，同帧只落一张）
    result.json   暂存数据（unique_count / per_frame / tracks / roi / snapshots / config）

部署参数唯一来源 = 项目根 configs.yaml（改参数只改那里，不改代码）。

注意: 视频上的标注文字一律用 ASCII —— cv2.putText 不支持中文，写中文会渲染成乱码，
      中文说明只出现在终端输出与 result.json 里。
"""

import sys
from pathlib import Path

# --- 环境引导: UTF-8 输出（Windows 默认 cp936 会让中文乱码）+ 项目根入 sys.path ---
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


# ============================================================================
# 依赖导入
# ============================================================================
try:
    import argparse
    import copy
    import json
    import os
    import time
    from datetime import datetime

    import cv2
    import numpy as np

    from utils.config import PIPELINE_CONFIG, deep_update
    from utils.paths import PROJECT_ROOT, new_timestamp, VIDEO_EXTS
    from utils.registry import latest_pest, resolve_pest
    from utils.render import render_pass
    from utils.roi import GrassMasker, filter_boxes_inside_quad
    from utils.sahi import SAHIInferenceEngine
    from utils.snapshots import SnapshotSaver
    from utils.tracker import IoUTracker, postprocess_tracks
except ImportError as _e:
    print(f"\n[错误] 缺少依赖或模块导入失败: {_e}")
    print("请先安装依赖: pip install -r requirements.txt（视频链路需要 opencv-python / numpy）\n")
    raise SystemExit(1)


def _detect_batch(detector, frames, masks) -> list:
    """统一批量检测入口: 检测器实现了 detect_batch 就用它，否则逐帧回退到 detect。

    回退分支是为"注入自定义检测器"留的（只需实现单帧 detect 即可接入）。
    """
    fn = getattr(detector, "detect_batch", None)
    if fn is not None:
        return fn(frames, masks)
    return [detector.detect(f, valid_mask=m) for f, m in zip(frames, masks)]


def build_detector(mode: str, model_path: str, config: dict):
    """按模式构建检测器（返回带 detect / detect_batch 的对象）。

    检测器契约:
        detect(frame_bgr, valid_mask=None) -> (boxes(N,4) float, scores(N,) float, labels(N,) int)
        detect_batch(frames, valid_masks=None) -> [同上，逐帧对应]（可选，缺省逐帧回退 detect）
        valid_mask 为可选 ROI 掩码 (H,W) uint8，非零 = 有效区域；
        仅用于跳过无效区域的算力优化，不改变输出坐标系。
    """
    if mode == "sahi":
        return _SahiDetector(model_path, config["sahi"])
    if mode == "direct":
        return _DirectDetector(model_path, config["direct"])
    raise ValueError(f"未知检测模式: {mode}（可选: sahi / direct）")


class _SahiDetector:
    """SAHI 切片检测（复用 utils.sahi.SAHIInferenceEngine）。"""

    def __init__(self, model_path: str, cfg: dict):
        self.cfg = cfg
        self.engine = SAHIInferenceEngine(
            model_path,
            slice_size=cfg["slice_size"],
            overlap_ratio=cfg["overlap_ratio"],
            conf_threshold=cfg["conf"],
            iou_threshold=cfg["iou"],
            batch=cfg["batch"],
            device=cfg["device"],
            quantize=cfg["quantize"],
            fusion_method=cfg["fusion"],
            min_coverage=cfg["min_coverage"],
        )

    def detect(self, frame, valid_mask=None):
        r = self.engine.detect(frame, multi_scale=self.cfg["multi_scale"],
                               scale_sizes=self.cfg["scale_sizes"],
                               valid_mask=valid_mask)
        return r["boxes"], r["scores"], r["labels"]


class _DirectDetector:
    """整帧直推（不做切片；batch>1 时把多帧合并成一次前向）。"""

    def __init__(self, model_path: str, cfg: dict):
        from ultralytics import YOLO   # 惰性导入

        self.cfg = cfg
        self.model = YOLO(model_path)

    @staticmethod
    def _to_arrays(r):
        if r.boxes is None or len(r.boxes) == 0:
            return np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int)
        return (r.boxes.xyxy.cpu().numpy(),
                r.boxes.conf.cpu().numpy(),
                r.boxes.cls.cpu().numpy().astype(int))

    def detect(self, frame, valid_mask=None):
        # 整帧直推没有切片可跳，valid_mask 无优化空间（遮罩已体现在像素上）
        return self.detect_batch([frame])[0]

    def detect_batch(self, frames, valid_masks=None):
        """多帧一次前向（batch 由 configs.yaml 的 direct.batch 控制）。

        结果按输入帧序返回；batch=1 时与逐帧直推完全等价。
        """
        cfg = self.cfg
        results = self.model.predict(
            list(frames), imgsz=cfg["imgsz"], conf=cfg["conf"], iou=cfg["iou"],
            device=cfg["device"], quantize=cfg["quantize"], max_det=cfg["max_det"],
            verbose=False,
        )
        return [self._to_arrays(r) for r in results]


class VideoPipeline:
    """端到端工作流: 检测 → 跨帧关联 → 去重计数 → 视频 + JSON。

    Args:
        model_path: 模型路径（None → 用 config 里的；空串 → 取最新登记权重）
        mode: "sahi" | "direct"（None → 用 config 里的）
        config: 覆盖 PIPELINE_CONFIG 的字段（嵌套 dict 支持局部覆盖）
        detector: 注入自定义检测器（测试用；给了就不再建模型）
    """

    def __init__(self, model_path=None, mode=None, config=None, detector=None):
        self.config = copy.deepcopy(PIPELINE_CONFIG)
        deep_update(self.config, config or {})
        if model_path is not None:
            self.config["model_path"] = model_path
        if mode is not None:
            self.config["mode"] = mode
        self.detector = detector
        self.out_dir = None

    # ------------------------------------------------------------------ 主流程

    def run(self, source: str, progress_cb=None, verbose: bool = True) -> dict:
        """跑完整工作流。

        Args:
            source: 视频路径
            progress_cb: 可选回调 progress_cb(已处理帧, 计划帧数, 已用秒数)，供 UI 接进度条
            verbose: 是否打印各阶段输出

        Returns:
            dict: 结果摘要（同时写入 result.json）
        """
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
        if verbose:
            self._print_header(video, model_path)

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
            results = _detect_batch(self.detector, [b[1] for b in batch],
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
                self._progress(processed, n_plan, t0, verbose, progress_cb)

        pending = []                       # 帧批缓冲: (frame_idx, 遮罩后帧, valid_mask, quad)
        while True:
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
        if verbose and n_plan:
            print()

        # ---------------- 4/6 轨迹后处理 ----------------
        tracks, pp_stats, id_map = postprocess_tracks(tracker.finalize(), cfg["tracker"])
        gate_stats = tracker.gate_summary()
        if verbose:
            print(f"  [4/6] 草地遮罩:   {masker.describe()}")
            if cfg["mask"]["filter_outside"]:
                print(f"  [4/6] 越界框过滤: 剔除 {masked_out} 个中心点落在四边形外的检测框")
            if gate_stats["confirm_enabled"] and gate_stats["confirm_window"] > 0:
                print(f"  [4/6] 稳定确认:   {gate_stats['confirm_window']} 帧窗口内需命中 "
                      f"{gate_stats['confirm_min_hits']} 帧 → 确认 {gate_stats['tracks_confirmed']} 条，"
                      f"剔除不稳定 {gate_stats['rejected_unconfirmed']} 条")
            else:
                print("  [4/6] 稳定确认:   已关闭（不做窗口门控）")
            if gate_stats.get("revived_online", 0):
                print(f"  [4/6] 在线复活:     归档轨迹被捞回 {gate_stats['revived_online']} 次（沿用旧 ID，不新建）")
            print(f"  [4/6] 轨迹后处理: 原始 {pp_stats['tracks_raw']} 条 → "
                  f"过滤短轨迹 {pp_stats['filtered_short']} / 合并断轨 {pp_stats['merged_broken']} / "
                  f"空间去重 {pp_stats['merged_spatial']} → 最终 {pp_stats['tracks_final']} 只")

        # ---------------- 5/6 重绘输出（视频 / 快照）----------------
        # 绘制统一挪到后处理之后: 用 id_map 把在线 ID 换成最终 ID 重画，
        # 保证画面里的框与 ID 和最终计数严格一致（未进入最终结果的轨迹不再出现）。
        writer = None
        if cfg["save_video"] or saver.enabled:
            if verbose:
                print(f"  [5/6] 重绘输出:   用最终 ID 重绘 {len(frame_visible)} 帧（视频/快照）")
            writer = render_pass(video, cfg, self.out_dir, frame_visible, quads, id_map,
                                 tracker, saver, fps, width, height, n_plan)
            if verbose and saver.enabled:
                snap = saver.summary()
                print(f"  [5/6] 检出帧快照: 有虫帧 {snap['count']} 张 → {snap['dir']}")

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
        if cfg["save_video"] and writer is not None:
            video_out = str(self.out_dir / cfg["video_name"])
        json_out = None
        if cfg["save_json"]:
            json_out = str(self.out_dir / cfg["json_name"])
        result["outputs"] = {"video": video_out, "json": json_out}

        if cfg["save_json"]:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with open(json_out, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        if verbose:
            self._print_footer(result, video_out, json_out)
        return result

    # ------------------------------------------------------------------ 辅助

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

    def _progress(self, done: int, total: int, t0: float, verbose: bool, cb):
        """进度输出（终端单行刷新 + 可选回调给 UI）。"""
        elapsed = time.time() - t0
        if cb is not None:
            cb(done, total, elapsed)
        if not verbose:
            return
        every = max(1, int(self.config["progress_every"]))
        if done % every and done != total:
            return
        if total:
            pct = 100.0 * done / total
            eta = elapsed / done * (total - done) if done else 0.0
        else:
            pct, eta = 0.0, 0.0
        print(f"\r  [3/6] 逐帧检测+关联: {done}/{total or '?'} 帧 ({pct:.1f}%) "
              f"已用 {elapsed:.1f}s ETA {eta:.1f}s", end="", flush=True)

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

    # ------------------------------------------------------------------ 打印

    def _print_header(self, video: Path, model_path: str) -> None:
        cfg = self.config
        print("=" * 66)
        print("  开始工作（检测 → 去重计数 → 视频/数据输出）")
        print("=" * 66)
        print(f"  [1/6] 输入视频:   {video}")
        print(f"  [1/6] 检测模型:   {model_path}")
        print(f"  [1/6] 检测模式:   {cfg['mode']}"
              + (f"（切片大小 {cfg['sahi']['slice_size']} 重叠 {cfg['sahi']['overlap_ratio']} "
                 f"batch = {cfg['sahi']['batch']}）"
                 if cfg["mode"] == "sahi"
                 else f"（整帧 imgsz={cfg['direct']['imgsz']} batch = {cfg['direct']['batch']}）"))
        print(f"  [1/6] 草地遮罩:   {self._describe_mask(cfg['mask'])}")
        print(f"  [1/6] 检出帧快照: {self._describe_snapshots(cfg['snapshots'])}")
        print(f"  [1/6] 输出目录:   {self.out_dir}")

    @staticmethod
    def _describe_snapshots(s: dict) -> str:
        if not s["enabled"]:
            return "未启用"
        return (f"启用（{s['fmt'].upper()} 质量 {s['quality']}）"
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

    @staticmethod
    def _print_footer(result: dict, video_out, json_out) -> None:
        counting = result["counting"]
        print(f"  [5/6] 推理视频:   {video_out or '（未输出）'}")
        print(f"  [6/6] 暂存数据:   {json_out or '（未输出）'}")
        print("-" * 66)
        print(f"  处理帧数:         {result['video']['processed_frames']}")
        print(f"  逐帧检测框累计:   {counting['raw_detections']} 次（去重前）")
        print(f"  去重后虫数:       {counting['unique_count']} 只")
        print(f"  耗时:             {result['elapsed_s']} s")
        print("=" * 66)


# ============================================================================
# CLI（由 cli.py 的 sahi / direct 子命令调用；两者共用本入口，mode 由命令名指定）
# ============================================================================

def detect_main(argv=None, mode=None):
    """sahi / direct 子命令的共用入口: mode 由命令名指定，缺省取配置里的 mode。"""
    mode = mode or PIPELINE_CONFIG["mode"]
    other = "direct" if mode == "sahi" else "sahi"
    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} {mode}",
        description=f"{'SAHI 切片' if mode == 'sahi' else '整帧直推'}检测 → 跨帧去重计数 → 推理视频 + 暂存数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"示例:\n"
               f"  python cli.py {mode} --source videos/test0.mp4                 # 模型留空 → 取最新登记权重\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --model pest1\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --model best.pt\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --stride 2 --no-video   # 抽帧 + 只出数据\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --no-mask               # 关闭草地遮罩\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --no-snapshots          # 不保存检出帧快照\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --mask-refresh 0        # 只在首帧拟合后固定\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --mask-refresh 30       # 每 30 帧重拟合（省算力）\n"
               f"换另一种检测模式: python cli.py {other} --source videos/test0.mp4\n"
               f"默认值唯一来源 = 项目根 configs.yaml（改参数只改那里）\n"
               f"遮罩调参预览: python cli.py roi --source videos/test0.mp4 --out runs/roi_preview.png",
    )
    parser.add_argument("--source", required=True, help="输入视频路径")
    parser.add_argument("--model", "--weights", default=PIPELINE_CONFIG["model_path"], metavar="PATH",
                        help="检测模型路径（留空 = 取最新登记权重；也可写 pest1 这类登记名）")
    parser.add_argument("--output", default=PIPELINE_CONFIG["output_root"], metavar="DIR",
                        help="输出根目录")
    parser.add_argument("--stride", type=int, default=PIPELINE_CONFIG["frame_stride"],
                        help="抽帧步长（1=逐帧）")
    parser.add_argument("--max-frames", type=int, default=PIPELINE_CONFIG["max_frames"],
                        help="最多处理帧数（0=全部）")
    parser.add_argument("--conf", type=float, default=None, help="覆盖检测置信度阈值")
    parser.add_argument("--device", default=None, help="推理设备（0/1/cpu）")
    parser.add_argument("--no-mask", action="store_true", help="关闭草地遮罩（整帧推理）")
    parser.add_argument("--mask-refresh", type=int, default=None, metavar="N",
                        help="每 N 帧重新拟合草地四边形（1=逐帧，默认；0=首帧拟合后固定）")
    parser.add_argument("--no-snapshots", action="store_true",
                        help="不保存检出帧快照（默认每只虫存一张带框标注的整帧）")
    parser.add_argument("--no-confirm", action="store_true",
                        help="关闭稳定确认门控（不再要求窗口内稳定命中）")
    parser.add_argument("--confirm-window", type=int, default=None, metavar="N",
                        help="稳定确认观察窗口帧数（默认 0 = 不启用窗口门控）")
    parser.add_argument("--confirm-min-hits", type=int, default=None, metavar="N",
                        help="窗口内最少命中帧数（默认 0；与窗口相等即要求连续全中）")
    parser.add_argument("--no-video", action="store_true", help="不输出推理视频")
    parser.add_argument("--no-json", action="store_true", help="不输出暂存数据 JSON")
    args = parser.parse_args(argv)

    if not os.path.exists(args.source):
        print(f"\n[错误] 视频文件不存在: {args.source}\n")
        return

    over = {
        "output_root": args.output,
        "frame_stride": args.stride,
        "max_frames": args.max_frames,
        "save_video": not args.no_video,
        "save_json": not args.no_json,
    }
    if args.conf is not None:
        over["sahi"] = {"conf": args.conf}
        over["direct"] = {"conf": args.conf}
    if args.device is not None:
        over.setdefault("sahi", {})["device"] = args.device
        over.setdefault("direct", {})["device"] = args.device
    if args.no_mask:
        over["mask"] = {"enabled": False}
    if args.mask_refresh is not None:
        over.setdefault("mask", {})["refresh_every"] = args.mask_refresh
    if args.no_snapshots:
        over["snapshots"] = {"enabled": False}
    if args.no_confirm:
        over.setdefault("tracker", {})["confirm_enabled"] = False
    if args.confirm_window is not None:
        over.setdefault("tracker", {})["confirm_window"] = args.confirm_window
    if args.confirm_min_hits is not None:
        over.setdefault("tracker", {})["confirm_min_hits"] = args.confirm_min_hits

    try:
        pipe = VideoPipeline(model_path=args.model, mode=mode, config=over)
        result = pipe.run(args.source)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"\n[错误] {e}\n")
        return

    if result["counting"]["unique_count"] == 0:
        print(f"  [提示] 未检出任何目标。可尝试: 降低 conf、换 python cli.py {other}、"
              "确认模型类别与目标匹配")
        c = result["counting"]
        if c.get("confirm_enabled") and c.get("rejected_unconfirmed", 0) > 0:
            print(f"  [提示] 稳定确认门控剔除了 {c['rejected_unconfirmed']} 条不稳定轨迹，"
                  f"可尝试 --confirm-min-hits 调小，或 --no-confirm 关闭门控")
