"""sahi — 4K 切片推理引擎 + 加权框融合。

由 core.detector 的 _SahiDetector 复用（SAHIInferenceEngine.detect →
weighted_boxes_fusion），是"切片检测"模式的核心。整帧直推（direct）不走这里。

顶层只 import cv2/numpy 与轻量模块（ultralytics 在 SAHIInferenceEngine.__init__
内惰性导入，保证 import 本模块不会拉起 torch）。
"""

import numpy as np

from pestdet.core.tracker import bbox_iou
from pestdet.infra.imageio import imread


def weighted_boxes_fusion(
    boxes_list: list,
    scores_list: list,
    labels_list: list,
    iou_thr: float = 0.55,
    skip_box_thr: float = 0.0,
    conf_type: str = "avg",
) -> tuple:
    """Weighted Boxes Fusion — 将重叠检测框按置信度加权融合。

    Args:
        boxes_list:   (N, 4) — [x1, y1, x2, y2] 绝对坐标
        scores_list:  (N,)  — 置信度
        labels_list:  (N,)  — 类别 ID
        iou_thr:      IoU 阈值（高于此值视为同一目标）
        skip_box_thr: 跳过置信度低于此值的框
        conf_type:    融合置信度计算方式 "avg"(均值) / "max" / "box_and_model_avg"

    Returns:
        fused_boxes:  (M, 4)
        fused_scores: (M,)
        fused_labels: (M,)
    """
    if len(boxes_list) == 0:
        return np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int)

    boxes = np.array(boxes_list, dtype=np.float32)
    scores = np.array(scores_list, dtype=np.float32)
    labels = np.array(labels_list, dtype=int)

    if skip_box_thr > 0:
        mask = scores > skip_box_thr
        boxes, scores, labels = boxes[mask], scores[mask], labels[mask]

    if len(boxes) == 0:
        return np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int)

    order = np.argsort(-scores)
    boxes, scores, labels = boxes[order], scores[order], labels[order]

    fused_boxes, fused_scores, fused_labels = [], [], []
    used = np.zeros(len(boxes), dtype=bool)

    for i in range(len(boxes)):
        if used[i]:
            continue

        cluster_indices = [i]
        for j in range(i + 1, len(boxes)):
            if used[j] or labels[j] != labels[i]:
                continue
            if bbox_iou(boxes[i], boxes[j]) >= iou_thr:
                cluster_indices.append(j)

        cluster_boxes = boxes[cluster_indices]
        cluster_scores = scores[cluster_indices]

        weights = cluster_scores / cluster_scores.sum()
        fused_box = (cluster_boxes * weights[:, np.newaxis]).sum(axis=0)

        if conf_type == "avg":
            fused_score = cluster_scores.mean()
        elif conf_type == "max":
            fused_score = cluster_scores.max()
        else:  # "box_and_model_avg"
            fused_score = (cluster_scores.mean() + cluster_scores.max()) / 2.0

        fused_boxes.append(fused_box)
        fused_scores.append(fused_score)
        fused_labels.append(labels[i])

        for j in cluster_indices:
            used[j] = True

    return (
        np.array(fused_boxes, dtype=np.float32),
        np.array(fused_scores, dtype=np.float32),
        np.array(fused_labels, dtype=int),
    )


def non_max_suppression(
    boxes: np.ndarray,
    scores: np.ndarray,
    labels: np.ndarray,
    iou_thr: float = 0.5,
) -> tuple:
    """逐类 NMS — 与 WBF 互补，用于单尺度快速去重。"""
    if len(boxes) == 0:
        return np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int)

    unique_labels = np.unique(labels)
    keep_indices = []

    for cls_id in unique_labels:
        cls_mask = labels == cls_id
        cls_boxes = boxes[cls_mask]
        cls_scores = scores[cls_mask]
        cls_indices = np.where(cls_mask)[0]

        order = np.argsort(-cls_scores)
        while len(order) > 0:
            best_idx = order[0]
            keep_indices.append(cls_indices[best_idx])
            if len(order) == 1:
                break

            best_box = cls_boxes[best_idx]
            ious = np.array([bbox_iou(best_box, cls_boxes[j]) for j in order[1:]])
            order = order[1:][ious < iou_thr]

    keep_indices = np.array(sorted(keep_indices))
    return boxes[keep_indices], scores[keep_indices], labels[keep_indices]


class SAHIInferenceEngine:
    """SAHI 切片推理引擎。

    支持:
        - 单尺度和多尺度切片推理
        - 切片批处理（同帧切片合并成一次前向，减少 GPU 空转）
        - NMS 或 WBF 融合
        - 精度量化加速（FP16 / INT8）
    """

    def __init__(
        self,
        model_path: str,
        slice_size: int = 640,
        overlap_ratio: float = 0.2,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.5,
        batch: int = 4,
        device: int = 0,
        quantize: int = None,
        fusion_method: str = "wbf",  # "wbf" | "nms"
        min_coverage: float = 0.5,  # 切片尺寸不足时的最小保留比例
    ):
        """
        Args:
            model_path: YOLO 权重路径
            slice_size: 切片尺寸（正方形）
            overlap_ratio: 重叠率（0.15-0.25 推荐）
            conf_threshold: 检测置信度阈值
            iou_threshold: 融合 IoU 阈值
            batch: 切片批大小（同帧切片合并成一次前向；显存吃紧调小）
            device: GPU 设备
            quantize: 精度量化，None=FP32（默认）/ 16=FP16 / 8=INT8
            fusion_method: 融合方法 "wbf" 或 "nms"
            min_coverage: 边缘切片至少覆盖完整切片的比例
        """
        from ultralytics import YOLO  # 惰性导入，保持模块顶层轻量

        self.model = YOLO(model_path)
        self.slice_size = slice_size
        self.overlap_ratio = overlap_ratio
        self.conf = conf_threshold
        self.iou = iou_threshold
        self.batch = max(1, int(batch))
        self.device = device
        self.quantize = quantize
        self.fusion_method = fusion_method
        self.min_coverage = min_coverage

    def close(self) -> None:
        """释放模型引用（配合 detector.close 回收显存；幂等）。"""
        self.model = None

    def detect(
        self,
        image,
        multi_scale: bool = False,
        scale_sizes: list = None,
        valid_mask: np.ndarray = None,
    ) -> dict:
        """对单张图片进行 SAHI 推理。

        Args:
            image: 图片路径 (str) 或 numpy 数组 (H, W, 3)
            multi_scale: 是否启用多尺度切片
            scale_sizes: 多尺度切片尺寸列表，如 [640, 960, 1280]
            valid_mask: 可选 ROI 掩码 (H, W) uint8，非零 = 有效区域；
                        完全落在有效区域外的切片直接跳过（黑块推理纯浪费算力，且可能产生边缘伪框）

        Returns:
            {
                "boxes":  np.ndarray (M, 4) — [x1, y1, x2, y2] 原图坐标
                "scores": np.ndarray (M,)  — 置信度
                "labels": np.ndarray (M,)  — 类别 ID
            }
        """
        if isinstance(image, str):
            img = imread(image)
        else:
            img = image.copy()

        H, W = img.shape[:2]

        all_boxes, all_scores, all_labels = [], [], []

        if multi_scale:
            sizes = scale_sizes if scale_sizes else [640, 960, 1280]
            for sz in sizes:
                boxes, scores, labels = self._detect_single_scale(img, sz, H, W, valid_mask)
                all_boxes.extend(boxes)
                all_scores.extend(scores)
                all_labels.extend(labels)
        else:
            boxes, scores, labels = self._detect_single_scale(img, self.slice_size, H, W, valid_mask)
            all_boxes.extend(boxes)
            all_scores.extend(scores)
            all_labels.extend(labels)

        if len(all_boxes) == 0:
            return {
                "boxes": np.zeros((0, 4)),
                "scores": np.zeros(0),
                "labels": np.zeros(0, dtype=int),
            }

        if self.fusion_method == "wbf":
            fused_boxes, fused_scores, fused_labels = weighted_boxes_fusion(
                all_boxes, all_scores, all_labels, iou_thr=self.iou
            )
        else:
            fused_boxes, fused_scores, fused_labels = non_max_suppression(
                np.array(all_boxes), np.array(all_scores),
                np.array(all_labels, dtype=int), iou_thr=self.iou,
            )

        return {
            "boxes": fused_boxes,
            "scores": fused_scores,
            "labels": fused_labels,
        }

    def _detect_single_scale(
        self, img: np.ndarray, slice_sz: int, img_h: int, img_w: int,
        valid_mask: np.ndarray = None,
    ) -> tuple:
        """单尺度切片推理（valid_mask 非空时跳过完全落在 ROI 外的切片）。

        同帧切片尺寸一致（边缘切片已零填充到 slice_sz），按 self.batch 分组后合并成
        一次 predict(list) 前向（ultralytics 对 list 输入的批大小 = 列表长度），
        避免逐切片 batch=1 调用让 GPU 在两次调用之间空转。
        """
        step = max(int(slice_sz * (1 - self.overlap_ratio)), 1)
        boxes, scores, labels = [], [], []

        # 阶段一: 切出本帧全部有效切片，记录各自的原图偏移
        patches, offsets = [], []
        for y in range(0, img_h, step):
            for x in range(0, img_w, step):
                x1, y1 = x, y
                x2, y2 = min(x + slice_sz, img_w), min(y + slice_sz, img_h)
                patch_w, patch_h = x2 - x1, y2 - y1

                if patch_w < slice_sz * self.min_coverage or patch_h < slice_sz * self.min_coverage:
                    continue

                # 跳过完全在 ROI 外的切片（内容是纯填充色，推理无意义）
                if valid_mask is not None and not valid_mask[y1:y2, x1:x2].any():
                    continue

                patch = img[y1:y2, x1:x2]
                if patch_w < slice_sz or patch_h < slice_sz:
                    padded = np.zeros((slice_sz, slice_sz, 3), dtype=np.uint8)
                    padded[:patch_h, :patch_w] = patch
                    patch = padded

                patches.append(patch)
                offsets.append((x1, y1))

        # 阶段二: 按 batch 分组前向，再把每片检出框平移到原图坐标
        for i in range(0, len(patches), self.batch):
            results = self.model.predict(
                patches[i:i + self.batch],
                imgsz=slice_sz,
                conf=self.conf,
                iou=self.iou,
                device=self.device,
                quantize=self.quantize,
                verbose=False,
            )

            for res, (x1, y1) in zip(results, offsets[i:i + self.batch]):
                dets = res.boxes
                if dets is None or len(dets) == 0:
                    continue

                det_xyxy = dets.xyxy.cpu().numpy()
                det_conf = dets.conf.cpu().numpy()
                det_cls = dets.cls.cpu().numpy().astype(int)

                # 边缘切片是零填充补齐（内容 1:1 放在左上角，未缩放），
                # 且方形切片在 imgsz=slice_sz 下 letterbox 为恒等变换，
                # 故回原图只需加切片偏移，不能乘 patch_w/slice_sz 缩放（否则框向切片原点收缩错位）
                det_xyxy[:, 0] += x1
                det_xyxy[:, 1] += y1
                det_xyxy[:, 2] += x1
                det_xyxy[:, 3] += y1

                boxes.extend(det_xyxy.tolist())
                scores.extend(det_conf.tolist())
                labels.extend(det_cls.tolist())

        return boxes, scores, labels