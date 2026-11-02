"""api 包 — FastAPI 装配、路由与异常映射。

对外接口:
    from pestdet.api.app import create_app
"""

from pestdet.api.app import create_app

__all__ = ["create_app"]