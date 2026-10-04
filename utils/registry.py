"""registry — 权重登记（runs/registry.json 的 pest{N} 版本链）。

部署侧由 pipeline.py 的模型解析复用: model_path 留空 = 取最新登记权重，--model pest1 = 指定登记名。
登记/查看入口（从项目根运行）:
    python -m utils.registry --save best.pt --tag deploy
    python -m utils.registry --list
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from utils.paths import PROJECT_ROOT

REGISTRY_PATH = PROJECT_ROOT / "runs" / "registry.json"
PEST_PATTERN = re.compile(r"^pest(\d+)$")


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"next": 1, "weights": {}}


def _save_registry(reg: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_save(source: str, tag: str = None, force_version: int = None, metrics: dict = None) -> str:
    """登记一次训练产物为 pest{N}。返回登记名（如 pest1）。

    Args:
        source: best.pt 路径（建议在 runs/ 布局下，登记相对项目根路径）
        tag: 可选标签（如实验名）
        force_version: 强制指定版本号
        metrics: 附加指标（mAP50 等，写入登记表）
    """
    src = Path(source)
    if not src.exists():
        print(f"[错误] 源权重文件不存在: {source}")
        return ""

    reg = _load_registry()
    version = force_version if force_version else reg["next"]
    name = f"pest{version}"

    # 路径登记：优先存相对项目根路径（repo 移动后仍可解析）
    try:
        rel = src.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        rel = src.resolve()

    entry = {
        "path": str(rel).replace("\\", "/"),
        "tag": tag or "",
        "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if metrics:
        entry.update({k: v for k, v in metrics.items() if isinstance(v, (int, float, str))})

    reg["weights"][name] = entry
    if version >= reg["next"]:
        reg["next"] = version + 1
    _save_registry(reg)

    print(f"  已登记: {name}  ←  {rel}")
    if tag:
        print(f"  标签:   {tag}")
    print(f"  登记表: {REGISTRY_PATH}")
    return name


def resolve_pest(name: str) -> str:
    """解析登记名（pest1 / 1）为绝对权重路径；未登记返回空串。"""
    m = PEST_PATTERN.match(name)
    version = m.group(1) if m else (name[4:] if name.startswith("pest") else name)
    reg = _load_registry()
    entry = reg["weights"].get(f"pest{version}")
    if not entry:
        return ""
    p = Path(entry["path"])
    return str(p if p.is_absolute() else PROJECT_ROOT / p)


def latest_pest() -> str:
    """最新登记的 pest{N} 权重绝对路径；无登记或文件已缺失时返回空串。"""
    reg = _load_registry()
    if not reg["weights"]:
        return ""
    name = sorted(reg["weights"], key=lambda s: int(s[4:]))[-1]
    path = resolve_pest(name)
    return path if path and Path(path).exists() else ""


def cmd_list():
    reg = _load_registry()
    if not reg["weights"]:
        print("  (暂无已登记的 pest 权重)")
        return
    print(f"{'版本':<10} {'mAP50':<10} {'标签':<24} {'路径'}")
    print("-" * 90)
    for name in sorted(reg["weights"], key=lambda s: int(s[4:])):
        e = reg["weights"][name]
        print(f"  {name:<8} {str(e.get('mAP50', '—')):<10} {str(e.get('tag', '')):<24} {e['path']}")


def cmd_latest():
    reg = _load_registry()
    if not reg["weights"]:
        print("  (暂无已登记的 pest 权重)")
        return
    name = sorted(reg["weights"], key=lambda s: int(s[4:]))[-1]
    e = reg["weights"][name]
    print(f"  最新版本: {name}")
    print(f"  路径:     {e['path']}")
    if e.get("tag"):
        print(f"  标签:     {e['tag']}")
    if e.get("mAP50") is not None:
        print(f"  mAP50:    {e['mAP50']}")
    print(f"  总登记数: {len(reg['weights'])}")


def cmd_info(name: str):
    path = resolve_pest(name)
    if not path:
        print(f"[错误] 未登记权重: {name}")
        return
    p = Path(path)
    if not p.exists():
        print(f"[警告] 登记路径不存在（训练输出可能已被清理）: {p}")
        return
    size_mb = p.stat().st_size / (1024 * 1024)
    mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    print(f"  路径:     {p}")
    print(f"  大小:     {size_mb:.1f} MB")
    print(f"  修改时间: {mtime}")


def cmd_resolve(name: str):
    """输出登记权重路径（供 shell 嵌套 --teacher 使用）。"""
    path = resolve_pest(name)
    if not path:
        print(f"[错误] 未登记权重: {name}")
        return
    print(path)


def _parse_metrics(text: str) -> dict:
    """解析 --metrics "mAP50=0.87,precision=0.9" 为 {键: 数值/字符串}。"""
    metrics = {}
    for item in (text or "").split(","):
        key, sep, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        try:
            metrics[key] = int(value)
        except ValueError:
            try:
                metrics[key] = float(value)
            except ValueError:
                metrics[key] = value
    return metrics


def weights_main(argv=None):
    """权重登记 CLI（python -m utils.registry ... / python cli.py weights ...）。"""
    parser = argparse.ArgumentParser(
        description="权重登记管理 — pest{N} 版本链（登记表 runs/registry.json）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例（从项目根运行）:\n"
               "  python -m utils.registry --save best.pt --tag deploy\n"
               "  python -m utils.registry --save best.pt --tag deploy --metrics mAP50=0.87\n"
               "  python -m utils.registry --list\n"
               "  python -m utils.registry --latest\n"
               "  python -m utils.registry --info pest1\n"
               "  python -m utils.registry --resolve pest1",
    )
    parser.add_argument("--save", type=str, default=None, metavar="PATH",
                        help="登记训练产物为 pest{N}（不复制文件）")
    parser.add_argument("--tag", type=str, default=None, help="登记标签")
    parser.add_argument("--version", type=int, default=None, help="强制指定版本号")
    parser.add_argument("--metrics", type=str, default=None, metavar="K=V[,K=V]",
                        help="登记时写入的附加指标（如 mAP50=0.87,precision=0.9）")
    parser.add_argument("--list", action="store_true", help="列出全部登记")
    parser.add_argument("--latest", action="store_true", help="显示最新登记")
    parser.add_argument("--info", type=str, default=None, metavar="PEST", help="显示指定版本（如 pest1）")
    parser.add_argument("--resolve", type=str, default=None, metavar="PEST", help="输出登记路径（如 pest1）")
    args = parser.parse_args(argv)

    if args.save:
        cmd_save(args.save, tag=args.tag, force_version=args.version,
                 metrics=_parse_metrics(args.metrics))
    elif args.list:
        cmd_list()
    elif args.latest:
        cmd_latest()
    elif args.info:
        cmd_info(args.info)
    elif args.resolve:
        cmd_resolve(args.resolve)
    else:
        parser.print_help()


if __name__ == "__main__":
    weights_main()
