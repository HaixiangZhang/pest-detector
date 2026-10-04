"""tracker — 轻量 IoU 关联器 + 轨迹后处理三步清洗（视频计数去重的共享底座）。

设计取舍:
    - 官方 ByteTrack（ultralytics model.track）只吃"整帧直推"的检测结果；
      SAHI 切片推理是外部检测，喂不进 model.track，所以这里自带一个关联器。
    - 关联逻辑沿用 ByteTrack 的两轮匹配思路（高分框先配、低分框救回），
      叠加匀速预测 + 起步期宽松阈值，适配小目标（~33px）的帧间位移。
    - 匹配用贪心而非匈牙利: 稀疏场景（平均 <2 个/帧）下结果等价，且零新增依赖。
    - 后处理三步（短轨迹过滤 / 断轨合并 / 空间去重）做成模块级函数，
      供 pipeline.py 视频工作流（SAHI / 整帧直推两条路径）共用。

调用方:
    pipeline.py（项目根，视频检测实现）   ← 逐帧检测结果的关联 + 轨迹后处理
顶层只 import numpy 与 utils.config（无 ultralytics 依赖）。
"""

import numpy as np

from utils.config import PIPELINE_CONFIG

# ============================================================================
# 几何工具
# ============================================================================

def bbox_center(bbox) -> np.ndarray:
    """框 (x1, y1, x2, y2) 的中心点。"""
    x1, y1, x2, y2 = bbox
    return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0], dtype=float)


def center_dist(a, b) -> float:
    """两点欧氏距离。"""
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def bbox_iou(box_a, box_b) -> float:
    """两个框的 IoU。"""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def boxes_envelope(bboxes: list) -> tuple:
    """一列检测框的外接矩形。

    注意用框而非中心点: 静止目标的中心点包络面积趋近 0，
    会让空间去重的 IoU 恒为 0 而失效。
    """
    xs1 = [b[0] for b in bboxes]
    ys1 = [b[1] for b in bboxes]
    xs2 = [b[2] for b in bboxes]
    ys2 = [b[3] for b in bboxes]
    return (min(xs1), min(ys1), max(xs2), max(ys2))


