"""system — 运行环境 / 硬件探测（Web「系统环境」页与启动自检共用）。

探测三类信息:
    1. 主机: CPU 名称与核心数、内存总量/可用量、操作系统
    2. 加速卡: 显卡名称、显存总量/空闲、算力、驱动版本、CUDA / PyTorch 版本
    3. 软件: Python / 关键依赖版本、ffmpeg 是否可用、前端是否已构建

结果在进程内缓存: 首次探测会初始化 CUDA（约 1~2s），之后直接返回缓存；
``probe(force=True)`` 可强制重测（前端「重新检测」按钮）。
"""

import ctypes
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from functools import lru_cache

from pestdet.infra.paths import PROJECT_ROOT

_CACHE: dict | None = None

# 权重体积下限: Git LFS 未安装时 .pt 会退化成 ~130 字节的指针文本，
# 比这个门槛小的文件一律视为"权重未就绪"，触发网页端自动下载。
_MIN_WEIGHT_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------- 主机


def _cpu_name() -> str:
    """CPU 型号。Windows 读注册表 ProcessorNameString（比 platform.processor 精确）。"""
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    elif sys.platform.startswith("linux"):
        try:
            for line in open("/proc/cpuinfo", encoding="utf-8"):
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine() or "未知"


def _memory() -> dict:
    """物理内存总量 / 可用量（字节）。Windows 走 GlobalMemoryStatusEx，Linux 读 /proc/meminfo。"""
    total = available = 0
    if os.name == "nt":
        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total, available = status.ullTotalPhys, status.ullAvailPhys
        except OSError:
            pass
    elif sys.platform.startswith("linux"):
        try:
            values = {}
            for line in open("/proc/meminfo", encoding="utf-8"):
                key, _, rest = line.partition(":")
                values[key.strip()] = int(rest.strip().split()[0]) * 1024
            total = values.get("MemTotal", 0)
            available = values.get("MemAvailable", values.get("MemFree", 0))
        except (OSError, ValueError):
            pass
    return {
        "total_gb": round(total / 1024**3, 1),
        "available_gb": round(available / 1024**3, 1),
    }


def _gpu() -> dict:
    """显卡信息。torch 不可用 / 无 CUDA 时返回空列表 + 原因。"""
    info = {"available": False, "cuda_version": None, "torch_version": None,
            "devices": [], "error": None}
    try:
        import torch
    except Exception as exc:                      # noqa: BLE001 - 环境缺失不应让探测失败
        info["error"] = f"PyTorch 不可用: {exc}"
        return info

    info["torch_version"] = torch.__version__
    info["cuda_version"] = getattr(torch.version, "cuda", None)
    try:
        if not torch.cuda.is_available():
            info["error"] = "未检测到可用的 CUDA 设备（CPU 推理会很慢，仍可使用）"
            return info
        info["available"] = True
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            try:
                free, total = torch.cuda.mem_get_info(index)
            except Exception:                     # noqa: BLE001 - 部分驱动不支持
                free, total = 0, props.total_memory
            info["devices"].append({
                "index": index,
                "name": torch.cuda.get_device_name(index),
                "total_gb": round(total / 1024**3, 1),
                "free_gb": round(free / 1024**3, 1),
                "capability": f"{props.major}.{props.minor}",
            })
    except Exception as exc:                      # noqa: BLE001 - CUDA 初始化失败
        info["error"] = f"CUDA 探测失败: {exc}"
    driver = _nvidia_driver()
    if driver:
        info["driver"] = driver
    return info


@lru_cache(maxsize=1)
def _nvidia_driver() -> str:
    """NVIDIA 驱动版本（nvidia-smi）；没有时返回空串。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return ""
    try:
        out = subprocess.run(
            [exe, "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return (out.stdout or "").strip().splitlines()[0] if out.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def _versions() -> dict:
    """关键依赖版本（查已安装发行版，不 import，快且不触发 CUDA）。"""
    names = ("torch", "ultralytics", "opencv-python", "fastapi", "uvicorn", "pydantic")
    out = {}
    for name in names:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


def _software() -> dict:
    ffmpeg = shutil.which("ffmpeg") or ""
    return {
        "python": platform.python_version(),
        "python_exe": sys.executable,
        "platform": f"{platform.system()} {platform.release()}",
        "ffmpeg": ffmpeg,
        "versions": _versions(),
        "web_dist": str(PROJECT_ROOT / "web" / "dist" / "index.html"),
        "web_dist_exists": (PROJECT_ROOT / "web" / "dist" / "index.html").exists(),
    }


# ---------------------------------------------------------------- 权重


def resolve_weight_path(model_path: str) -> str:
    """把 configs.yaml 的 model_path 解析成绝对路径（支持 pestN 登记名）。"""
    raw = (model_path or "").strip()
    if not raw:
        from pestdet.infra.registry import latest_pest

        return latest_pest()
    if raw.lower().startswith("pest"):
        from pestdet.infra.registry import resolve_pest

        return resolve_pest(raw) or ""
    path = PROJECT_ROOT / raw
    return str(path)


def weight_status() -> dict:
    """当前部署权重的就绪状态（缺失 / 体积异常 / 正常）。"""
    from pestdet.services.weights import DEFAULT_WEIGHT

    try:
        from pestdet.config import load_config

        model_path = load_config().get("model_path", "")
        config_error = None
    except Exception as exc:                      # noqa: BLE001 - 配置坏了也要能展示状态
        model_path = ""
        config_error = str(exc)

    path = resolve_weight_path(model_path)
    status = {
        "model_path": model_path,
        "path": path,
        "exists": False,
        "size_mb": 0.0,
        "valid": False,
        "reason": "",
        "default_name": DEFAULT_WEIGHT["name"],
        "default_sha256": DEFAULT_WEIGHT["sha256"],
        "config_error": config_error,
    }
    if not path:
        status["reason"] = "configs.yaml 的 model_path 为空，且没有已登记的权重"
        return status

    from pathlib import Path

    file = Path(path)
    if not file.exists():
        status["reason"] = "权重文件不存在，可由网页端自动下载"
        return status

    size = file.stat().st_size
    status["exists"] = True
    status["size_mb"] = round(size / 1024**2, 1)
    if size < _MIN_WEIGHT_BYTES:
        status["reason"] = ("文件体积异常（疑似 Git LFS 指针文件），请安装 git-lfs 或由网页端下载")
        return status

    status["valid"] = True
    return status


# ---------------------------------------------------------------- 汇总


def probe(force: bool = False) -> dict:
    """完整探测结果。

    硬件 / 软件部分进程级缓存（CUDA 初始化较慢）；权重状态每次都重新读取，
    这样前端下载完成后刷新即可看到最新结果。
    """
    global _CACHE
    if _CACHE is None or force:
        from pestdet import __version__

        _CACHE = {
            "version": __version__,
            "cpu": {
                "name": _cpu_name(),
                "logical_cores": os.cpu_count(),
                "machine": platform.machine(),
            },
            "memory": _memory(),
            "gpu": _gpu(),
            "software": _software(),
            "project_root": str(PROJECT_ROOT),
        }
    info = dict(_CACHE)
    info["weights"] = weight_status()
    return info
