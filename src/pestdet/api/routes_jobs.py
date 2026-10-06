"""routes_jobs — 任务路由: 创建 / 列表 / 详情 / SSE 事件 / 取消 / 产物。

产物读取统一从 ``Job.out_dir`` 出发，文件名取自该任务生效参数
（``video_name`` / ``json_name`` / ``snapshots.dir_name``），保证与 CLI 产物一致。
"""

import asyncio
import json
import queue
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from pestdet.api.deps import Pagination, get_service
from pestdet.api.files import range_file_response
from pestdet.infra.paths import PROJECT_ROOT
from pestdet.services.analyze import AnalyzeService

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class CreateJobBody(BaseModel):
    """新建任务请求体。``params`` 与 configs.yaml 同构（可为部分字段）。"""

    source: str = Field(description="服务器上视频路径（相对项目根或绝对路径）")
    mode: Literal["sahi", "direct"] = "sahi"
    params: dict = Field(default_factory=dict, description="参数覆盖（嵌套 dict）")
    preset: str | None = Field(default=None, description="参数预设名")


# ---------------------------------------------------------------- 创建 / 列表

@router.post("", status_code=201)
def create_job(body: CreateJobBody, service: AnalyzeService = Depends(get_service)) -> dict:
    """创建并启动任务。配置非法返回 422 + 字段级错误。"""
    job = service.create_job(source=body.source, mode=body.mode,
                             params=body.params, preset=body.preset)
    return {"job_id": job.id, "job": job.to_dict()}


@router.get("")
def list_jobs(page: Pagination = Depends(), service: AnalyzeService = Depends(get_service)) -> dict:
    """任务列表（创建时间倒序 + 分页）。"""
    jobs = service.list_jobs(limit=page.limit, offset=page.offset)
    return {"total": service.count_jobs(),
            "limit": page.limit, "offset": page.offset,
            "items": [j.to_dict() for j in jobs]}


# ---------------------------------------------------------------- 详情 / 取消

@router.get("/{job_id}")
def get_job(job_id: str, service: AnalyzeService = Depends(get_service)) -> dict:
    """任务状态 + 进度快照 + 结果摘要。"""
    return _job_or_404(service, job_id).to_dict()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, service: AnalyzeService = Depends(get_service)) -> dict:
    """请求取消。任务已终态返回 ``cancelled: false``。"""
    _job_or_404(service, job_id)
    accepted = service.cancel_job(job_id)
    return {"job_id": job_id, "cancelled": accepted}


# ---------------------------------------------------------------- SSE 事件流

@router.get("/{job_id}/events")
async def job_events(job_id: str, request: Request,
                     service: AnalyzeService = Depends(get_service)) -> StreamingResponse:
    """SSE: 进度事件 + 日志行，直到任务终态（``type=done``）。

    订阅时会回放该任务已发生的历史事件，因此晚连接的客户端不会丢进度。
    """
    _job_or_404(service, job_id)
    q = service.bus.subscribe(job_id)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = q.get_nowait()
                except queue.Empty:
                    if service.bus.is_closed(job_id) and q.empty():
                        break
                    await asyncio.sleep(0.2)      # 轮询间隔: 足够实时，又不空转
                    continue
                yield _sse(event)
                if event.get("type") == "done":
                    break
        finally:
            service.bus.unsubscribe(job_id, q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",        # 反代下禁用缓冲，保证逐条推送
        },
    )


# ---------------------------------------------------------------- 产物

@router.get("/{job_id}/result")
def get_result(job_id: str, service: AnalyzeService = Depends(get_service)) -> FileResponse:
    """返回 result.json。"""
    job = _job_or_404(service, job_id)
    path = _artifact(job, "json")
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="结果 JSON 尚未生成")
    return FileResponse(str(path), media_type="application/json")


@router.get("/{job_id}/video")
def get_video(job_id: str, request: Request,
              service: AnalyzeService = Depends(get_service)):
    """标注视频；支持 HTTP Range，浏览器可拖动进度。"""
    job = _job_or_404(service, job_id)
    path = _artifact(job, "video")
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="标注视频尚未生成")
    return range_file_response(path, request, media_type="video/mp4")


@router.get("/{job_id}/frames")
def list_frames(job_id: str, service: AnalyzeService = Depends(get_service)) -> dict:
    """检出帧快照列表。"""
    job = _job_or_404(service, job_id)
    directory = _frames_dir(job)
    items = []
    if directory is not None and directory.exists():
        for path in sorted(directory.iterdir()):
            if path.is_file():
                items.append({
                    "name": path.name,
                    "url": f"/api/jobs/{job_id}/frames/{path.name}",
                    "size_kb": round(path.stat().st_size / 1024, 1),
                })
    return {"count": len(items), "items": items}


@router.get("/{job_id}/frames/{name}")
def get_frame(job_id: str, name: str,
              service: AnalyzeService = Depends(get_service)) -> FileResponse:
    """单张快照图片。"""
    job = _job_or_404(service, job_id)
    if Path(name).name != name:                 # 阻断路径穿越
        raise HTTPException(status_code=400, detail="非法文件名")
    directory = _frames_dir(job)
    path = directory / name if directory is not None else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="快照不存在")
    return FileResponse(str(path))


@router.get("/{job_id}/logs")
def get_logs(job_id: str, service: AnalyzeService = Depends(get_service)):
    """完整日志文本。"""
    _job_or_404(service, job_id)
    path = PROJECT_ROOT / "logs" / f"{job_id}.log"
    if not path.exists():
        raise HTTPException(status_code=404, detail="日志尚未生成")
    return Response(path.read_text(encoding="utf-8", errors="replace"),
                    media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------- 内部辅助

def _job_or_404(service: AnalyzeService, job_id: str):
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    return job


def _out_dir(job) -> Path | None:
    return Path(job.out_dir) if job.out_dir else None


def _artifact(job, kind: str) -> Path | None:
    directory = _out_dir(job)
    if directory is None:
        return None
    key = "video_name" if kind == "video" else "json_name"
    return directory / job.params.get(key, f"{kind}.mp4")


def _frames_dir(job) -> Path | None:
    directory = _out_dir(job)
    if directory is None:
        return None
    return directory / job.params.get("snapshots", {}).get("dir_name", "frames")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"