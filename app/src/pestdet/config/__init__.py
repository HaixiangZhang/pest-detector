"""config 包 — 配置模型与加载。

对外接口:
    from pestdet.config import load_config, validate_config, merge_overrides, to_json_schema
    from pestdet.config import ConfigError, PipelineConfig

设计要点:
    - **无导入期副作用**: 不再在 import 时读盘校验（原 utils/config.py 会，且失败即 SystemExit）
    - **失败抛 ConfigError**: 携带逐条字段级错误，由 CLI / API 决定如何展示
    - **每任务独立实例**: load_config() 每次返回新的普通 dict，可安全并发使用
"""

from pestdet.config.errors import ConfigError, format_validation_errors
from pestdet.config.loader import (
    CONFIG_PATH,
    load_config,
    merge_overrides,
    to_json_schema,
    validate_config,
)
from pestdet.config.schema import PipelineConfig

__all__ = [
    "CONFIG_PATH",
    "ConfigError",
    "PipelineConfig",
    "format_validation_errors",
    "load_config",
    "merge_overrides",
    "to_json_schema",
    "validate_config",
]