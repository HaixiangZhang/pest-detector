"""config — 部署配置（项目根 configs.yaml）的加载与字段级校验。


完成: 读 yaml → 字段级校验 → 产出进程内唯一的 PIPELINE_CONFIG。

用法:
    from utils.config import PIPELINE_CONFIG, deep_update

字段级校验尽早暴露拼写/类型/取值错误；失败则逐条打印并以非零码退出。
mask / tracker / snapshots 三节同样必须写全（不再有"留空即用模块默认值"的兜底），
其字段名与 utils 各模块消费的 key 一一对应，写错会直接报"未知字段"。

顶层只 import yaml + 路径常量（无 cv2/numpy/torch/ultralytics）。
"""

import yaml

from utils.paths import PROJECT_ROOT

PIPELINE_CONFIG_PATH = PROJECT_ROOT / "configs.yaml"


def deep_update(base: dict, over: dict) -> dict:
    """递归合并（用于让 CLI/调用方只覆盖想改的字段）。"""
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base


# ---- 配置校验: 字段级检查，尽早暴露拼写/类型/取值错误 ----
_PIPELINE_SCHEMA = {
    "model_path": {"type": str, "required": True},
    "mode": {"type": str, "required": True, "choices": ("sahi", "direct")},
    "output_root": {"type": str, "required": True},
    "save_video": {"type": bool, "required": True},
    "save_json": {"type": bool, "required": True},
    "video_name": {"type": str, "required": True},
    "json_name": {"type": str, "required": True},
    "save_track_path": {"type": bool, "required": True},
    "progress_every": {"type": int, "required": True, "min": 1},
    "frame_stride": {"type": int, "required": True, "min": 1},
    "max_frames": {"type": int, "required": True, "min": 0},
    "sahi": {
        "type": dict, "required": True,
        "fields": {
            "slice_size": {"type": int, "required": True, "min": 32},
            "overlap_ratio": {"type": float, "required": True, "min": 0.0, "max": 0.95},
            "conf": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "iou": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "batch": {"type": int, "required": True, "min": 1},
            "device": {"type": (int, str), "required": True},
            "quantize": {"type": (int, type(None)), "choices": (None, 8, 16)},
            "fusion": {"type": str, "choices": ("wbf", "nms")},
            "min_coverage": {"type": float, "min": 0.0, "max": 1.0},
            "multi_scale": {"type": bool},
            "scale_sizes": {"type": list},
        },
    },
    "direct": {
        "type": dict, "required": True,
        "fields": {
            "imgsz": {"type": int, "required": True, "min": 32},
            "conf": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "iou": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "device": {"type": (int, str), "required": True},
            "quantize": {"type": (int, type(None)), "choices": (None, 8, 16)},
            "max_det": {"type": int, "min": 1},
            "batch": {"type": int, "required": True, "min": 1},
        },
    },
    "draw": {
        "type": dict, "required": True,
        "fields": {
            "box": {"type": bool, "required": True},
            "track_id": {"type": bool, "required": True},
            "score": {"type": bool, "required": True},
            "trail": {"type": bool, "required": True},
            "panel": {"type": bool, "required": True},
            "roi_outline": {"type": bool, "required": True},
            "trail_len": {"type": int, "required": True, "min": 1},
            "thickness": {"type": int, "required": True, "min": 1},
            "font_scale": {"type": float, "required": True, "min": 0.1},
            "box_color": {"type": list, "required": True},
            "trail_color": {"type": list, "required": True},
            "roi_color": {"type": list, "required": True},
            "text_color": {"type": list, "required": True},
        },
    },
    "encode": {
        "type": dict, "required": True,
        "fields": {
            "h264": {"type": bool, "required": True},
            "ffmpeg": {"type": str, "required": True},
            "crf": {"type": int, "required": True, "min": 0, "max": 51},
            "preset": {"type": str, "required": True,
                       "choices": ("ultrafast", "superfast", "veryfast", "faster",
                                   "fast", "medium", "slow", "slower", "veryslow")},
        },
    },
    "mask": {
        "type": dict, "required": True,
        "fields": {
            "enabled": {"type": bool, "required": True},
            "mode": {"type": str, "required": True, "choices": ("auto", "manual")},
            "quad": {"type": list, "required": True},
            "refresh_every": {"type": int, "required": True, "min": 0},
            "max_area_jump": {"type": float, "required": True, "min": 0.0},
            "expand_ratio": {"type": float, "required": True, "min": 0.0},
            "fill": {"type": int, "required": True, "min": 0, "max": 255},
            "filter_outside": {"type": bool, "required": True},
            "detect_scale": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "hsv_lower": {"type": list, "required": True},
            "hsv_upper": {"type": list, "required": True},
            "morph_kernel": {"type": int, "required": True, "min": 1},
            "min_area_ratio": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "max_area_ratio": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "approx_eps_ratio": {"type": float, "required": True, "min": 0.0},
        },
    },
    "tracker": {
        "type": dict, "required": True,
        "fields": {
            "high_thresh": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "low_thresh": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "new_track_thresh": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "match_thresh": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "second_match_thresh": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "boot_match_iou": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "match_dist_gate": {"type": float, "required": True, "min": 0.0},
            "track_buffer": {"type": int, "required": True, "min": 0},
            "min_track_frames": {"type": int, "required": True, "min": 0},
            "merge_gap_frames": {"type": int, "required": True, "min": 0},
            "merge_dist_threshold": {"type": float, "required": True, "min": 0.0},
            "merge_speed_max": {"type": float, "required": True, "min": 0.0},
            "spatial_overlap": {"type": float, "required": True, "min": 0.0, "max": 1.0},
            "confirm_enabled": {"type": bool, "required": True},
            "confirm_window": {"type": int, "required": True, "min": 0},
            "confirm_min_hits": {"type": int, "required": True, "min": 0},
        },
    },
    "snapshots": {
        "type": dict, "required": True,
        "fields": {
            "enabled": {"type": bool, "required": True},
            "dir_name": {"type": str, "required": True},
            "prefix": {"type": str, "required": True},
            "fmt": {"type": str, "required": True, "choices": ("jpg", "png")},
            "quality": {"type": int, "required": True, "min": 1, "max": 100},
            "min_score": {"type": float, "required": True, "min": 0.0, "max": 1.0},
        },
    },
}


