"""events — 任务进度/日志事件总线（进程内 pub/sub，支持多订阅者）。

**这是多用户阶段的替换点之一**: 本期为内存实现；当部署多 Uvicorn worker 或需要
跨进程订阅时，换成 Redis Pub/Sub 即可，订阅/发布接口不变
（见 docs/PLAN_web_mvp.md 第 8 节）。

事件统一为带 ``type`` 的 dict:
    {"type": "status",   "status": "running", "at": "2026-10-05 12:00:00"}
    {"type": "progress", "done": 12, "total": 300, "elapsed": 4.1}
    {"type": "log",      "line": "[3/6] 逐帧检测+关联: 12/300 帧"}
    {"type": "done",     "status": "succeeded", "summary": {...}}

发布方在**推理线程**里调用 ``publish``，因此队列满时只丢弃、绝不阻塞。
"""

import queue
import threading

_TERMINAL_TYPES = {"done"}
_HISTORY_MAX = 500


class EventBus:
    """按 job_id 分组的进程内事件总线。"""

    def __init__(self, history_max: int = _HISTORY_MAX):
        self._subs: dict[str, list[queue.Queue]] = {}
        self._history: dict[str, list] = {}
        self._lock = threading.Lock()
        self._history_max = history_max

    def publish(self, job_id: str, event: dict) -> None:
        """发布事件（保留最近 history_max 条供晚订阅者回放）。"""
        with self._lock:
            hist = self._history.setdefault(job_id, [])
            hist.append(event)
            if len(hist) > self._history_max:
                del hist[: len(hist) - self._history_max]
            subs = list(self._subs.get(job_id, ()))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass        # 订阅端消费不过来就丢，绝不阻塞发布方（推理线程）

    def subscribe(self, job_id: str) -> queue.Queue:
        """订阅某任务的事件；先回放已发生的历史，再接收后续。"""
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.setdefault(job_id, []).append(q)
            for ev in self._history.get(job_id, ()):
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    break
        return q

    def unsubscribe(self, job_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subs.get(job_id)
            if not subs:
                return
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subs.pop(job_id, None)

    def is_closed(self, job_id: str) -> bool:
        """是否已发出终态事件（供 SSE 判断流可以结束）。"""
        with self._lock:
            return any(ev.get("type") in _TERMINAL_TYPES
                       for ev in self._history.get(job_id, ()))

    def clear(self, job_id: str) -> None:
        """清掉某任务的历史与订阅（任务终态后释放内存）。"""
        with self._lock:
            self._history.pop(job_id, None)
            self._subs.pop(job_id, None)


# 进程级单例: API 与 runner 通过它对接（多用户阶段换成 Redis 客户端）
bus = EventBus()