"""weights — 默认权重的下载 / 校验 / 进度状态。

网页端打开后若检测到权重缺失（或只是 Git LFS 指针文件），会自动调用这里的
下载器: 流式写 ``<目标>.part`` → 校验 SHA256 → 原子替换到 configs.yaml 的
``model_path``。下载在后台线程执行，前端轮询 ``state()`` 拿进度。

下载源按顺序尝试，可用环境变量 ``PESTDET_WEIGHT_URL`` 覆盖（自建镜像 / 内网）。
"""

import hashlib
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from pestdet.infra.paths import PROJECT_ROOT

# 默认权重清单（RicePest v1.0 的 P2 + 切片主力权重）
DEFAULT_WEIGHT = {
    "name": "tiling_104121.pt",
    "sha256": "c474e7d39b30860526198262837eea6ebf1f2d7a8958f905c0a42a881e72ce9d",
    "size_mb": 118.2,
    "urls": [
        # RicePest 仓库 Release（权重主发布位置）
        "https://github.com/HaixiangZhang/RicePest-YOLO11x-P2/releases/download/"
        "v1.0/tiling_104121.pt",
        # 备用: pest_detector 仓库 Release
        "https://github.com/HaixiangZhang/pest-detector/releases/download/"
        "v0.1.0/best.pt",
    ],
}

_CHUNK = 1024 * 1024
_LOCK = threading.Lock()
_STATE = {
    "running": False,
    "status": "idle",        # idle | running | done | error
    "done_bytes": 0,
    "total_bytes": 0,
    "percent": 0,
    "path": "",
    "error": "",
    "source": "",
}


def _candidate_urls() -> list[str]:
    """下载源列表（环境变量优先，便于内网镜像）。"""
    override = (os.environ.get("PESTDET_WEIGHT_URL") or "").strip()
    return [override] if override else list(DEFAULT_WEIGHT["urls"])


def _target_path() -> Path:
    """下载落点: configs.yaml 的 model_path；为空时落到项目根 best.pt。"""
    from pestdet.services.system import resolve_weight_path

    try:
        from pestdet.config import load_config

        model_path = load_config().get("model_path", "")
    except Exception:                             # noqa: BLE001 - 配置损坏时用默认名
        model_path = ""
    resolved = resolve_weight_path(model_path)
    return Path(resolved) if resolved else PROJECT_ROOT / "best.pt"


def state() -> dict:
    """当前下载状态（线程安全快照）。"""
    with _LOCK:
        return dict(_STATE)


def _set(**kwargs) -> None:
    with _LOCK:
        _STATE.update(kwargs)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_one(url: str, target: Path) -> None:
    """从单个 URL 下载并校验；失败抛异常。"""
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "pest_detector"})
    with urllib.request.urlopen(request, timeout=30) as response:
        total = int(response.headers.get("Content-Length") or 0)
        _set(total_bytes=total, done_bytes=0, percent=0, source=url)
        done = 0
        with open(tmp, "wb") as handle:
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                percent = int(done * 100 / total) if total else 0
                _set(done_bytes=done, percent=percent)

    actual = _sha256(tmp)
    if DEFAULT_WEIGHT["sha256"] and actual != DEFAULT_WEIGHT["sha256"]:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"校验失败（SHA256 不匹配: {actual[:12]}…）")

    os.replace(tmp, target)


def _worker(target: Path, urls: list[str]) -> None:
    errors = []
    for url in urls:
        try:
            _download_one(url, target)
            _set(running=False, status="done", percent=100, path=str(target), error="")
            return
        except urllib.error.HTTPError as exc:
            errors.append(f"HTTP {exc.code} @ {url}")
        except Exception as exc:                  # noqa: BLE001 - 逐个源降级
            errors.append(f"{exc} @ {url}")
    hint = ("自动下载失败，请手动下载权重后放到 configs.yaml 的 model_path 位置。"
            "下载地址: https://github.com/HaixiangZhang/RicePest-YOLO11x-P2/releases")
    _set(running=False, status="error",
         error="；".join(errors) + "。" + hint, path=str(target))


def start_download() -> dict:
    """启动后台下载（已在下载中则直接返回当前状态）。"""
    with _LOCK:
        if _STATE["running"]:
            return dict(_STATE)
        _STATE.update(running=True, status="running", percent=0, error="",
                      done_bytes=0, total_bytes=0)

    target = _target_path()
    _set(path=str(target))
    urls = _candidate_urls()
    thread = threading.Thread(
        target=_worker, args=(target, urls), name="weight-download", daemon=True,
    )
    thread.start()
    return state()


def reset_state() -> None:
    """测试辅助: 清空状态。"""
    with _LOCK:
        _STATE.update(running=False, status="idle", done_bytes=0, total_bytes=0,
                      percent=0, path="", error="", source="")
