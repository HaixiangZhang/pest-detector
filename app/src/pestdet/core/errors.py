"""errors — core 层领域异常。

这些异常由 core 抛出、由上层（services / api / cli）捕获并决定呈现方式，
core 自身不做任何 I/O 或进程级退出。
"""


class PestDetectorError(Exception):
    """本项目领域异常基类。"""


class JobCancelled(PestDetectorError):
    """任务被协作式取消（帧循环内检查到取消信号）。

    Attributes:
        processed: 取消前已处理的帧数（便于上层记录进度快照）
    """

    def __init__(self, processed: int = 0):
        self.processed = int(processed)
        super().__init__(f"任务已取消（已处理 {self.processed} 帧）")