def _type_name(expected) -> str:
    if isinstance(expected, tuple):
        return " 或 ".join(_type_name(e) for e in expected)
    names = {int: "int", float: "float", bool: "bool", str: "str",
             dict: "dict", list: "list", type(None): "null"}
    return names.get(expected, getattr(expected, "__name__", str(expected)))


def validate_pipeline_config(cfg: dict) -> None:
    """字段级校验部署配置；有问题则逐条列出并以非零码退出。"""
    errors: list = []

    def type_ok(value, expected) -> bool:
        if isinstance(expected, tuple):
            return any(type_ok(value, e) for e in expected)
        if expected is bool:
            return isinstance(value, bool)
        if expected is int:      # 注意 bool 是 int 的子类，必须排除
            return isinstance(value, int) and not isinstance(value, bool)
        if expected is float:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected is type(None):
            return value is None
        return isinstance(value, expected)

    def is_num(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def check(node, schema, prefix=""):
        if not isinstance(node, dict):
            errors.append(f"{prefix.rstrip('.')}: 应为映射（dict），实际 {type(node).__name__}")
            return
        for key, spec in schema.items():
            path = f"{prefix}{key}"
            if key not in node:
                if spec.get("required"):
                    errors.append(f"{path}: 缺少必填字段")
                continue
            value = node[key]
            if not type_ok(value, spec["type"]):
                errors.append(f"{path}: 类型应为 {_type_name(spec['type'])}，"
                              f"实际 {type(value).__name__}（{value!r}）")
                continue
            if "choices" in spec and value not in spec["choices"]:
                errors.append(f"{path}: 取值应为 {'/'.join(map(str, spec['choices']))} 之一，"
                              f"实际 {value!r}")
                continue
            if "min" in spec and is_num(value) and value < spec["min"]:
                errors.append(f"{path}: 应 ≥ {spec['min']}，实际 {value!r}")
            if "max" in spec and is_num(value) and value > spec["max"]:
                errors.append(f"{path}: 应 ≤ {spec['max']}，实际 {value!r}")
            if "fields" in spec:
                check(value, spec["fields"], prefix=f"{path}.")
            allowed = spec.get("allowed")
            if allowed is None and "fields" in spec:
                allowed = tuple(spec["fields"])
            if allowed is not None:
                for extra in value:
                    if extra not in allowed:
                        errors.append(f"{path}.{extra}: 未知字段（可用字段: {', '.join(allowed)}）")
        if prefix == "":
            for extra in node:
                if extra not in schema:
                    errors.append(f"{extra}: 未知的顶层字段（可用字段: {', '.join(schema)}）")

    check(cfg, _PIPELINE_SCHEMA)
    if errors:
        print(f"\n[错误] 部署配置校验失败: {PIPELINE_CONFIG_PATH}")
        for e in errors:
            print(f"  - {e}")
        print(f"\n请修正 {PIPELINE_CONFIG_PATH.name} 后重试。\n")
        raise SystemExit(1)


def load_pipeline_config() -> dict:
    """加载部署配置 configs.yaml（部署参数唯一来源）。

    不做默认值兜底: 文件必须存在且字段写全，缺失/拼错/越界都在这里报错终止，
    避免"配置写错却静默用默认值"这类难查问题。
    """
    if not PIPELINE_CONFIG_PATH.exists():
        print(f"\n[错误] 缺少部署配置: {PIPELINE_CONFIG_PATH}")
        print("（仓库应自带该文件；若被误删，请从版本控制恢复）\n")
        raise SystemExit(1)
    try:
        with open(PIPELINE_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        print(f"\n[错误] 部署配置解析失败: {PIPELINE_CONFIG_PATH}（{e}）\n")
        raise SystemExit(1)
    validate_pipeline_config(cfg)
    return cfg


# 部署参数（唯一来源 = 项目根 configs.yaml；改参数只改那里，不改代码）
PIPELINE_CONFIG = load_pipeline_config()
