"""logging — 日志装配: 控制台 + 可选文件 + 可选回调（事件总线）。

统一挂在 ``pestdet`` logger 下，各模块用 ``logging.getLogger(__name__)``
（如 ``pestdet.core.tracker``）即可自动继承配置。

用法:
    from pestdet.infra.logging import configure_logging, get_logger
    configure_logging(level="INFO")                      # 控制台
    configure_logging(log_file="logs/job-xxx.log")       # 追加文件（按任务隔离）
    configure_logging(sink=bus_sink)                     # 同时把日志行推给 SSE
    logger = get_logger(__name__)
"""

import logging
import sys
from pathlib import Path

_ROOT_NAME = "pestdet"
# 文件日志带时间/级别/来源；控制台默认只用消息体（CLI 输出保持干净，消息自带 [1/6] 等前缀）
_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_CONSOLE_FORMAT = "%(message)s"


class _CallbackHandler(logging.Handler):
    """把格式化后的日志行交给回调（如事件总线 → SSE 实时日志）。"""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(self.format(record))
        except Exception:       # 回调失败不能影响正常日志
            self.handleError(record)


def get_logger(name: str | None = None) -> logging.Logger:
    """取 pestdet 命名空间下的 logger。"""
    if not name or name == "__main__":
        return logging.getLogger(_ROOT_NAME)
    if name.startswith(_ROOT_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


def configure_logging(level: str = "INFO", log_file=None, stream=None,
                      console_format: str = _CONSOLE_FORMAT, sink=None) -> logging.Logger:
    """装配 pestdet logger（幂等: 重复调用会先清掉旧 handler）。

    Args:
        level: 日志级别名（DEBUG/INFO/WARNING/...）
        log_file: 可选日志文件路径；父目录不存在会自动创建
        stream: 控制台输出流；默认 stderr
        console_format: 控制台 / 回调日志格式；默认只输出消息体（CLI 友好）
        sink: 可选回调 ``callable(line: str)``，每条日志触发一次（供 SSE 推送）
    """
    logger = logging.getLogger(_ROOT_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(stream or sys.stderr)
    console.setFormatter(logging.Formatter(console_format))
    logger.addHandler(console)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        logger.addHandler(file_handler)

    if sink is not None:
        callback_handler = _CallbackHandler(sink)
        callback_handler.setFormatter(logging.Formatter(console_format))
        logger.addHandler(callback_handler)

    return logger