def iou_matrix(boxes_a, boxes_b) -> np.ndarray:
    """两组框的 IoU 矩阵 (N, M)。boxes 为 (N,4)/(M,4) 数组。"""
    a = np.asarray(boxes_a, dtype=float).reshape(-1, 4)
    b = np.asarray(boxes_b, dtype=float).reshape(-1, 4)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=float)

    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])

    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = np.clip(a[:, 2] - a[:, 0], 0, None) * np.clip(a[:, 3] - a[:, 1], 0, None)
    area_b = np.clip(b[:, 2] - b[:, 0], 0, None) * np.clip(b[:, 3] - b[:, 1], 0, None)
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def match_score_matrix(boxes_a, boxes_b, dist_gate: float = 1.5) -> np.ndarray:
    """匹配分数矩阵 = max(IoU, 距离分数)。

    距离分数 = 1 - 中心距离 / (dist_gate × 框平均边长)，下限截断到 0。
    纯 IoU 在小目标 + 抽帧/快速位移时会骤降到 0 导致断链，
    距离项用来兜住"位移大但确实是同一目标"的连接。
    """
    a = np.asarray(boxes_a, dtype=float).reshape(-1, 4)
    b = np.asarray(boxes_b, dtype=float).reshape(-1, 4)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=float)

    iou = iou_matrix(a, b)
    ca = np.stack([(a[:, 0] + a[:, 2]) / 2, (a[:, 1] + a[:, 3]) / 2], axis=1)
    cb = np.stack([(b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2], axis=1)
    size_a = ((a[:, 2] - a[:, 0]) + (a[:, 3] - a[:, 1])) / 2
    size_b = ((b[:, 2] - b[:, 0]) + (b[:, 3] - b[:, 1])) / 2
    size = np.minimum(size_a[:, None], size_b[None, :])       # 取小框尺寸，避免大框过度吸附属物

    dist = np.linalg.norm(ca[:, None, :] - cb[None, :, :], axis=2)
    scale = np.maximum(dist_gate * size, 1e-6)
    return np.maximum(iou, np.clip(1.0 - dist / scale, 0.0, None))


def _greedy_match(score: np.ndarray, row_thresh: np.ndarray) -> list:
    """按匹配分数降序贪心配对，返回 [(row, col)]。

    row_thresh: 每行的分数阈值（不同轨迹可用不同阈值）。
    稀疏场景下与匈牙利算法结果等价，且不引入 scipy 依赖。
    """
    pairs = []
    if score.size == 0:
        return pairs
    used_row = np.zeros(score.shape[0], dtype=bool)
    used_col = np.zeros(score.shape[1], dtype=bool)
    for flat in np.argsort(-score, axis=None):
        r, c = np.unravel_index(int(flat), score.shape)
        if used_row[r] or used_col[c] or score[r, c] < row_thresh[r]:
            continue
        used_row[r] = True
        used_col[c] = True
        pairs.append((int(r), int(c)))
    return pairs


# ============================================================================
# 轻量 IoU 关联器（ByteTrack 风格两轮匹配）
# ============================================================================

class IoUTracker:
    """逐帧关联器: 喂入每帧检测框，输出稳定的 track ID。

    工作方式:
        1. 匀速预测: 用轨迹速度把上一帧的框外推到本帧位置
        2. 第一轮匹配: 高分框（>= high_thresh）与预测框按匹配分数配对
           （分数 = max(IoU, 距离门控)，兼顾重叠与位移）
        3. 第二轮匹配: 低分框（>= low_thresh）救回第一轮没配上的轨迹
        4. 幸存/新建: 未匹配轨迹累计丢失帧数（超 track_buffer 归档）；
           未匹配的高分框建新轨迹（速度未建立时用 boot_match_iou 宽松阈值起步）
        5. 稳定确认（可开关）: 轨迹需在 confirm_window 帧内命中 confirm_min_hits 次
           才被标记 confirmed；finalize() 与 visible_confirmed() 都只放行 confirmed 轨迹

    Args:
        config: 覆盖 configs.yaml 的 tracker 节（只覆盖传入的 key）
    """

    def __init__(self, config: dict = None):
        cfg = dict(PIPELINE_CONFIG["tracker"])
        if config:
            cfg.update({k: v for k, v in config.items() if k in cfg})
        self.config = cfg
        self.tracks = {}          # tid -> track dict（活跃/暂丢失）
        self.removed = {}         # tid -> track dict（超期归档，历史保留）
        self._next_id = 1
        self._revive_count = 0    # 在线复活次数（归档轨迹被捞回的次数）
        self.frame_idx = -1

    # ---------------------------------------------------------------- 主循环

    def update(self, boxes, scores, labels=None) -> dict:
        """喂入一帧检测，返回本帧可见轨迹 {tid: (bbox, score)}。

        Args:
            boxes:  (N, 4) [x1, y1, x2, y2]
            scores: (N,)   置信度
            labels: (N,)   类别 ID（单类别场景可省略）
        """
        self.frame_idx += 1

        boxes = np.asarray(boxes, dtype=float).reshape(-1, 4)
        scores = np.asarray(scores, dtype=float).reshape(-1)
        if labels is None:
            labels = np.zeros(len(boxes), dtype=int)
        labels = np.asarray(labels, dtype=int).reshape(-1)

        cfg = self.config
        tids = list(self.tracks.keys())

        # 预测每条轨迹在本帧的位置
        if tids:
            pred_boxes = np.array([self._predict(self.tracks[t]) for t in tids], dtype=float)
        else:
            pred_boxes = np.zeros((0, 4), dtype=float)

        # 检测框按置信度分流（ByteTrack 的两轮匹配基础）
        high_idx = np.where(scores >= cfg["high_thresh"])[0]
        low_idx = np.where((scores >= cfg["low_thresh"]) & (scores < cfg["high_thresh"]))[0]

        # 每行阈值: 起步期轨迹放宽（速度还没建立，预测不可靠）
        row_thresh = np.array([
            cfg["boot_match_iou"] if self.tracks[t]["hits"] < 2 else cfg["match_thresh"]
            for t in tids
        ], dtype=float)

        # 第一轮: 高分框 ↔ 预测框（分数 = IoU ⊕ 距离门控）
        matched = {}   # 轨迹行号 -> 检测框下标
        if tids and len(high_idx):
            score1 = match_score_matrix(pred_boxes, boxes[high_idx], cfg["match_dist_gate"])
            for r, c in _greedy_match(score1, row_thresh):
                matched[r] = int(high_idx[c])

        # 第二轮: 低分框救回第一轮落空的轨迹
        left = [r for r in range(len(tids)) if r not in matched]
        if left and len(low_idx):
            score2 = match_score_matrix(pred_boxes[left], boxes[low_idx], cfg["match_dist_gate"])
            thr2 = np.full(len(left), cfg["second_match_thresh"], dtype=float)
            for r2, c2 in _greedy_match(score2, thr2):
                matched[left[r2]] = int(low_idx[c2])

        # 应用匹配结果
        visible = {}
        for r, tid in enumerate(tids):
            trk = self.tracks[tid]
            d = matched.get(r)
            if d is None:
                trk["time_since_update"] += 1
            else:
                self._update_track(trk, boxes[d], float(scores[d]), int(labels[d]))
                visible[tid] = (trk["bbox"], float(scores[d]))

        # 未被匹配的高分框 → 先尝试复活归档轨迹，不行再新建
        taken = set(matched.values())
        for d in high_idx:
            d = int(d)
            if d in taken or scores[d] < cfg["new_track_thresh"]:
                continue
            tid = self._try_revive(boxes[d], float(scores[d]), int(labels[d]))
            if tid is None:
                tid = self._create_track(boxes[d], float(scores[d]), int(labels[d]))
            visible[tid] = (self.tracks[tid]["bbox"], float(scores[d]))

        # 清理超期轨迹: 移入归档而非删除（历史要留着参与计数与短轨迹过滤）
        expired = [t for t, trk in self.tracks.items()
                   if trk["time_since_update"] > cfg["track_buffer"]]
        for t in expired:
            self.removed[t] = self.tracks.pop(t)

        return visible

    def finalize(self) -> dict:
        """导出轨迹历史（含已超期归档的），格式与 postprocess_tracks 输入一致。

        稳定确认门控开启时只导出已确认轨迹 —— 计数与画框共用这一处判定，
        未通过门控的轨迹不会进入后处理，也不会出现在视频里。
        """
        all_tracks = {**self.removed, **self.tracks}
        if self.config["confirm_enabled"]:
            all_tracks = {t: trk for t, trk in all_tracks.items() if trk["confirmed"]}
        return {
            tid: {
                "frames": trk["frames"],
                "centers": trk["centers"],
                "bboxes": trk["bboxes"],
                "confs": trk["confs"],
            }
            for tid, trk in all_tracks.items()
            if trk["frames"]
        }

    def visible_confirmed(self, visible: dict) -> dict:
        """按稳定确认门控过滤本帧可见轨迹（门控关闭时原样返回）。"""
        if not self.config["confirm_enabled"]:
            return visible
        return {t: v for t, v in visible.items()
                if self.tracks.get(t, {}).get("confirmed")}

    def gate_summary(self) -> dict:
        """稳定确认门控统计（供日志与 result.json 展示）。"""
        all_tracks = [trk for trk in {**self.removed, **self.tracks}.values() if trk["frames"]]
        enabled = bool(self.config["confirm_enabled"])
        n_confirmed = sum(1 for trk in all_tracks if trk["confirmed"])
        return {
            "confirm_enabled": enabled,
            "confirm_window": self.config["confirm_window"],
            "confirm_min_hits": self.config["confirm_min_hits"],
            "tracks_total": len(all_tracks),
            "tracks_confirmed": n_confirmed if enabled else len(all_tracks),
            "rejected_unconfirmed": (len(all_tracks) - n_confirmed) if enabled else 0,
            "revived_online": self._revive_count,
        }

    # ------------------------------------------------------------ 轨迹状态

    @staticmethod
    def _predict(trk: dict) -> np.ndarray:
        """匀速外推: 中心点按速度前进 (time_since_update + 1) 步。"""
        steps = trk["time_since_update"] + 1
        shift = trk["vel"] * steps
        b = trk["bbox"]
        return np.array([b[0] + shift[0], b[1] + shift[1],
                         b[2] + shift[0], b[3] + shift[1]], dtype=float)

    def _try_revive(self, bbox, score: float, label: int):
        """尝试从归档轨迹里复活一条（同一只虫再次出现，沿用旧 ID）。

        这就是你说的"后面再检测到它不要重新编号": 先判断是不是之前那只，
        是就沿用原 ID，不是才新建。编号天然按首次出现顺序。

        判据（和断轨合并一致）:
          - 时间: 消失帧数 <= merge_gap_frames（太久没见就当新虫）
          - 空间: 中心距离 <= min(merge_dist_threshold, merge_speed_max × gap)
        多条候选时选最近的那条。复活成功返回原 tid，失败返回 None。
        """
        cfg = self.config
        gap_max = int(cfg["merge_gap_frames"])
        dist_cap = float(cfg["merge_dist_threshold"])
        speed_max = float(cfg["merge_speed_max"])
        if gap_max <= 0 or not self.removed:
            return None

        new_center = bbox_center(bbox)
        best_tid, best_dist = None, None
        for tid, trk in self.removed.items():
            gap = self.frame_idx - trk["frames"][-1]
            if gap < 1 or gap > gap_max:
                continue
            limit = min(dist_cap, speed_max * gap)
            if limit <= 0:
                continue
            d = center_dist(trk["centers"][-1], new_center)
            if d > limit:
                continue
            if best_dist is None or d < best_dist:
                best_tid, best_dist = tid, d

        if best_tid is None:
            return None

        self._revive_count += 1
        # 复活: 从归档移回活跃集合，然后按新检测框更新
        trk = self.removed.pop(best_tid)
        self.tracks[best_tid] = trk
        # 按 gap 折算速度更新（和 _update_track 逻辑一致）
        steps = self.frame_idx - trk["frames"][-1]
        inst_vel = (new_center - trk["center"]) / max(steps, 1)
        if trk["hits"] >= 2:
            trk["vel"] = 0.5 * trk["vel"] + 0.5 * inst_vel
        else:
            trk["vel"] = inst_vel
        trk["bbox"] = np.asarray(bbox, dtype=float)
        trk["center"] = new_center
        trk["label"] = label
        trk["hits"] += 1
        trk["time_since_update"] = 0
        trk["hit_frames"].append(self.frame_idx)
        self._prune_and_confirm(trk)
        trk["frames"].append(self.frame_idx)
        trk["centers"].append(tuple(new_center))
        trk["bboxes"].append(tuple(float(v) for v in bbox))
        trk["confs"].append(float(score))
        return best_tid

    def _create_track(self, bbox, score: float, label: int) -> int:
        """新建轨迹（速度未知，起步期用宽松阈值匹配）。"""
        tid = self._next_id
        self._next_id += 1
        center = bbox_center(bbox)
        self.tracks[tid] = {
            "id": tid,
            "bbox": np.asarray(bbox, dtype=float),
            "center": center,
            "vel": np.zeros(2, dtype=float),   # 匀速模型速度（px/帧）
            "hits": 1,                          # 累计命中次数（速度可信度）
            "hit_frames": [self.frame_idx],     # 近期命中帧号（稳定确认窗口用）
            "confirmed": False,                 # 是否已通过稳定确认门控
            "time_since_update": 0,             # 连续丢失帧数
            "label": label,
            "frames": [self.frame_idx],
            "centers": [tuple(center)],
            "bboxes": [tuple(float(v) for v in bbox)],
            "confs": [float(score)],
        }
        self._prune_and_confirm(self.tracks[tid])
        return tid

    def _update_track(self, trk: dict, bbox, score: float, label: int) -> None:
        """命中后更新轨迹: 位置 + 速度（EMA 平滑，抗检测抖动）+ 历史。"""
        new_center = bbox_center(bbox)
        steps = trk["time_since_update"] + 1
        inst_vel = (new_center - trk["center"]) / steps   # 跨丢失帧时按步数折算
        if trk["hits"] >= 2:
            trk["vel"] = 0.5 * trk["vel"] + 0.5 * inst_vel
        else:
            trk["vel"] = inst_vel

        trk["bbox"] = np.asarray(bbox, dtype=float)
        trk["center"] = new_center
        trk["label"] = label
        trk["hits"] += 1
        trk["time_since_update"] = 0
        trk["hit_frames"].append(self.frame_idx)
        self._prune_and_confirm(trk)
        trk["frames"].append(self.frame_idx)
        trk["centers"].append(tuple(new_center))
        trk["bboxes"].append(tuple(float(v) for v in bbox))
        trk["confs"].append(float(score))

    def _prune_and_confirm(self, trk: dict) -> None:
        """把命中帧裁剪到观察窗口，并判定是否达到稳定确认。

        窗口取 [frame_idx - window + 1, frame_idx]。要求 min_hits == window 时，
        等价于"连续 window 帧都被识别到"；调小 min_hits 可容忍偶发漏检。
        确认是单向的（一旦达标不再撤销），避免轨迹中途抖动导致计数闪烁。
        """
        window = max(1, int(self.config["confirm_window"]))
        cutoff = self.frame_idx - window + 1
        trk["hit_frames"] = [f for f in trk["hit_frames"] if f >= cutoff]
        if trk["confirmed"]:
            return
        need = min(max(1, int(self.config["confirm_min_hits"])), window)
        if len(trk["hit_frames"]) >= need:
            trk["confirmed"] = True


# ============================================================================
# 轨迹后处理三步清洗（计数精度的决定环节）
# ============================================================================

def _refresh(trk: dict) -> None:
    """合并后重算派生字段（start/end/首尾中心/包络）。"""
    order = np.argsort(trk["frames"], kind="stable")
    trk["frames"] = [trk["frames"][i] for i in order]
    trk["centers"] = [trk["centers"][i] for i in order]
    trk["bboxes"] = [trk["bboxes"][i] for i in order]
    trk["confs"] = [trk["confs"][i] for i in order]
    trk["start_frame"] = trk["frames"][0]
    trk["end_frame"] = trk["frames"][-1]
    trk["first_center"] = trk["centers"][0]
    trk["last_center"] = trk["centers"][-1]
    trk["envelope"] = boxes_envelope(trk["bboxes"])


def _absorb(trk_a: dict, trk_b: dict) -> None:
    """把轨迹 B 并入 A 后按帧号重排（空间去重时两条轨迹时间上可能交叠）。"""
    # 合并前记录 B 的在线 ID 来源，供 postprocess_tracks 回溯 id_map
    trk_a["origins"] = set(trk_a.get("origins", ())) | set(trk_b.get("origins", ()))
    seen = set()
    frames, centers, bboxes, confs = [], [], [], []
    for f, c, b, cf in zip(trk_a["frames"] + trk_b["frames"],
                           trk_a["centers"] + trk_b["centers"],
                           trk_a["bboxes"] + trk_b["bboxes"],
                           trk_a["confs"] + trk_b["confs"]):
        if f in seen:      # 同一帧两条轨迹都有 → 只留一条，避免 n_frames 虚高
            continue
        seen.add(f)
        frames.append(f)
        centers.append(c)
        bboxes.append(b)
        confs.append(cf)
    trk_a["frames"], trk_a["centers"] = frames, centers
    trk_a["bboxes"], trk_a["confs"] = bboxes, confs
    _refresh(trk_a)


def _merge_broken(tracks: dict, cfg: dict) -> tuple:
    """② 断轨合并: 时间上首尾相接 + 空间上接得上的两段轨迹判为同一只。

    虫子被遮挡 / 检测器连续漏检 → 关联器会把一条轨迹切成两段（两个 ID）。

    两个门槛分工:
      - 时间: 间隔超过 merge_gap_frames 就认为无关（不合并）。这同时保证一条轨迹内部
        不会出现更长的断裂 —— 否则 ID 会在消失很久后重新出现，看起来像编号乱序。
      - 空间: 只看"首尾中心离多远"，不看运动方向。虫子会转向，方向约束会把真断轨漏掉；
        改用速度上限 dist <= min(merge_dist_threshold, merge_speed_max × gap) ——
        间隔越长允许离得越远，但"一瞬间跨半屏"那种误接会被速度上限挡住。
    返回 (合并后 tracks, 合并次数)。
    """
    gap_max = cfg["merge_gap_frames"]
    dist_cap = cfg["merge_dist_threshold"]
    speed_max = cfg["merge_speed_max"]
    merged, n = dict(tracks), 0

    changed = True
    while changed:
        changed = False
        items = sorted(merged.items(), key=lambda kv: kv[1]["start_frame"])
        for i in range(len(items)):
            if changed:
                break
            tid_a, ta = items[i]
            for j in range(i + 1, len(items)):
                tid_b, tb = items[j]
                gap = tb["start_frame"] - ta["end_frame"]
                if gap > gap_max:
                    break              # 已按起始帧排序，后面的间隔只会更大
                if gap < 0:            # 时间上重叠的交给空间去重处理
                    continue
                if center_dist(ta["last_center"], tb["first_center"]) <= \
                        min(dist_cap, speed_max * gap):
                    _absorb(ta, tb)
                    merged.pop(tid_b, None)
                    n += 1
                    changed = True
                    break
    return merged, n


def _same_bug_overlap(ta: dict, tb: dict, overlap_thr: float) -> bool:
    """时间重叠的两条轨迹是否指同一只虫: 重叠帧里框 IoU 超阈值的帧过半。

    只看两条轨迹同时出现的那些帧，逐帧比框 —— 不碰整段包络。
    用"过半"而非"最大/均值": 两只不同的虫轨迹交叉时个别帧的框可能恰好重合
    （取最大会误判），但绝大多数重叠帧并不重合（过半判据能压下去）；而"同一只虫
    被拆成两条"是帧帧都重合，稳定通过。
    """
    box_by_frame = dict(zip(ta["frames"], ta["bboxes"]))
    ious = [bbox_iou(box_by_frame[f], b)
            for f, b in zip(tb["frames"], tb["bboxes"]) if f in box_by_frame]
    if not ious:
        return False
    hits = sum(1 for v in ious if v > overlap_thr)
    return hits * 2 >= len(ious)


def _dedup_spatial(tracks: dict, cfg: dict) -> tuple:
    """③ 空间去重: 时间上重叠 + 同时刻位置重合的两条轨迹判为同一只。

    与 ② 断轨合并的分工: ② 处理时间首尾相接（gap >= 0）的两段；这里处理时间上
    重叠的两条 —— 关联器在同一时刻把同一只虫拆成了两条（检测抖动 / 双检 / 关联分裂）。

    判据从"整段包络 IoU"改为"重叠帧逐帧框 IoU"（见 _same_bug_overlap）:
    包络是轨迹全生命周期所有框的外接矩形，虫子爬动一段后包络会远大于虫体本身，
    和邻居的包络轻轻一碰就 IoU > 0 → 合并后包络再变大 → 连锁吞并。
    逐帧比较只看同一时刻两个框是否重合，物理含义明确，且不随轨迹时长漂移。
    返回 (去重后 tracks, 合并次数)。
    """
    overlap_thr = cfg["spatial_overlap"]
    merged, n = dict(tracks), 0

    changed = True
    while changed:
        changed = False
        items = sorted(merged.items(), key=lambda kv: kv[1]["start_frame"])
        for i in range(len(items)):
            if changed:
                break
            tid_a, ta = items[i]
            for j in range(i + 1, len(items)):
                tid_b, tb = items[j]
                # 按 start_frame 排序 → 一旦 B 的起点晚于 A 的终点，后面更晚，不可能再重叠
                if tb["start_frame"] > ta["end_frame"]:
                    break
                if _same_bug_overlap(ta, tb, overlap_thr):
                    _absorb(ta, tb)
                    merged.pop(tid_b, None)
                    n += 1
                    changed = True
                    break
    return merged, n


def postprocess_tracks(tracks: dict, config: dict = None) -> tuple:
    """轨迹后处理三步清洗 + 重编号。

    Args:
        tracks: {tid: {"frames", "centers", "bboxes", "confs"}}（IoUTracker.finalize()
                或 model.track 逐帧收集的结果）
        config: 覆盖 configs.yaml 的 tracker 节（只用到后处理这几个 key）

    Returns:
        (tracks, stats, id_map)
        tracks: {1..M: {...}} 清洗后轨迹（含 start_frame/end_frame/envelope 等派生字段）
        stats:  各步删并数量，便于核对去重效果
        id_map: {原始 tid: 最终 id}，把逐帧在线 ID 映射到最终 ID；
                未出现在表里的在线 ID 表示该轨迹被丢弃，不应计入也不应绘制
    """
    cfg = dict(PIPELINE_CONFIG["tracker"])
    if config:
        cfg.update({k: v for k, v in config.items() if k in cfg})

    n_raw = len(tracks)
    tracks = {tid: dict(trk) for tid, trk in tracks.items() if trk["frames"]}
    for tid, trk in tracks.items():
        trk["origins"] = {tid}      # 记录合并前的在线 ID 来源
        _refresh(trk)

    # ① 短轨迹过滤: 存活帧数不足判为误检（误检通常只活 1-2 帧）
    tracks = {tid: trk for tid, trk in tracks.items()
              if len(trk["frames"]) >= cfg["min_track_frames"]}
    n_short = n_raw - len(tracks)

    # ② 断轨合并  ③ 空间去重
    tracks, n_broken = _merge_broken(tracks, cfg)
    tracks, n_spatial = _dedup_spatial(tracks, cfg)

    # ④ 重编号 1..M（按起始帧排序，输出更干净）+ 建在线 ID → 最终 ID 映射表
    ordered = sorted(tracks.items(), key=lambda kv: kv[1]["start_frame"])
    tracks = {new_id: trk for new_id, (_, trk) in enumerate(ordered, start=1)}
    id_map = {}
    for new_id, trk in tracks.items():
        trk["origins"] = sorted(trk["origins"])     # set → list（JSON 可序列化）
        for orig in trk["origins"]:
            id_map[orig] = new_id

    stats = {
        "tracks_raw": n_raw,
        "filtered_short": n_short,
        "merged_broken": n_broken,
        "merged_spatial": n_spatial,
        "tracks_final": len(tracks),
    }
    return tracks, stats, id_map


