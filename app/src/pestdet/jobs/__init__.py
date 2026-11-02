"""jobs 包 — 任务模型、持久化、事件总线与执行器。

对外接口:
    from pestdet.jobs import Job, JobStatus, JobStore, JobRunner, bus
"""

from pestdet.jobs.events import EventBus, bus
from pestdet.jobs.models import Job, JobStatus, new_job_id
from pestdet.jobs.runner import JobRunner
from pestdet.jobs.store import JobStore

__all__ = ["EventBus", "Job", "JobRunner", "JobStatus", "JobStore", "bus", "new_job_id"]