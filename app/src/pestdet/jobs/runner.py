"""runner — 单 worker 任务执行器。

推理是阻塞式 CPU/GPU 调用，**绝不能跑在 asyncio 事件循环里**；同时 8GB 显存只允许
一个任务持有模型，因此串行执行既正确又省显存。

**这是多用户阶段的替换点之一**: 换 RQ / Celery / arq + Redis 队列即可实现多 worker、
配额与优先级，``submit`` / ``request_cancel`` 接口不变。
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from pestdet.infra.logging import get_logger

logger = get_logger(__name__)


class JobRunner:
    """把任务丢到单 worker 线程池，并支持协作式取消。"""

    def __init__(self, max_workers: int = 1):
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="pestdet-job")
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def submit(self, job_id: str, target) -> None:
        """提交任务。``target(cancel_event)`` 在 worker 线程内执行。

        约定: target 自行捕获异常并落库状态；这里只兜底记录未处理异常。
        """
        cancel_event = threading.Event()
        with self._lock:
            self._cancels[job_id] = cancel_event
        self._pool.submit(self._run, job_id, target, cancel_event)

    def _run(self, job_id: str, target, cancel_event: threading.Event) -> None:
        try:
            target(cancel_event)
        except Exception:
            logger.exception("任务 %s 执行线程未捕获异常", job_id)
        finally:
            with self._lock:
                self._cancels.pop(job_id, None)

    def request_cancel(self, job_id: str) -> bool:
        """置位取消事件。任务不在运行中（未提交或已结束）返回 False。"""
        with self._lock:
            ev = self._cancels.get(job_id)
        if ev is None:
            return False
        ev.set()
        return True

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancels

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait)