"""app — FastAPI 装配。

- lifespan 里创建进程级 AnalyzeService 单例（任务库 / 事件总线 / 单 worker 执行器）
- 注册全部路由与领域异常处理器
- 若 ``web/dist`` 存在（前端已构建），挂到根路径作为静态站点；否则只提供 API

启动:
    python -m pestdet.server --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from pestdet import __version__
from pestdet.api import routes_jobs, routes_meta, routes_system, routes_uploads
from pestdet.api.errors import install_exception_handlers
from pestdet.infra.logging import configure_logging, get_logger
from pestdet.infra.paths import PROJECT_ROOT
from pestdet.services.analyze import AnalyzeService

WEB_DIST = PROJECT_ROOT / "web" / "dist"


class SPAStaticFiles(StaticFiles):
    """静态站点 + SPA 回退。

    前端是 BrowserRouter 单页应用，``/jobs``、``/jobs/<id>`` 这类路径在磁盘上没有
    对应文件；若不做回退，直接访问或刷新这些深链会 404。这里把未命中的非 ``/api/``
    路径统一回 ``index.html``，交给前端路由处理。
    """

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not scope["path"].startswith("/api/"):
                return await super().get_response("index.html", scope)
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(level="INFO")
    logger = get_logger(__name__)
    app.state.service = AnalyzeService()
    logger.info("pest_detector API 就绪（版本 %s）", __version__)
    try:
        yield
    finally:
        app.state.service.runner.shutdown(wait=False)
        logger.info("pest_detector API 已停止")


def create_app() -> FastAPI:
    """构建 FastAPI 应用（uvicorn factory 入口）。"""
    app = FastAPI(
        title="pest_detector API",
        description="4K 航拍视频害虫检测与跨帧去重计数",
        version=__version__,
        lifespan=lifespan,
        # Swagger 放到 /api/docs：根路径的 /docs 留给前端「使用文档」页
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # MVP 前后端分离开发时跨域放开；生产由同源静态站点提供，可收紧
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_exception_handlers(app)
    app.include_router(routes_meta.router)
    app.include_router(routes_system.router)
    app.include_router(routes_uploads.router)
    app.include_router(routes_jobs.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    # 前端构建产物存在时挂到根路径（API 路由已先注册，优先级更高）
    if WEB_DIST.exists():
        app.mount("/", SPAStaticFiles(directory=str(WEB_DIST), html=True), name="web")

    return app