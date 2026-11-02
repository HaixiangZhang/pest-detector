"""analyze — AnalyzeService: 编排 配置 + core + 任务状态 + 落盘。

分层位置: ``api / cli → services → jobs → core``。这是唯一把这几层粘起来的地方。

职责:
    1. 建任务: 校验入参 → 合并出**可复现的完整参数快照** → 落库 → 提交 runner
    2. 跑任务: 装配按 job 的日志（文件 + 事件总线）→ 跑 VideoPipeline
    3. 状态流转: queued → running → succeeded / failed / cancelled，全程推事件总线
    4. 取消: 把 runner 的取消事件透传给 pipeline（帧循环内协作式检查）

异常约定: 入参非法抛 ConfigError / ValueError（由 api 映射 4xx）；
          执行期异常一律捕获并落到 Job.error（任务失败，但服务不崩）。
"""

import threading
from pathlib import Path

import yaml

from pestdet.config import load_config, merge_overrides, validate_config
from pestdet.core.errors import JobCancelled
from pestdet.core.pipeline import VideoPipeline
from pestdet.infra.logging import configure_logging, get_logger
from pestdet.infra.paths import PROJECT_ROOT
from pestdet.jobs import Job, JobRunner, JobStatus, JobStore, bus, new_job_id
from pestdet.jobs.models import now_str

logger = get_logger(__name__)

PRESETS_DIR = PROJECT_ROOT / "configs" / "presets"
LOGS_DIR = PROJECT_ROOT / "logs"
VALID_MODES = ("sahi", "direct")

# 进度落库节流: 每 N 帧写一次 SQLite（逐帧写会拖慢 4K 流程；SSE 仍逐帧实时推）
_PROGRESS_PERSIST_EVERY = 25


