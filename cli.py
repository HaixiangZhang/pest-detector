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

底层实现: pipeline.detect_main（sahi / direct 共用）/ utils.roi.roi_main / utils.registry.weights_main
（utils 各模块仍支持 python -m utils.<mod> 直调，如 python -m utils.sahi 是纯切片推理调试入口；
  pipeline.py 已无独立入口，只作库被 import）
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def _cmd_sahi(argv):
    from pipeline import detect_main
    return detect_main(argv, mode="sahi")


def _cmd_direct(argv):
    from pipeline import detect_main
    return detect_main(argv, mode="direct")


def _cmd_roi(argv):
    from utils.roi import roi_main
    return roi_main(argv)


def _cmd_weights(argv):
    from utils.registry import weights_main
    return weights_main(argv)


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
    return entry[0](rest) or 0


if __name__ == "__main__":
    raise SystemExit(main())