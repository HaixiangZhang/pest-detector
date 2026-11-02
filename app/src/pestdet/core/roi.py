"""roi — 草地四边形 ROI 遮罩（自动绿色分割 → 四边形拟合 → 区域外涂黑 + 越界框过滤）。

被 core.pipeline 逐帧复用（参数由调用方注入，本模块不读全局配置）:

    masker = GrassMasker(cfg["mask"])
    masked = masker.apply(frame)                       # 区域外涂黑，几何不变
    boxes, scores, labels = detector.detect(masked, valid_mask=masker.mask)
    boxes, scores, labels = filter_boxes_inside_quad(boxes, scores, labels, masker.quad)

调参预览（把四边形画到首帧上，确认绿色分割是否贴合草地）由 cli 的 roi 子命令调用
``load_frame`` + ``make_preview`` 组装，本模块只负责几何与绘制、不写盘、不 argparse。

顶层只 import cv2/numpy 与 infra.imageio（保持模块轻量）。
"""

from pathlib import Path

import cv2
import numpy as np

from pestdet.infra.imageio import imread


# ---------------------------------------------------------------- 四边形拟合

def detect_grass_quad(frame: np.ndarray, cfg: dict) -> np.ndarray | None:
    """从单帧中提取绿色草地最大连通域并拟合成四边形。

    分割在 detect_scale 倍降采样图上进行（默认 1/4），返回的四边形已换算回原帧坐标。
    草地边界是粗区域，降采样对结果几乎无影响，但 4K 上形态学开销能降一个量级。

    Returns:
        (4, 2) int32 四边形顶点（原帧坐标）；拟合失败返回 None。
    """
    scale = float(cfg.get("detect_scale") or 1.0)
    scale = min(max(scale, 0.05), 1.0)
    work = frame if scale >= 1.0 else cv2.resize(
        frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    lower = np.array(cfg["hsv_lower"], dtype=np.uint8)
    upper = np.array(cfg["hsv_upper"], dtype=np.uint8)
    green = cv2.inRange(hsv, lower, upper)

    k = int(cfg["morph_kernel"])
    if k > 1:
        k = max(3, int(round(k * scale)))       # 核尺寸同比缩放，保持等效平滑范围
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, kernel)   # 补洞（草地里的虫体/阴影）
        green = cv2.morphologyEx(green, cv2.MORPH_OPEN, kernel)    # 去噪（零散绿色噪点）

    contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    cnt = max(contours, key=cv2.contourArea)
    h, w = work.shape[:2]
    area_ratio = cv2.contourArea(cnt) / float(h * w)     # 占比与分辨率无关，阈值无需换算
    if not (cfg["min_area_ratio"] <= area_ratio <= cfg["max_area_ratio"]):
        return None

    quad = _fit_quad(cnt, cfg["approx_eps_ratio"])
    if scale < 1.0:
        quad = np.round(quad.astype(np.float32) / scale).astype(np.int32)
    return quad


def _fit_quad(cnt: np.ndarray, eps_ratio: float) -> np.ndarray:
    """凸包 → approxPolyDP 取 4 顶点；点数收敛不到 4 时退化为最小外接旋转矩形。

    先取凸包有两个好处: 抹掉草地边缘的锯齿/缺口让四边形更稳；保证结果凸，
    后面按 TL→TR→BR→BL 重排顶点时不会把多边形排成自交。
    """
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    if peri > 0:
        for eps in (eps_ratio, eps_ratio * 2, 0.03, 0.05, 0.08):
            approx = cv2.approxPolyDP(hull, eps * peri, True)
            if len(approx) == 4:
                return order_quad(approx.reshape(4, 2).astype(np.float32))

    rect = cv2.minAreaRect(hull)                 # 兜底: 旋转矩形本身即四边形
    return order_quad(cv2.boxPoints(rect).astype(np.float32))


def order_quad(pts: np.ndarray) -> np.ndarray:
    """顶点按 TL→TR→BR→BL 重排，让日志/JSON 里的坐标顺序稳定可读。

    用的是 x+y / x-y 极值法，四边形明显倾斜时"哪个是 TL"会不精确；但填充
    （fillPoly）与内外判定（pointPolygonTest）都与顶点顺序无关，只要求多边形不自交
    —— 输入来自凸包，重排后仍是简单多边形，所以这里只影响可读性。
    """
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = pts[:, 0] - pts[:, 1]
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.int32)


