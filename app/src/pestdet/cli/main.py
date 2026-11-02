"""cli — 统一命令行入口（把视频检测与各工具子命令收敛到一处）。

检测模式直接作为子命令（不再有 detect 中间层），两种模式共用同一套视频流程
（草地遮罩 → 检测 → 跨帧去重计数 → 视频/JSON 产物）:

用法:
    python cli.py sahi    --source videos/test0.mp4            # 切片检测 → 去重计数
    python cli.py direct  --source videos/test0.mp4            # 整帧直推 → 去重计数
    python cli.py roi     --source videos/test0.mp4            # ROI 遮罩调参预览
    python cli.py weights --list                               # 权重登记管理

    python cli.py --help              # 查看全部子命令
    python cli.py <子命令> --help      # 查看某子命令的参数

底层实现: pestdet.core.pipeline.VideoPipeline（sahi / direct 共用）/
         pestdet.core.roi（roi 预览）/ pestdet.infra.registry（weights 管理）。
配置唯一来源 = 项目根 configs.yaml；CLI 显式参数仅覆盖想改的字段。
"""

import argparse
import os
import sys
from pathlib import Path

import cv2

from pestdet.config import ConfigError, load_config, merge_overrides
from pestdet.core.pipeline import VideoPipeline
from pestdet.core.roi import load_frame, make_preview, quad_area_ratio
from pestdet.infra.logging import configure_logging, get_logger

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ============================================================================
# sahi / direct —— 视频检测工作流（共用同一入口，mode 由子命令名指定）
# ============================================================================

