"""files — HTTP 文件响应工具（支持 Range，供视频拖动进度复用）。

``routes_jobs``（标注视频）与 ``routes_uploads``（上传源视频预览）共用，
避免两份 Range 解析逻辑漂移。
"""

import re
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, Response, StreamingResponse

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK = 1024 * 256


def range_file_response(path: Path, request: Request, media_type: str):
    """带 HTTP Range 的文件响应（支持浏览器 seek）。无 Range 时走普通 FileResponse。"""
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    match = _RANGE_RE.match(range_header) if range_header else None
    if match is None:
        return FileResponse(str(path), media_type=media_type)

    start_text, end_text = match.groups()
    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    else:                                   # 后缀范围: bytes=-N
        start = max(0, file_size - int(end_text or 0))
        end = file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        return Response(status_code=416,
                        headers={"Content-Range": f"bytes */{file_size}"})

    length = end - start + 1

    def iter_file():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                data = f.read(min(_CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iter_file(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )