"""API 冒烟（FastAPI TestClient）。

**不触发推理**: 需要"创建成功"的用例注入一个空转 runner，避免真的去读视频/占 GPU。
覆盖: 元信息接口、请求体校验、配置错误 422、404、列表与取消。
"""

import pytest
from fastapi.testclient import TestClient

from pestdet.api.app import create_app
from pestdet.infra.paths import PROJECT_ROOT
from pestdet.jobs import EventBus, Job, JobStatus, JobStore
from pestdet.services.analyze import AnalyzeService


class _NullRunner:
    """空转执行器: 只记录提交，不真的跑任务。"""

    def __init__(self):
        self.submitted: list[str] = []

    def submit(self, job_id, target):
        self.submitted.append(job_id)

    def request_cancel(self, job_id):
        return False

    def is_running(self, job_id):
        return False

    def shutdown(self, wait=False):
        return None


@pytest.fixture
def service(tmp_path):
    return AnalyzeService(
        store=JobStore(tmp_path / "jobs.db"),
        event_bus=EventBus(),
        runner=_NullRunner(),
    )


@pytest.fixture
def client(service):
    app = create_app()
    with TestClient(app) as test_client:
        app.state.service = service      # 覆盖为隔离实例（临时库 + 空转 runner）
        yield test_client


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_meta_videos(client):
    res = client.get("/api/meta/videos")
    assert res.status_code == 200
    assert isinstance(res.json()["items"], list)


def test_meta_config_schema(client):
    res = client.get("/api/meta/config-schema")
    assert res.status_code == 200
    body = res.json()
    assert "mode" in body["schema"]["properties"]
    assert body["defaults"]["mode"] in ("sahi", "direct")


def test_meta_presets(client):
    res = client.get("/api/meta/presets")
    assert res.status_code == 200
    names = {item["name"] for item in res.json()["items"]}
    assert "default" in names                    # 只保留「默认」预设
    assert {"fast", "accurate"} & names == set()


def test_meta_docs(client):
    res = client.get("/api/meta/docs")
    assert res.status_code == 200
    names = {item["name"] for item in res.json()["items"]}
    assert "web-guide" in names
    assert client.get("/api/meta/docs/web-guide").json()["content"].strip()


def test_system_info(client):
    """系统环境探测: 至少能返回 CPU / 内存 / 权重状态（GPU 允许缺失）。"""
    res = client.get("/api/system/info")
    assert res.status_code == 200
    body = res.json()
    assert body["cpu"]["logical_cores"]
    assert "valid" in body["weights"]
    assert client.get("/api/system/weights/download").json()["status"] in (
        "idle", "running", "done", "error")


def test_create_job_rejects_bad_mode(client):
    res = client.post("/api/jobs", json={"source": "videos/x.mp4", "mode": "turbo"})
    assert res.status_code == 422        # 请求体 Literal 校验


def test_create_job_missing_video(client):
    res = client.post("/api/jobs", json={"source": "videos/__not_here__.mp4",
                                         "mode": "sahi"})
    assert res.status_code == 404


def test_create_job_bad_params_returns_field_errors(client, tmp_path):
    fake = tmp_path / "clip.mp4"
    fake.write_bytes(b"not a real video")     # 只用于通过"源存在"检查

    res = client.post("/api/jobs", json={
        "source": str(fake),
        "mode": "sahi",
        "params": {"sahi": {"conf": 1.5}},    # 越界
    })
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "config_error"
    assert any("sahi.conf" in err for err in body["errors"])


def test_create_job_ok_with_null_runner(client, service, tmp_path):
    fake = tmp_path / "clip.mp4"
    fake.write_bytes(b"not a real video")

    res = client.post("/api/jobs", json={"source": str(fake), "mode": "direct"})
    assert res.status_code == 201
    job_id = res.json()["job_id"]
    assert service.runner.submitted == [job_id]

    listed = client.get("/api/jobs").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == job_id


def test_get_job_not_found(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_cancel_unknown_job(client):
    assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_cancel_finished_job_is_noop(client, service, tmp_path):
    fake = tmp_path / "clip.mp4"
    fake.write_bytes(b"not a real video")
    job_id = client.post("/api/jobs", json={"source": str(fake),
                                            "mode": "direct"}).json()["job_id"]

    res = client.post(f"/api/jobs/{job_id}/cancel")
    assert res.status_code == 200
    assert res.json()["cancelled"] is False     # 空转 runner 不接受取消


def test_stale_jobs_reconciled_on_startup(tmp_path):
    """进程重启后，遗留的 queued/running 任务应在服务初始化时对账为 failed。"""
    store = JobStore(tmp_path / "jobs.db")
    for jid, status in (("stale-running", JobStatus.RUNNING),
                        ("stale-queued", JobStatus.QUEUED),
                        ("finished", JobStatus.SUCCEEDED)):
        store.save(Job(id=jid, source="videos/x.mp4", mode="sahi",
                       params={}, status=status))

    AnalyzeService(store=store, event_bus=EventBus(), runner=_NullRunner())

    assert store.get("stale-running").status == JobStatus.FAILED
    assert store.get("stale-queued").status == JobStatus.FAILED
    assert store.get("stale-running").error["code"] == "Interrupted"
    assert store.get("finished").status == JobStatus.SUCCEEDED   # 终态不动


def test_spa_deeplink_falls_back_to_index(client):
    """/jobs 这类前端深链应回 index.html（而非 404）；/api 未知路径仍 404。"""
    if not (PROJECT_ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("前端未构建，跳过 SPA 回退用例")

    res = client.get("/jobs/some-id")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]

    assert client.get("/api/__nope__").status_code == 404