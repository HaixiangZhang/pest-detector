"""routes_meta — 元信息路由: 可用视频 / 已登记权重 / 参数 Schema / 预设 / 内置文档。

前端「新建任务」页靠这几个接口渲染下拉与表单，无需硬编码任何参数；
「使用文档」页则直接渲染仓库里的 Markdown（离线可用，不依赖外网）。
"""

import re

from fastapi import APIRouter, HTTPException
import yaml

from pestdet.config import load_config, merge_overrides, to_json_schema, validate_config
from pestdet.infra.media import is_video, probe_duration, size_mb
from pestdet.infra.paths import PROJECT_ROOT
from pestdet.infra.registry import list_weights
from pestdet.services.analyze import PRESETS_DIR

router = APIRouter(prefix="/api/meta", tags=["meta"])

VIDEOS_DIR = PROJECT_ROOT / "videos"

DEFAULT_PRESET = "default"
PRESET_LABELS = {DEFAULT_PRESET: "默认"}
PRESET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

# 内置文档白名单（只读仓库内的固定文件，避免任意路径读取）
DOCS = {
    "web-guide": ("docs/WEB_GUIDE.md", "网页端使用说明"),
    "deploy": ("docs/DEPLOY.md", "部署与运维"),
    "readme": ("README.md", "项目总览"),
}


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
    """列出参数预设，并附带其**增量覆盖**内容。

    ``params`` 只含该预设显式写了的字段（未写的沿用 configs.yaml），
    前端可据此展示"这个预设到底改了什么"。``default`` 恒存在（默认配置），
    文件缺失时用空覆盖兜底，保证下拉里总有"默认"。
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
                "label": PRESET_LABELS.get(path.stem, path.stem),
                "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "params": params,
            })
    if not any(item["name"] == DEFAULT_PRESET for item in items):
        items.insert(0, {
            "name": DEFAULT_PRESET,
            "label": PRESET_LABELS[DEFAULT_PRESET],
            "path": f"configs/presets/{DEFAULT_PRESET}.yaml",
            "params": {},
        })
    return {"items": items}


@router.put("/presets/{name}")
def save_preset(name: str, body: dict) -> dict:
    """保存推理配置为预设（前端「保存推理配置」按钮）。

    body: ``{"params": {...}}``，与 configs.yaml 同构的**部分字段**。
    先按"configs.yaml + params"整体校验，通过后才落盘，避免写进一份非法配置。
    """
    if not PRESET_NAME_PATTERN.match(name):
        raise HTTPException(status_code=400, detail="预设名只能包含字母、数字、下划线和短横线")
    params = (body or {}).get("params")
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="params 必须是对象")

    effective = validate_config(merge_overrides(load_config(), params))   # 非法 → 422
    # 只保存用户显式给出的字段（增量覆盖），不回写整块默认值
    params = {key: value for key, value in params.items() if key in effective}

    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    path = PRESETS_DIR / f"{name}.yaml"
    header = ("# 参数预设: " + PRESET_LABELS.get(name, name) +
              "（网页端「保存推理配置」写入，可手工编辑）\n"
              "# 只写要覆盖 configs.yaml 的字段；其余沿用默认值。\n")
    path.write_text(header + yaml.safe_dump(params, allow_unicode=True,
                                            sort_keys=False, default_flow_style=False),
                    encoding="utf-8")
    return {
        "name": name,
        "label": PRESET_LABELS.get(name, name),
        "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "params": params,
    }


@router.get("/docs")
def list_docs() -> dict:
    """内置文档清单（网页端「使用文档」页的导航）。"""
    return {"items": [
        {"name": key, "title": title, "exists": (PROJECT_ROOT / rel).exists()}
        for key, (rel, title) in DOCS.items()
    ]}


@router.get("/docs/{name}")
def get_doc(name: str) -> dict:
    """返回指定文档的 Markdown 原文（由前端本地渲染）。"""
    entry = DOCS.get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"文档不存在: {name}")
    rel, title = entry
    path = PROJECT_ROOT / rel
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"文档文件缺失: {rel}")
    return {"name": name, "title": title,
            "content": path.read_text(encoding="utf-8", errors="replace")}
