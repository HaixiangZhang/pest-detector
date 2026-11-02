"""errors — 领域异常 → HTTP 状态码 + 结构化 body。

原则: 配置写错返回 **422 + 字段级错误列表**，而不是杀进程或抛 500
（这正是 P0 把 SystemExit 改成 ConfigError 的目的）。

统一错误 body:
    {"code": "...", "message": "...", "errors": [...]?}
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pestdet.config import ConfigError
from pestdet.core.errors import PestDetectorError


def install_exception_handlers(app: FastAPI) -> None:
    """给 app 注册领域异常处理器。"""

    @app.exception_handler(ConfigError)
    async def _config_error(_request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "config_error",
                "message": "部署配置校验失败",
                "errors": exc.errors,
            },
        )

    @app.exception_handler(FileNotFoundError)
    async def _not_found(_request: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"code": "not_found", "message": str(exc) or "资源不存在"},
        )

    @app.exception_handler(PestDetectorError)
    async def _domain_error(_request: Request, exc: PestDetectorError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"code": "domain_error", "message": str(exc)},
        )

    @app.exception_handler(ValueError)
    async def _invalid_argument(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_argument", "message": str(exc)},
        )