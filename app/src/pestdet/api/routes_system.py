"""routes_system — 系统环境 / 硬件 / 权重状态与自动下载。

前端每次打开页面都会调 ``GET /api/system/info``（带 ``refresh=true``）：
拿到 CPU / 内存 / GPU / 依赖版本 / 权重就绪状态；权重不就绪时再调
``POST /api/system/weights/download`` 启动后台下载，并轮询 GET 看进度。
"""

from fastapi import APIRouter, Query

from pestdet.services import system, weights

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info")
def system_info(refresh: bool = Query(False, description="true = 重新探测（会重新初始化 CUDA）")) -> dict:
    """主机 + 加速卡 + 软件环境 + 权重状态。"""
    return system.probe(force=refresh)


@router.get("/weights/download")
def download_state() -> dict:
    """默认权重下载进度（未下载过时 status=idle）。"""
    return weights.state()


@router.post("/weights/download")
def start_download() -> dict:
    """启动默认权重下载（幂等：下载中重复调用只返回进度）。"""
    return weights.start_download()