class AnalyzeService:
    """检测任务的创建、执行、取消与查询。

    Args:
        store: 任务持久化（默认 runs/jobs.db）
        event_bus: 事件总线（默认进程级单例，多用户阶段换 Redis）
        runner: 执行器（默认单 worker 线程池）
    """

    def __init__(self, store: JobStore | None = None, event_bus=None, runner=None):
        self.store = store or JobStore()
        self.bus = event_bus or bus
        self.runner = runner or JobRunner(max_workers=1)
        self._reconcile_stale_jobs()

    def _reconcile_stale_jobs(self) -> None:
        """把上次进程退出时遗留的 queued/running 任务标记为失败。

        执行器是进程内的，进程一退线程就没了；若不清理，任务会永远停在
        running，任务列表与详情页都会误导用户。
        """
        stale = self.store.list_unfinished()
        for job in stale:
            job.status = JobStatus.FAILED
            job.error = {"code": "Interrupted",
                         "message": "服务重启导致任务中断（进程内执行器已结束），请重新提交"}
            job.finished_at = now_str()
            self.store.save(job)
        if stale:
            logger.warning("启动对账: %d 个未完成任务已标记为失败", len(stale))

    # ------------------------------------------------------------ 查询

    def get_job(self, job_id: str) -> Job | None:
        return self.store.get(job_id)

    def list_jobs(self, limit: int = 50, offset: int = 0) -> list:
        return self.store.list(limit=limit, offset=offset)

    def count_jobs(self) -> int:
        return self.store.count()

    # ------------------------------------------------------------ 创建

    def create_job(self, source: str, mode: str = "sahi", params: dict | None = None,
                   preset: str | None = None, owner: str | None = None) -> Job:
        """建任务并立即提交执行。

        Args:
            source: 服务器上视频路径
            mode: 检测模式 "sahi" | "direct"
            params: 参数覆盖（与 configs.yaml 同构的嵌套 dict，可为部分字段）
            preset: 参数预设名（configs/presets/<name>.yaml），params 在其之上覆盖
            owner: 多用户预留，本期恒 None

        Raises:
            ValueError: mode 非法
            ConfigError: 合并后的参数校验不通过（含字段级错误）
            FileNotFoundError: preset 不存在
        """
        if mode not in VALID_MODES:
            raise ValueError(f"mode 应为 {'/'.join(VALID_MODES)} 之一，实际 {mode!r}")

        source_path = Path(source)
        if not source_path.is_absolute():        # 前端传相对项目根的路径
            source_path = PROJECT_ROOT / source_path
        if not source_path.exists():
            raise FileNotFoundError(f"视频不存在: {source_path}")

        base = self._load_base_config(preset)
        override = dict(params or {})
        override["mode"] = mode          # 模式以入参为准，防止被 params 覆盖
        effective = validate_config(merge_overrides(base, override))

        job = Job(id=new_job_id(), source=str(source_path), mode=mode,
                  params=effective, owner=owner)
        self.store.save(job)
        self._publish(job.id, {"type": "status", "status": job.status.value, "at": now_str()})
        self.runner.submit(job.id, lambda cancel_event: self._execute(job.id, cancel_event))
        return job

    def cancel_job(self, job_id: str) -> bool:
        """请求取消。返回是否成功置位（任务不存在抛 FileNotFoundError）。"""
        job = self.store.get(job_id)
        if job is None:
            raise FileNotFoundError(f"任务不存在: {job_id}")
        if job.status.is_terminal:
            return False
        return self.runner.request_cancel(job_id)

    # ------------------------------------------------------------ 执行

    def _execute(self, job_id: str, cancel_event: threading.Event) -> None:
        """worker 线程内执行（由 runner 调用）。"""
        job = self.store.get(job_id)
        if job is None:                  # 被删掉的极少数情况
            return

        job.status = JobStatus.RUNNING
        job.started_at = now_str()
        self.store.save(job)
        self._publish(job_id, {"type": "status", "status": "running", "at": job.started_at})

        log_path = LOGS_DIR / f"{job_id}.log"
        configure_logging(
            level="INFO",
            log_file=log_path,
            sink=lambda line: self._publish(job_id, {"type": "log", "line": line}),
        )
        job_logger = get_logger("services.analyze")
        job_logger.info("任务开始: %s（mode=%s, source=%s）", job_id, job.mode, job.source)

        pipe = None
        try:
            pipe = VideoPipeline(job.params, mode=job.mode,
                                 logger=get_logger("core.pipeline"))
            result = pipe.run(
                job.source,
                progress_cb=lambda done, total, elapsed: self._on_progress(
                    job, done, total, elapsed),
                cancel=cancel_event.is_set,
            )
            job.status = JobStatus.SUCCEEDED
            job.out_dir = str(pipe.out_dir)
            job.summary = _summarize(result)
            job.progress = {
                "done": result["video"]["processed_frames"],
                "total": result["video"]["processed_frames"],
                "elapsed": result.get("elapsed_s", job.progress.get("elapsed", 0.0)),
            }
            job.finished_at = now_str()
            self.store.save(job)
            job_logger.info("任务成功: %s → 唯一计数 %s", job_id, job.summary.get("unique_count"))
            self._publish(job_id, {"type": "done", "status": "succeeded",
                                   "summary": job.summary})

        except JobCancelled as exc:
            job.status = JobStatus.CANCELLED
            job.progress = {**job.progress, "done": exc.processed}
            job.out_dir = str(pipe.out_dir) if pipe is not None and pipe.out_dir else None
            job.finished_at = now_str()
            self.store.save(job)
            job_logger.info("任务已取消: %s（已处理 %d 帧）", job_id, exc.processed)
            self._publish(job_id, {"type": "done", "status": "cancelled",
                                   "processed": exc.processed})

        except Exception as exc:         # 任务失败但不影响服务
            job.status = JobStatus.FAILED
            job.error = {"code": type(exc).__name__, "message": str(exc)}
            job.finished_at = now_str()
            self.store.save(job)
            job_logger.exception("任务失败: %s", job_id)
            self._publish(job_id, {"type": "done", "status": "failed", "error": job.error})

        finally:
            if pipe is not None:            # 取消/异常路径也回收 GPU 显存（正常路径已在 run 内释放）
                pipe.close()
            configure_logging(level="INFO")     # 复位为仅控制台，避免污染后续任务

    # ------------------------------------------------------------ 内部

    def _on_progress(self, job: Job, done: int, total: int, elapsed: float) -> None:
        job.progress = {"done": int(done), "total": int(total),
                        "elapsed": round(float(elapsed), 2)}
        self._publish(job.id, {"type": "progress", "done": int(done),
                               "total": int(total), "elapsed": round(float(elapsed), 2)})
        if done % _PROGRESS_PERSIST_EVERY == 0 or (total and done == total):
            self.store.save(job)

    def _publish(self, job_id: str, event: dict) -> None:
        self.bus.publish(job_id, event)

    @staticmethod
    def _load_base_config(preset: str | None) -> dict:
        """读基础配置。

        默认取 ``configs.yaml``；给了 preset 则把 ``configs/presets/<name>.yaml``
        当作**增量覆盖**叠加上去（预设只需写要改的字段，无需整份复制）。
        这里不做校验，由 ``create_job`` 在合并入参覆盖后统一 validate。
        """
        base = load_config()
        if not preset:
            return base
        path = PRESETS_DIR / f"{preset}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"参数预设不存在: {preset}（{path}）")
        overlay = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return merge_overrides(base, overlay)


def _summarize(result: dict) -> dict:
    """从完整 result 中抽出列表页/详情页要展示的摘要字段。"""
    counting = result.get("counting", {})
    video = result.get("video", {})
    snapshots = result.get("snapshots", {})
    outputs = result.get("outputs", {})
    return {
        "unique_count": counting.get("unique_count"),
        "raw_detections": counting.get("raw_detections"),
        "processed_frames": video.get("processed_frames"),
        "elapsed_s": result.get("elapsed_s"),
        "snapshot_count": snapshots.get("count", 0),
        "has_video": bool(outputs.get("video")),
        "has_json": bool(outputs.get("json")),
    }