"""render — 第二遍重绘: 把最终 ID 画到帧上，并写出推理视频与检出帧快照。

第一遍主循环只做检测与关联；绘制统一收敛到这里的 render_pass —— 用后处理得到的 id_map
把在线 ID 换成最终 ID 再画，保证画面里的框与 ID 和最终计数严格一致（被短轨迹过滤或门控
剔除的在线轨迹在 id_map 里查不到，直接不画）。

用法（由 pipeline.py 的 VideoPipeline.run 在 5/6 阶段调用）:
    writer = render_pass(video, cfg, out_dir, frame_visible, quads, id_map,
                         tracker, saver, fps, width, height, n_plan)

顶层只 import cv2/numpy 与标准库（保持模块轻量）。
"""

import os
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np


def make_writer(out_path: str, save_video: bool, width: int, height: int, fps: float):
    """建视频写入器；失败则关闭视频输出（不中断流程）。

    输出目录在这里按需创建（pipeline 只规划路径、不预建），保证"没写成视频"时
    不会留下空目录；编码器全部不可用时撤掉刚建的空目录。
    """
    if not save_video:
        return None
    if width <= 0 or height <= 0:
        print("  [警告] 视频尺寸读取失败，跳过推理视频输出")
        return None

    parent = Path(out_path).parent
    parent.mkdir(parents=True, exist_ok=True)
    for fourcc_name in ("mp4v", "avc1"):
        writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*fourcc_name),
                                 max(float(fps), 1.0), (width, height))
        if writer.isOpened():
            return writer
        writer.release()
    try:
        parent.rmdir()                 # 只在空目录时成功；非空则说明别处已写入，保留
    except OSError:
        pass
    print(f"  [警告] 无法创建视频写入器（编码器不可用），跳过推理视频输出: {out_path}")
    return None


# 常见 ffmpeg 安装位置（PATH 里没有时兜底探测）
_FFMPEG_COMMON = (
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    r"D:\ffmpeg\bin\ffmpeg.exe",
)


def _find_ffmpeg(enc_cfg):
    """定位 ffmpeg 可执行文件（返回路径，找不到返回 None）。

    顺序: 配置里 encode.ffmpeg 的显式路径 → PATH → 常见安装位置 → TRAE 自带。
    最后一项是因为 TRAE 的 resources/app/bin 下带一份 libx264 的 ffmpeg，但它只在
    IDE 自己的终端里进 PATH，用户在自己终端跑 cli.py 时看不到，故额外探一下。
    """
    explicit = str((enc_cfg or {}).get("ffmpeg", "") or "").strip()
    if explicit:
        if Path(explicit).exists():
            return explicit
        print(f"  [警告] encode.ffmpeg 指定的路径不存在: {explicit}（继续自动探测）")

    found = shutil.which("ffmpeg")
    if found:
        return found

    for cand in _FFMPEG_COMMON:
        if Path(cand).exists():
            return cand

    local = os.environ.get("LOCALAPPDATA")
    if local:
        winget = Path(local) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
        if winget.exists():
            return str(winget)

    for drive in ("C:/", "D:/", "E:/"):
        root = Path(drive)
        if not root.exists():
            continue
        try:
            for hit in root.glob("TRAE*/resources/app/bin/ffmpeg.exe"):
                return str(hit)
        except OSError:
            pass
    return None


def transcode_h264(path, enc_cfg) -> bool:
    """把 OpenCV 写出的 mp4v 视频就地转成 H.264（可硬件解码，避免 4K60 播放卡顿）。

    背景: 本机 OpenCV 只能写 mp4v（MPEG-4 Part 2），它没有硬件解码，4K60 软解跟不上
    会卡；而 ffmpeg 带 libx264。所以写完后转一遍，成功后覆盖原文件。

    ffmpeg 找不到、转码失败或未开启时，原 mp4v 文件原样保留（不中断流程）。
    """
    if not (enc_cfg or {}).get("h264", True):
        return False
    ffmpeg = _find_ffmpeg(enc_cfg)
    if not ffmpeg:
        print("  [警告] 未找到 ffmpeg，无法转 H.264 → 保留 mp4v 输出（无硬件解码，4K 播放会卡）")
        print("         解决: 装 ffmpeg 并加入 PATH，或把完整路径填到 configs.yaml 的 encode.ffmpeg")
        return False

    path = Path(path)
    tmp = path.with_name(f"{path.stem}.h264{path.suffix}")
    crf, preset = int(enc_cfg.get("crf", 23)), str(enc_cfg.get("preset", "medium"))
    print(f"  [编码] 用 ffmpeg 转 H.264: {path.name}（libx264 crf={crf} preset={preset}）")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(path), "-an",
           "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as e:
        print(f"  [警告] 调起 ffmpeg 失败，保留 mp4v 输出: {e}")
        return False
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        if tmp.exists():
            tmp.unlink()
        print(f"  [警告] H.264 转码失败，保留 mp4v 输出: {r.stderr.strip()[:200]}")
        return False
    os.replace(tmp, path)              # 原子替换；失败也不影响已转好的临时文件
    return True


def trail_points(tracker, tid, frame_idx, trail_len):
    """取该轨迹截至 frame_idx 的最近 trail_len 个中心点。

    第二遍渲染时轨迹可能已归档进 removed，所以要两处都查；
    且必须按 frame_idx 截断，否则尾迹会画出当前帧之后的部分。
    """
    trk = tracker.tracks.get(tid) or tracker.removed.get(tid)
    if not trk:
        return []
    pts = [c for f, c in zip(trk["frames"], trk["centers"])
           if frame_idx is None or f <= frame_idx]
    return pts[-trail_len:]


def draw_frame(frame, visible: dict, tracker, draw_cfg: dict, processed: int, n_plan: int,
               quad=None, frame_idx=None, n_final=0):
    """绘制标注帧: ROI 轮廓 + 框 + ID + 尾迹 + 计数面板（文字全 ASCII，中文会乱码）。

    由 render_pass 在第二遍渲染时调用: visible 的 key 已经是最终 ID。
    frame_idx 用于把尾迹截断到当前帧 —— 此时轨迹历史已完整，不截断会画出"未来"。
    """
    d = draw_cfg
    img = frame.copy()
    k = max(1.0, frame.shape[1] / 1280.0)          # 4K 自动放大线宽与字号
    thick = max(1, int(round(d["thickness"] * k)))
    font = d["font_scale"] * k

    # ROI 轮廓画在最底层，避免压住检测框
    if d["roi_outline"] and quad is not None:
        cv2.polylines(img, [quad.reshape(-1, 1, 2)], True, d["roi_color"], thick)

    for tid, (bbox, score) in visible.items():
        x1, y1, x2, y2 = (int(v) for v in bbox)

        if d["trail"]:
            pts = trail_points(tracker, tid, frame_idx, d["trail_len"])
            if len(pts) >= 2:
                poly = np.array([[int(p[0]), int(p[1])] for p in pts], dtype=np.int32)
                cv2.polylines(img, [poly], False, d["trail_color"], thick)

        if d["box"]:
            cv2.rectangle(img, (x1, y1), (x2, y2), d["box_color"], thick)

        if d["track_id"]:
            label = f"ID{tid}" + (f" {score:.2f}" if d["score"] else "")
            cv2.putText(img, label, (x1, max(int(14 * k), y1 - int(6 * k))),
                        cv2.FONT_HERSHEY_SIMPLEX, font, d["box_color"], thick, cv2.LINE_AA)

    if d["panel"]:
        lines = [
            f"Frame {processed}/{n_plan}",
            f"in-frame: {len(visible)}",
            f"tracks: {n_final}",
        ]
        pad, lh = int(10 * k), int(24 * k)
        box_w = int(230 * k)
        cv2.rectangle(img, (pad, pad), (pad + box_w, pad + lh * len(lines) + lh // 2),
                      (0, 0, 0), -1)
        for i, txt in enumerate(lines):
            cv2.putText(img, txt, (pad + int(8 * k), pad + lh * (i + 1)),
                        cv2.FONT_HERSHEY_SIMPLEX, font, d["text_color"], 1, cv2.LINE_AA)
    return img


def render_pass(video, cfg, out_dir, frame_visible, quads, id_map, tracker,
                saver, fps, width, height, n_plan):
    """第二遍: 重读视频，用最终 ID 重画并写出视频与快照。

    主循环只做检测与关联，绘制统一放在这里 —— 这样离线合并/过滤的结果才能反映到
    画面上，视频里的框与 ID 必然和最终计数一致。被短轨迹过滤或门控剔除的在线轨迹
    在 id_map 里查不到，直接不画。

    Returns:
        已打开的 VideoWriter（未开启视频输出时为 None）
    """
    stride = max(1, int(cfg["frame_stride"]))
    writer = make_writer(str(out_dir / cfg["video_name"]), cfg["save_video"],
                         width, height, fps / stride)
    n_final = len(set(id_map.values()))

    cap = cv2.VideoCapture(str(video))
    frame_idx, processed = -1, 0
    while processed < len(frame_visible):
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        if frame_idx % stride:          # 与第一遍的抽帧规则保持一致
            continue

        visible = {id_map[t]: v for t, v in frame_visible[processed].items()
                   if t in id_map}
        drawn = None
        if writer is not None or saver.will_save(visible):
            drawn = draw_frame(frame, visible, tracker, cfg["draw"], processed, n_plan,
                               quads[processed], frame_idx, n_final)
        if writer is not None:
            writer.write(drawn)
        saver.save(drawn, visible, frame_idx, processed)
        processed += 1

    cap.release()
    if writer is not None:
        writer.release()
        # OpenCV 写出的 mp4v 无硬件解码，播放 4K60 会卡；收尾转成 H.264（不可用则保留）
        transcode_h264(out_dir / cfg["video_name"], cfg.get("encode"))
    return writer