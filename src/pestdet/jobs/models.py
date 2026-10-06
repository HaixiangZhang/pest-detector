"""models — 任务数据模型与状态机。

状态机: ``queued → running → succeeded | failed | cancelled``
（终态不再变化；cancel 只对 queued / running 有意义）

字段定义见 docs/PLAN_web_mvp.md 第 5 节。``owner`` 为多用户阶段预留，本期恒为 None。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """任务状态。继承 str 便于直接 JSON 序列化与 SQLite 存储。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


def now_str() -> str:
    """当前时间（统一格式，落库与展示共用）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_job_id() -> str:
    """任务 ID: 时间前缀 + 短随机，便于按时间排序与人工辨识。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


@dataclass
class Job:
    """一次检测任务的完整状态（含可复现的参数快照）。"""

    id: str
    source: str
    mode: str
    params: dict
    status: JobStatus = JobStatus.QUEUED
    owner: str | None = None
    created_at: str = field(default_factory=now_str)
    started_at: str | None = None
    finished_at: str | None = None
    progress: dict = field(default_factory=lambda: {"done": 0, "total": 0, "elapsed": 0.0})
    out_dir: str | None = None
    summary: dict | None = None
    error: dict | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "owner": self.owner,
            "source": self.source,
            "mode": self.mode,
            "params": self.params,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "out_dir": self.out_dir,
            "summary": self.summary,
            "error": self.error,
        }