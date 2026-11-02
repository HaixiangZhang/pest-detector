"""routes_uploads — 用户上传视频的存取（用户数据目录 ``data/uploads/``）。

设计要点:
    - 落盘位置与 ``runs/``（任务产物）分开: 上传是"用户资产"，需跨会话保留、
      可重复跑；产物是"某次运行的结果"，可清理。
    - **流式原始请求体**: 前端用 ``POST /api/uploads?name=<文件名>`` 直接把
      ``File`` 当 body 发过来（非 multipart），服务端 ``request.stream()`` 边收边写，
      内存占用与文件大小无关；也因此不需要 ``python-multipart`` 依赖。
    - 同名/同内容去重: 按内容 sha256 前 8 位命名，重复上传同一文件不占额外空间。
    - 路径安全: 文件名经 ``safe_filename`` 净化，产物名再按白名单回查，阻断路径穿越。
    - 大小限制: 默认 4GB，可用 ``PESTDET_MAX_UPLOAD_MB`` 覆盖。

上传后的 ``path``（相对项目根，如 ``data/uploads/xxx.mp4``）可直接作为
``POST /api/jobs`` 的 ``source``，因此"上传 → 建任务"无需再走服务器目录。
"""

import hashlib
import os
import uuid
from pathlib import Path

from anyio import to_thread
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from pestdet.api.files import range_file_response
from pestdet.infra.media import is_video, probe_duration, safe_filename, size_mb
from pestdet.infra.paths import PROJECT_ROOT, UPLOADS_DIR

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

_MAX_UPLOAD_BYTES = int(os.environ.get("PESTDET_MAX_UPLOAD_MB", "4096")) * 1024 * 1024
_CHUNK = 1024 * 1024


@router.post("", status_code=201)
async def upload_video(request: Request,
                       name: str = Query(..., description="原始文件名（含扩展名）")) -> dict:
    """流式接收上传的源视频并落盘到 ``data/uploads/``（内容去重）。

    返回项可直接用作新建任务的 ``source``。
    """
    safe = safe_filename(name)
    if not is_video(Path(safe)):
        raise HTTPException(status_code=400,
                            detail=f"不支持的文件类型: {safe}（仅支持常见视频格式）")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = UPLOADS_DIR / f".{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    written = 0
    out = await to_thread.run_sync(tmp.open, "wb")
    failure: HTTPException | None = None
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                failure = HTTPException(
                    status_code=413,
                    detail=f"文件超过上限 {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                break
            digest.update(chunk)
            await to_thread.run_sync(out.write, chunk)
    except Exception as exc:                    # 网络中断 / 磁盘异常
        failure = HTTPException(status_code=500, detail=f"写入失败: {exc}")
    finally:
        await to_thread.run_sync(out.close)

    if failure is not None:
        tmp.unlink(missing_ok=True)
        raise failure
    if written == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="空文件")

    stem = Path(safe).stem
    ext = Path(safe).suffix.lower()
    final = UPLOADS_DIR / f"{stem}_{digest.hexdigest()[:8]}{ext}"
    if final.exists():                          # 内容已存在 → 去重
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(final)

    return _item(final)


@router.get("")
def list_uploads() -> dict:
    """已上传视频列表（按修改时间倒序）。这是刷新/重开网页后仍可见的"历史"。"""
    items = []
    if UPLOADS_DIR.exists():
        files = [p for p in UPLOADS_DIR.iterdir()
                 if p.is_file() and not p.name.startswith(".") and is_video(p)]
        for path in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
            items.append(_item(path))
    return {"root": str(UPLOADS_DIR), "items": items}


@router.get("/{name}/video")
def get_upload_video(name: str, request: Request):
    """上传源视频预览（支持 Range，可拖动进度）。"""
    path = _resolve(name)
    return range_file_response(path, request, media_type="video/mp4")


@router.get("/{name}/download")
def download_upload(name: str) -> FileResponse:
    """下载原始上传文件。"""
    path = _resolve(name)
    return FileResponse(str(path), media_type="application/octet-stream",
                        filename=path.name)


@router.delete("/{name}")
def delete_upload(name: str) -> dict:
    """删除上传文件。"""
    path = _resolve(name)
    path.unlink()
    return {"deleted": path.name}


# ---------------------------------------------------------------- 内部

def _resolve(name: str) -> Path:
    """按白名单回查真实文件，阻断路径穿越（只认目录下的直接子文件）。"""
    safe = safe_filename(name)
    path = UPLOADS_DIR / safe
    if safe != name or not path.is_file():
        raise HTTPException(status_code=404, detail=f"上传文件不存在: {name}")
    return path


def _item(path: Path) -> dict:
    return {
        "name": path.name,
        "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "size_mb": size_mb(path),
        "duration_s": probe_duration(path),
        "uploaded_at": path.stat().st_mtime,
        "url": f"/api/uploads/{path.name}/video",
    }