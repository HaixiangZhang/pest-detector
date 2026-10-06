"""loader — configs.yaml 的读取 / 校验 / 合并 / JSON Schema 导出。

对外接口:
    load_config()          读盘 + 校验 → 普通 dict（失败抛 ConfigError）
    validate_config(raw)   校验已读入的 dict → 普通 dict
    merge_overrides(base, over)   递归合并（返回新 dict，不修改入参）
    to_json_schema()       导出 JSON Schema（前端表单用）
"""

import copy
from pathlib import Path

import yaml
from pydantic import ValidationError

from pestdet.config.errors import ConfigError, format_validation_errors
from pestdet.config.schema import PipelineConfig
from pestdet.infra.paths import PROJECT_ROOT

CONFIG_PATH = PROJECT_ROOT / "configs.yaml"


def merge_overrides(base: dict, over: dict) -> dict:
    """递归合并覆盖项，返回**新的** dict（不修改 base / over）。

    每个任务持有一份独立配置，故这里必须复制而不能原地改（原 deep_update 是原地改）。
    """
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_overrides(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def validate_config(raw: dict, path=None) -> dict:
    """校验配置 dict，返回规范化后的普通 dict；失败抛 ConfigError。

    返回普通 dict（而非模型对象）是刻意的: core 各模块继续以 ``cfg["tracker"]``
    这样的下标方式消费配置，迁移面最小；模型只承担校验与 Schema 导出职责。
    """
    if not isinstance(raw, dict):
        raise ConfigError(
            [f"配置根节点应为映射（dict），实际 {type(raw).__name__}"], path=path)
    try:
        return PipelineConfig.model_validate(raw).model_dump()
    except ValidationError as exc:
        raise ConfigError(format_validation_errors(exc, PipelineConfig), path=path) from exc


def load_config(path=None) -> dict:
    """加载部署配置（默认项目根 configs.yaml）。

    不做默认值兜底: 文件必须存在且字段写全，缺失 / 拼错 / 越界都在这里报错，
    避免"配置写错却静默用默认值"这类难查问题。

    Raises:
        ConfigError: 文件缺失、YAML 解析失败或字段校验不通过
    """
    config_path = Path(path) if path is not None else CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(
            [f"缺少部署配置: {config_path}",
             "（仓库应自带该文件；若被误删，请从版本控制恢复）"],
            path=config_path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError([f"YAML 解析失败: {exc}"], path=config_path) from exc
    return validate_config(raw, path=config_path)


def to_json_schema() -> dict:
    """导出 JSON Schema（供前端自动生成参数表单 / 校验请求参数）。"""
    return PipelineConfig.model_json_schema()