def expand_quad(quad: np.ndarray, ratio: float) -> np.ndarray:
    """以质心为中心按比例外扩（ratio>0 放大，<0 收缩）。"""
    quad = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    if not ratio:
        return quad.astype(np.int32)
    center = quad.mean(axis=0)
    return (center + (quad - center) * (1.0 + float(ratio))).astype(np.int32)


def build_mask(shape, quad: np.ndarray) -> np.ndarray:
    """生成 ROI 掩码: 四边形内部 255、外部 0。"""
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [np.asarray(quad, dtype=np.int32).reshape(-1, 1, 2)], 255)
    return mask


def apply_mask(frame: np.ndarray, mask: np.ndarray, fill=0) -> np.ndarray:
    """区域外涂 fill（默认黑）。只改像素值不动几何，检测框坐标仍是原帧坐标系。"""
    out = np.empty_like(frame)
    out[:] = fill
    cv2.copyTo(frame, mask, out)      # mask 非零处保留原像素
    return out


def quad_area_ratio(quad: np.ndarray, shape) -> float:
    """四边形面积占全帧比例（用于日志/结果记录）。"""
    mask = build_mask(shape, quad)
    return float(np.count_nonzero(mask)) / float(mask.size)


def filter_boxes_inside_quad(boxes, scores, labels, quad, fill_expand=0.0):
    """丢弃中心点落在四边形外的检测框（quad=None 时原样返回）。"""
    if quad is None or len(boxes) == 0:
        return boxes, scores, labels

    poly = expand_quad(quad, fill_expand).astype(np.float32)
    cx = (boxes[:, 0] + boxes[:, 2]) / 2.0
    cy = (boxes[:, 1] + boxes[:, 3]) / 2.0
    keep = np.fromiter(
        (cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0
         for x, y in zip(cx, cy)),
        dtype=bool, count=len(boxes),
    )
    return boxes[keep], scores[keep], labels[keep]


# ---------------------------------------------------------------- 遮罩器