def _run_detect(argv, mode: str) -> int:
    """sahi / direct 子命令的共用实现: mode 由命令名指定。"""
    cfg = load_config()
    other = "direct" if mode == "sahi" else "sahi"
    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} {mode}",
        description=f"{'SAHI 切片' if mode == 'sahi' else '整帧直推'}检测 → 跨帧去重计数 → 推理视频 + 暂存数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"示例:\n"
               f"  python cli.py {mode} --source videos/test0.mp4                 # 模型留空 → 取最新登记权重\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --model pest1\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --model best.pt\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --stride 2                # 抽帧加速\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --no-mask               # 关闭草地遮罩\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --no-snapshots          # 不保存检出帧快照\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --mask-refresh 0        # 只在首帧拟合后固定\n"
               f"  python cli.py {mode} --source videos/test0.mp4 --mask-refresh 30       # 每 30 帧重拟合（省算力）\n"
               f"换另一种检测模式: python cli.py {other} --source videos/test0.mp4\n"
               f"默认值唯一来源 = 项目根 configs.yaml（改参数只改那里）\n"
               f"遮罩调参预览: python cli.py roi --source videos/test0.mp4 --out runs/roi_preview.png",
    )
    parser.add_argument("--source", required=True, help="输入视频路径")
    parser.add_argument("--model", "--weights", default=cfg["model_path"], metavar="PATH",
                        help="检测模型路径（留空 = 取最新登记权重；也可写 pest1 这类登记名）")
    parser.add_argument("--output", default=cfg["output_root"], metavar="DIR",
                        help="输出根目录")
    parser.add_argument("--stride", type=int, default=cfg["frame_stride"],
                        help="抽帧步长（1=逐帧）")
    parser.add_argument("--max-frames", type=int, default=cfg["max_frames"],
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
    parser.add_argument("--no-json", action="store_true", help="不输出暂存数据 JSON")
    args = parser.parse_args(argv)

    if not os.path.exists(args.source):
        print(f"\n[错误] 视频文件不存在: {args.source}\n")
        return 1

    over = {
        "output_root": args.output,
        "frame_stride": args.stride,
        "max_frames": args.max_frames,
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

    configure_logging(level="INFO")
    logger = get_logger("cli")
    try:
        pipe = VideoPipeline(merge_overrides(cfg, over), model_path=args.model,
                             mode=mode, logger=logger)
        result = pipe.run(args.source)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"\n[错误] {e}\n")
        return 1

    if result["counting"]["unique_count"] == 0:
        print(f"  [提示] 未检出任何目标。可尝试: 降低 conf、换 python cli.py {other}、"
              "确认模型类别与目标匹配")
        c = result["counting"]
        if c.get("confirm_enabled") and c.get("rejected_unconfirmed", 0) > 0:
            print(f"  [提示] 稳定确认门控剔除了 {c['rejected_unconfirmed']} 条不稳定轨迹，"
                  f"可尝试 --confirm-min-hits 调小，或 --no-confirm 关闭门控")
    return 0


def _cmd_sahi(argv) -> int:
    return _run_detect(argv, "sahi")


def _cmd_direct(argv) -> int:
    return _run_detect(argv, "direct")


# ============================================================================
# roi —— 草地 ROI 遮罩调参预览
# ============================================================================

def _cmd_roi(argv) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} roi",
        description="草地四边形 ROI 预览 — 确认绿色分割是否贴合草地，便于调 HSV 阈值",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python cli.py roi --source videos/test0.mp4 --out runs/roi_preview.png\n"
               "  python cli.py roi --source videos/test0.mp4 --frame 200 --hsv-lower 30,30,30\n",
    )
    parser.add_argument("--source", required=True, help="视频或图片路径")
    parser.add_argument("--frame", type=int, default=0, help="取第几帧拟合（默认首帧）")
    parser.add_argument("--out", default="runs/roi_preview.png", help="预览图输出路径")
    parser.add_argument("--hsv-lower", default=None, help="覆盖绿色下界，如 35,40,40")
    parser.add_argument("--hsv-upper", default=None, help="覆盖绿色上界，如 85,255,255")
    parser.add_argument("--morph", type=int, default=None, help="覆盖形态学核尺寸")
    parser.add_argument("--detect-scale", type=float, default=None,
                        help="覆盖分割降采样比例（默认 0.25；设 1.0 用全分辨率，更慢更精细）")
    args = parser.parse_args(argv)

    if not os.path.exists(args.source):
        print(f"\n[错误] 输入不存在: {args.source}\n")
        return 1

    mask_cfg = dict(cfg["mask"])
    if args.hsv_lower:
        mask_cfg["hsv_lower"] = [int(v) for v in args.hsv_lower.split(",")]
    if args.hsv_upper:
        mask_cfg["hsv_upper"] = [int(v) for v in args.hsv_upper.split(",")]
    if args.morph is not None:
        mask_cfg["morph_kernel"] = args.morph
    if args.detect_scale is not None:
        mask_cfg["detect_scale"] = args.detect_scale

    try:
        frame = load_frame(args.source, args.frame)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        print(f"\n[错误] {e}\n")
        return 1

    preview, quad, cost_ms, fitted = make_preview(frame, mask_cfg)
    if not fitted:
        print(f"  拟合失败: 绿色区域占比不在 "
              f"[{mask_cfg['min_area_ratio']}, {mask_cfg['max_area_ratio']}] 内 —— "
              f"请放宽 --hsv-lower/--hsv-upper 或降低 min_area_ratio")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    params = [cv2.IMWRITE_JPEG_QUALITY, 95] if out.suffix.lower() in {".jpg", ".jpeg"} else []
    cv2.imwrite(str(out), preview, params)
    print(f"  四边形顶点:   {quad.tolist()}")
    print(f"  占帧面积比例: {quad_area_ratio(quad, frame.shape):.1%}")
    print(f"  拟合耗时:     {cost_ms:.1f} ms（detect_scale={mask_cfg['detect_scale']}）")
    print(f"  预览图:       {out}")
    return 0


# ============================================================================
# weights —— 权重登记管理
# ============================================================================

def _cmd_weights(argv) -> int:
    from pestdet.infra.registry import weights_main
    return weights_main(argv) or 0


# ============================================================================
# 分发
# ============================================================================

COMMANDS = {
    "sahi": (_cmd_sahi, "切片检测 → 跨帧去重计数 → 视频/JSON 产物"),
    "direct": (_cmd_direct, "整帧直推 → 跨帧去重计数 → 视频/JSON 产物"),
    "roi": (_cmd_roi, "草地 ROI 遮罩调参预览"),
    "weights": (_cmd_weights, "权重登记管理（pest{N} 版本链）"),
}


def _print_help() -> None:
    print("用法: python cli.py <子命令> [参数...]\n")
    print("子命令:")
    for name, (_, desc) in COMMANDS.items():
        print(f"  {name:<8} {desc}")
    print("\n查看子命令参数: python cli.py <子命令> --help")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        _print_help()
        return 0
    name, rest = argv[0], argv[1:]
    entry = COMMANDS.get(name)
    if entry is None:
        print(f"[错误] 未知子命令: {name}\n")
        _print_help()
        return 2
    try:
        return entry[0](rest) or 0
    except ConfigError as e:
        print(f"\n[错误] {e.format()}\n")
        print(f"请修正配置文件后重试。\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())