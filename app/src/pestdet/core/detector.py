"""detector — 检测器构建（SAHI 切片 / 整帧直推）。

自原 pipeline.py 迁入。检测模式只决定用哪个检测器，其余流程（遮罩 → 检测 →
跨帧去重计数 → 产物）完全共用（见 core.pipeline）。

检测器契约:
    detect(frame_bgr, valid_mask=None) -> (boxes(N,4) float, scores(N,) float, labels(N,) int)
    detect_batch(frames, valid_masks=None) -> [同上，逐帧对应]（可选，缺省逐帧回退 detect）
    valid_mask 为可选 ROI 掩码 (H,W) uint8，非零 = 有效区域；
    仅用于跳过无效区域的算力优化，不改变输出坐标系。

顶层不 import ultralytics（_DirectDetector 惰性导入，保持模块轻量）。
"""

import numpy as np

from pestdet.core.sahi import SAHIInferenceEngine


def release_cuda_cache() -> None:
    """把空闲显存块还给驱动（长驻服务每次任务结束必须调用）。

    背景: PyTorch 的缓存分配器在张量释放后仍保留显存块，nvidia-smi 看不到下降，
    只有 empty_cache() 才把空闲块归还驱动。调用前须先把模型引用置 None 并 gc，
    否则对象仍被引用、显存不会真正释放。
    注意: CUDA context 本身保留到进程退出（属正常现象），故不会降到 0。
    """
    import gc

    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:                  # torch 未装 / CUDA 不可用 → 无需处理
        pass


def detect_batch(detector, frames, masks) -> list:
    """统一批量检测入口: 检测器实现了 detect_batch 就用它，否则逐帧回退到 detect。

    回退分支是为"注入自定义检测器"留的（只需实现单帧 detect 即可接入）。
    """
    fn = getattr(detector, "detect_batch", None)
    if fn is not None:
        return fn(frames, masks)
    return [detector.detect(f, valid_mask=m) for f, m in zip(frames, masks)]


def build_detector(mode: str, model_path: str, config: dict):
    """按模式构建检测器（返回带 detect / detect_batch 的对象）。

    Args:
        mode: "sahi" | "direct"
        model_path: 权重路径
        config: 完整部署配置 dict（需含 sahi / direct 两节）
    """
    if mode == "sahi":
        return _SahiDetector(model_path, config["sahi"])
    if mode == "direct":
        return _DirectDetector(model_path, config["direct"])
    raise ValueError(f"未知检测模式: {mode}（可选: sahi / direct）")


class _SahiDetector:
    """SAHI 切片检测（复用 core.sahi.SAHIInferenceEngine）。"""

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

    def close(self) -> None:
        """释放模型并回收显存（幂等）。"""
        engine = getattr(self, "engine", None)
        if engine is not None:
            engine.close()
        self.engine = None
        release_cuda_cache()


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

    def close(self) -> None:
        """释放模型并回收显存（幂等）。"""
        self.model = None
        release_cuda_cache()