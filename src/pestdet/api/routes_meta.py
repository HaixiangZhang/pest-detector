"""routes_meta — 元信息路由: 可用视频 / 已登记权重 / 参数 Schema / 预设。

前端「新建任务」页靠这几个接口渲染下拉与表单，无需硬编码任何参数。
"""

from fastapi import APIRouter
import yaml

from pestdet.config import load_config, to_json_schema
from pestdet.infra.media import is_video, probe_duration, size_mb
from pestdet.infra.paths import PROJECT_ROOT
from pestdet.infra.registry import list_weights
from pestdet.services.analyze import PRESETS_DIR

router = APIRouter(prefix="/api/meta", tags=["meta"])

VIDEOS_DIR = PROJECT_ROOT / "videos"


@router.get("/videos")
def list_videos() -> dict:
    """列出 ``videos/`` 下服务器自带视频（名称、相对路径、大小、时长）。"""
    items = []
    if VIDEOS_DIR.exists():
        for path in sorted(VIDEOS_DIR.rglob("*")):
            if path.is_file() and is_video(path):
                items.append({
                    "name": path.name,
                    "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    "size_mb": size_mb(path),
                    "duration_s": probe_duration(path),
                })
    return {"root": str(VIDEOS_DIR), "items": items}


@router.get("/weights")
def list_registered_weights() -> dict:
    """列出已登记权重（pest{N} 版本链）。"""
    return {"items": list_weights()}


@router.get("/config-schema")
def config_schema() -> dict:
    """参数 JSON Schema（前端生成表单）+ 当前默认值（configs.yaml）。"""
    return {"schema": to_json_schema(), "defaults": load_config()}


@router.get("/presets")
def list_presets() -> dict:
    """列出 ``configs/presets/*.yaml`` 预设，并附带其**增量覆盖**内容。

    ``params`` 只含该预设显式写了的字段（未写的沿用 configs.yaml），
    前端可据此展示"这个预设到底改了什么"。
    """
    items = []
    if PRESETS_DIR.exists():
        for path in sorted(PRESETS_DIR.glob("*.yaml")):
            try:
                params = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                params = {}
            items.append({
                "name": path.stem,
                "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "params": params,
            })
    return {"items": items}