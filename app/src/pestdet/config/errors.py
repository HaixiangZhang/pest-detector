"""errors — 配置错误类型与 Pydantic 校验错误的双语化。

原实现校验失败直接 ``raise SystemExit(1)``，在 Web 服务里会杀掉整个进程；
现改为抛 ``ConfigError``，由调用方（CLI 打印后退出 / API 转 422）自行处理。
"""

from pydantic import BaseModel, ValidationError


class ConfigError(Exception):
    """配置错误：携带逐条字段级错误。

    Attributes:
        errors: 逐条错误描述（中文，已含字段路径）
        path: 出错的配置文件路径（可选）
    """

    def __init__(self, errors, path=None):
        self.errors = [str(e) for e in errors]
        self.path = path
        super().__init__("部署配置校验失败")

    def format(self, indent: str = "  ") -> str:
        """多行可读文本（CLI 展示用）。"""
        title = "部署配置校验失败"
        if self.path is not None:
            title = f"{title}: {self.path}"
        return "\n".join([title, *(f"{indent}- {e}" for e in self.errors)])


# ---------------------------------------------------------------------------
# Pydantic 校验错误 → 中文逐条消息
# ---------------------------------------------------------------------------

_SIMPLE_TYPES = {
    "int_type": "int",
    "int_parsing": "int",
    "int_from_float": "int",
    "float_type": "float",
    "float_parsing": "float",
    "bool_type": "bool",
    "bool_parsing": "bool",
    "string_type": "str",
    "list_type": "list",
    "dict_type": "dict",
}


def _join_loc(loc) -> str:
    return ".".join(str(p) for p in loc)


def _allowed_fields(root: BaseModel, loc) -> tuple:
    """按字段路径下钻到子模型，返回其允许的字段名（用于"未知字段"提示）。"""
    model = root
    for key in loc:
        field = model.model_fields.get(str(key))
        if field is None:
            return ()
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            model = annotation
        else:
            return ()
    return tuple(model.model_fields)


def _format_one(root: BaseModel, err: dict) -> str:
    loc = err.get("loc", ())
    path = _join_loc(loc)
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}

    if kind == "missing":
        return f"{path}: 缺少必填字段"
    if kind == "extra_forbidden":
        allowed = _allowed_fields(root, loc[:-1])
        hint = f"（可用字段: {', '.join(allowed)}）" if allowed else ""
        return f"{path}: 未知字段{hint}"
    if kind == "literal_error":
        # Pydantic 各版本枚举提示的分隔符不同（"a, b" 或 "a or b"），统一归一到逗号
        expected = str(ctx.get("expected", "")).replace("'", "").replace(" or ", ",")
        choices = "/".join(p.strip() for p in expected.split(",") if p.strip())
        return f"{path}: 取值应为 {choices} 之一"
    if kind in _SIMPLE_TYPES:
        return f"{path}: 类型应为 {_SIMPLE_TYPES[kind]}"
    if kind == "greater_than_equal":
        return f"{path}: 应 ≥ {ctx.get('ge')}"
    if kind == "less_than_equal":
        return f"{path}: 应 ≤ {ctx.get('le')}"

    return f"{path}: {err.get('msg', kind)}"


def format_validation_errors(exc: ValidationError, root: BaseModel) -> list:
    """把 Pydantic ValidationError 转成中文逐条消息列表。"""
    return [_format_one(root, e) for e in exc.errors()]