class GrassMasker:
    """逐帧草地遮罩器: 按 refresh_every 重新拟合四边形（默认逐帧），帧间复用最近一次结果。

    拟合失败（绿地区域过小/过大）或面积突变被守卫拦下时，沿用上一帧四边形，绝不因为
    单帧分割异常而放弃遮罩；始终没拟合成功过则退化为不遮罩（保守策略: 宁可多检，不可漏检）。

    Args:
        config: configs.yaml 的 mask 节（必填，由调用方注入完整配置）
    """

    def __init__(self, config: dict):
        self.cfg = dict(config)
        self.quad = None            # (4,2) int32 或 None
        self.mask = None            # (H,W) uint8 或 None，供 SAHI 跳过区域外切片
        self._mask_shape = None     # (H, W) 拟合时帧尺寸，供面积比校验
        self._seen = 0              # 已调用次数（用于 refresh_every 判定）
        self.refit_count = 0
        self.fail_count = 0
        self.jitter_reject_count = 0

    @property
    def enabled(self) -> bool:
        return bool(self.cfg["enabled"])

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """返回遮罩后的帧（未启用或从未拟合成功时原样返回）。"""
        if not self.enabled:
            return frame

        if self.cfg["mode"] == "manual":
            self._use_manual_quad(frame.shape)      # 手动模式不做自动拟合
        else:
            refresh = int(self.cfg["refresh_every"])
            # 0 = 只在首帧拟合一次；N>0 = 每 N 帧重拟合（N=1 即逐帧）
            if self.quad is None or (refresh > 0 and self._seen % refresh == 0):
                self._refit(frame)

        self._seen += 1
        if self.quad is None:
            return frame
        return apply_mask(frame, self.mask, self.cfg["fill"])

    def _use_manual_quad(self, shape) -> None:
        if self.quad is not None:
            return
        pts = self.cfg.get("quad") or []
        if len(pts) != 4:
            return
        self._set_quad(np.asarray(pts, dtype=np.int32).reshape(4, 2), shape)

    def _refit(self, frame: np.ndarray) -> None:
        quad = detect_grass_quad(frame, self.cfg)
        if quad is None:
            self.fail_count += 1
            return
        if self.quad is not None and not self._area_ok(quad):
            self.jitter_reject_count += 1
            return
        self._set_quad(quad, frame.shape)
        self.refit_count += 1

    def _area_ok(self, quad: np.ndarray) -> bool:
        """面积突变守卫。

        逐帧重拟合时，单帧分割异常（有人/大块阴影/反光进入画面）会让四边形突然放大或
        缩小，此时若直接采用，当帧真实目标会被 filter_outside 全部剔掉、轨迹断链。
        面积比超阈值就弃用本帧结果、沿用上一帧四边形（max_area_jump=0 关闭守卫）。
        """
        jump = float(self.cfg["max_area_jump"])
        if jump <= 0:
            return True
        prev = abs(cv2.contourArea(np.asarray(self.quad, dtype=np.float32)))
        cur = abs(cv2.contourArea(np.asarray(quad, dtype=np.float32)))
        if prev <= 0 or cur <= 0:
            return True
        return max(cur / prev, prev / cur) <= jump

    def _set_quad(self, quad: np.ndarray, shape) -> None:
        self.quad = expand_quad(quad, self.cfg["expand_ratio"])
        self.mask = build_mask(shape, self.quad)
        self._mask_shape = shape[:2]

    def describe(self) -> str:
        if not self.enabled:
            return "未启用"
        if self.quad is None:
            if self.cfg["mode"] == "manual":
                return "启用（manual）但 quad 坐标无效（需 4 个点）→ 未遮罩"
            return f"启用但拟合失败（{self.fail_count} 次）→ 未遮罩"
        refresh = int(self.cfg["refresh_every"])
        how = "逐帧重拟合" if refresh == 1 else (
            f"每 {refresh} 帧重拟合" if refresh > 0 else "首帧拟合后固定")
        ratio = quad_area_ratio(self.quad, self._mask_shape)
        return (f"启用（{self.cfg['mode']}，{how}）末帧四边形 {self.quad.tolist()} "
                f"占帧 {ratio:.1%}，重拟合 {self.refit_count} 次 / 失败 {self.fail_count} 次 / "
                f"面积突变弃用 {self.jitter_reject_count} 次")


# ---------------------------------------------------------------- 调参预览支撑

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_frame(source: str, frame_idx: int = 0) -> np.ndarray:
    """读视频第 frame_idx 帧；图片源直接读图（供 ROI 调参预览用）。"""
    if Path(source).suffix.lower() in _IMAGE_EXTS:
        return imread(source)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {source}")
    if frame_idx > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"无法读取第 {frame_idx} 帧: {source}")
    return frame


def make_preview(frame: np.ndarray, mask_cfg: dict) -> tuple:
    """生成 ROI 预览图: 左=原帧+四边形轮廓，右=遮罩后帧。

    Returns:
        (preview, quad, cost_ms, fitted)
        quad: 拟合出的四边形（含外扩）；拟合失败时为零四边形
        cost_ms: 拟合耗时（毫秒）
        fitted: 是否拟合成功（False 表示退化为零四边形，调用方可据此提示调参）
    """
    import time

    t0 = time.perf_counter()
    quad = detect_grass_quad(frame, mask_cfg)
    cost_ms = (time.perf_counter() - t0) * 1000
    fitted = quad is not None
    if not fitted:
        quad = np.array([[0, 0], [0, 0], [0, 0], [0, 0]], dtype=np.int32)

    quad = expand_quad(quad, mask_cfg["expand_ratio"])
    mask = build_mask(frame.shape, quad)
    left = frame.copy()
    cv2.polylines(left, [quad.reshape(-1, 1, 2)], True, (0, 0, 255), 3)
    right = apply_mask(frame, mask, mask_cfg["fill"])

    k = max(1.0, frame.shape[1] / 1280.0)
    for img, text in ((left, "quad"), (right, "masked")):
        cv2.putText(img, text, (int(20 * k), int(50 * k)), cv2.FONT_HERSHEY_SIMPLEX,
                    1.2 * k, (0, 255, 255), max(1, int(2 * k)), cv2.LINE_AA)

    sep = np.zeros((frame.shape[0], 6, 3), dtype=np.uint8)
    return np.hstack([left, sep, right]), quad, cost_ms, fitted