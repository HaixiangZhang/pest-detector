"""deps — FastAPI 依赖项。

服务单例挂在 ``app.state.service``（lifespan 里创建），路由通过依赖注入取用，
便于测试时替换（TestClient + 覆盖 app.state）。
"""

from fastapi import Query, Request

from pestdet.services.analyze import AnalyzeService


def get_service(request: Request) -> AnalyzeService:
    """取应用级 AnalyzeService 单例。"""
    return request.app.state.service


class Pagination:
    """通用分页参数（limit / offset）。"""

    def __init__(self,
                 limit: int = Query(50, ge=1, le=500, description="每页条数"),
                 offset: int = Query(0, ge=0, description="偏移量")):
        self.limit = limit
        self.offset = offset