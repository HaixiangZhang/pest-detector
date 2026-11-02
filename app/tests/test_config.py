"""配置层测试：校验通过 / 各错误分支 / 覆盖合并不可变 / Schema 导出。"""

import copy

import pytest
from pydantic import BaseModel

from pestdet.config import (
    ConfigError,
    load_config,
    merge_overrides,
    to_json_schema,
    validate_config,
)


def _errors(exc: pytest.ExceptionInfo) -> str:
    return " | ".join(exc.value.errors)


# ---------------------------------------------------------------- 正常路径

def test_shipped_config_is_valid():
    cfg = load_config()
    assert cfg["mode"] in ("sahi", "direct")
    for section in ("sahi", "direct", "draw", "encode", "mask", "tracker", "snapshots"):
        assert isinstance(cfg[section], dict), f"缺少配置节: {section}"


def test_load_config_returns_plain_dict():
    cfg = load_config()
    assert isinstance(cfg, dict)
    assert not isinstance(cfg, BaseModel)   # 刻意返回普通 dict，供 core 下标消费


def test_validate_accepts_loaded_dict():
    cfg = load_config()
    again = validate_config(copy.deepcopy(cfg))
    assert again["tracker"]["track_buffer"] < again["tracker"]["merge_gap_frames"]


# ---------------------------------------------------------------- 错误分支

def test_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "not_here.yaml")
    assert "缺少部署配置" in _errors(exc)


def test_invalid_mode_literal():
    raw = copy.deepcopy(load_config())
    raw["mode"] = "turbo"
    with pytest.raises(ConfigError) as exc:
        validate_config(raw)
    assert "mode: 取值应为 sahi/direct 之一" in _errors(exc)


def test_unknown_field_is_rejected():
    raw = copy.deepcopy(load_config())
    raw["sahi"]["slice_sise"] = 640          # 拼错字段名
    with pytest.raises(ConfigError) as exc:
        validate_config(raw)
    msg = _errors(exc)
    assert "sahi.slice_sise: 未知字段" in msg
    assert "slice_size" in msg               # 提示可用字段


def test_out_of_range_value():
    raw = copy.deepcopy(load_config())
    raw["sahi"]["conf"] = 1.5
    with pytest.raises(ConfigError) as exc:
        validate_config(raw)
    assert "sahi.conf: 应 ≤ 1.0" in _errors(exc)


def test_missing_required_field():
    raw = copy.deepcopy(load_config())
    del raw["tracker"]["high_thresh"]
    with pytest.raises(ConfigError) as exc:
        validate_config(raw)
    assert "tracker.high_thresh: 缺少必填字段" in _errors(exc)


def test_error_format_contains_path():
    raw = copy.deepcopy(load_config())
    raw["mode"] = "turbo"
    try:
        validate_config(raw, path="configs.yaml")
    except ConfigError as e:
        assert "configs.yaml" in e.format()
    else:
        pytest.fail("应当抛出 ConfigError")


# ---------------------------------------------------------------- 覆盖合并

def test_merge_overrides_is_pure():
    base = load_config()
    base_snapshot = copy.deepcopy(base)
    over = {"tracker": {"confirm_enabled": False}, "max_frames": 7}
    over_snapshot = copy.deepcopy(over)

    merged = merge_overrides(base, over)

    assert base == base_snapshot              # 入参 base 不被改
    assert over == over_snapshot              # 入参 over 不被改
    assert merged["max_frames"] == 7
    assert merged["tracker"]["confirm_enabled"] is False
    assert merged["tracker"]["high_thresh"] == base["tracker"]["high_thresh"]   # 其余字段保留


def test_merge_overrides_nested_merge():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    merged = merge_overrides(base, {"a": {"y": 20}})
    assert merged == {"a": {"x": 1, "y": 20}, "b": 3}


# ---------------------------------------------------------------- Schema 导出

def test_to_json_schema():
    schema = to_json_schema()
    assert schema["title"] == "PipelineConfig"
    assert "mode" in schema["properties"]
    assert "tracker" in schema["properties"]