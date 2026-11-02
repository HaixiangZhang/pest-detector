"""store — 任务持久化（SQLite，stdlib sqlite3，零部署成本）。

单文件库 ``runs/jobs.db``。每次操作开一条短连接（MVP 并发量低），避免跨线程共享
连接的坑；写操作用一把进程内锁串行化。多用户阶段可直接换库，接口不变。
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from pestdet.infra.paths import PROJECT_ROOT
from pestdet.jobs.models import Job, JobStatus

DB_PATH = PROJECT_ROOT / "runs" / "jobs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    owner       TEXT,
    source      TEXT NOT NULL,
    mode        TEXT NOT NULL,
    params      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    progress    TEXT NOT NULL,
    out_dir     TEXT,
    summary     TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
"""

_JSON_FIELDS = ("params", "progress", "summary", "error")
_TEXT_FIELDS = ("id", "status", "owner", "source", "mode", "created_at",
                "started_at", "finished_at", "out_dir")
_ALL_FIELDS = (*_TEXT_FIELDS, *_JSON_FIELDS)


class JobStore:
    """任务记录的增删查改。"""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_schema()

    # ------------------------------------------------------------ 连接

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._session() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------ CRUD

    def save(self, job: Job) -> None:
        """插入或整体覆盖一条任务记录。"""
        data = job.to_dict()
        row = {k: (json.dumps(data[k], ensure_ascii=False) if k in _JSON_FIELDS else data[k])
               for k in _ALL_FIELDS}
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._lock, self._session() as conn:
            conn.execute(f"INSERT OR REPLACE INTO jobs ({cols}) VALUES ({marks})",
                         list(row.values()))

    def get(self, job_id: str) -> Job | None:
        with self._lock, self._session() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list:
        """按创建时间倒序列出任务。"""
        with self._lock, self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def count(self) -> int:
        with self._lock, self._session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def list_unfinished(self) -> list:
        """列出非终态任务（queued / running），用于进程重启后的对账。"""
        with self._lock, self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status IN (?, ?) ORDER BY created_at DESC",
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def delete(self, job_id: str) -> bool:
        with self._lock, self._session() as conn:
            cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return cur.rowcount > 0


def _row_to_job(row: sqlite3.Row) -> Job:
    d = dict(row)
    for key in _JSON_FIELDS:
        raw = d.get(key)
        d[key] = json.loads(raw) if raw is not None else None
    d["status"] = JobStatus(d["status"])
    return Job(**{k: d[k] for k in _ALL_FIELDS})