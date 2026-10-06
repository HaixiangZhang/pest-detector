# 部署到 GPU 服务器

面向"把 pest_detector 跑在带 GPU 的服务器上、多人在浏览器里用"的部署说明。
当前为 **MVP 形态**: 单进程 Uvicorn + 单 worker 串行推理 + SQLite，够用且好维护。

---

## 1. 前置条件

| 项 | 要求 |
| --- | --- |
| 操作系统 | Linux（推荐）或 Windows |
| Python | ≥ 3.10 |
| GPU | NVIDIA + 驱动；CUDA 12.8（适配 RTX 50 系） |
| 磁盘 | 4K 视频与产物较大，`videos/` 与 `runs/` 建议挂独立盘 |
| ffmpeg | 可选但强烈建议（把 mp4v 转 H.264，浏览器播放/拖动才流畅） |

---

## 2. 安装

```bash
git clone <repo> pest_detector && cd pest_detector

# CUDA 版 PyTorch（先装，避免 pip 拉 CPU 轮子）
pip install torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 \
    --index-url https://download.pytorch.org/whl/cu128

# 项目本体 + Web 依赖
pip install -e ".[web]"

# 前端构建（需要 Node.js ≥ 18）
cd web && npm install && npm run build && cd ..
```

构建后 `web/dist` 存在，FastAPI 会自动把它挂到根路径，浏览器访问
`http://<host>:8000/` 即是完整应用（API 与前端同源，无跨域问题）。

> 若不做前端构建，后端 API 仍可用（`/docs` 有 Swagger），只是没有网页界面。

---

## 3. 配置

### 3.1 工作根（重要）

`configs.yaml` / `videos/` / `runs/` / `logs/` / `data/` 默认相对**仓库根**解析。
若数据放在别处（推荐），设置环境变量：

```bash
export PESTDET_HOME=/data/pest_detector
# 目录结构: $PESTDET_HOME/{configs.yaml, videos/, runs/, logs/, data/uploads/}
```

其中 `data/uploads/` 是**用户上传的源视频**（用户资产，跨会话保留）；
`runs/` 是**任务产物**（按次生成，可归档清理）。二者分开，便于分别挂盘与备份。

### 3.2 模型权重

把部署权重登记进版本链，或直接指定路径：

```bash
python cli.py weights --save best.pt --tag deploy
python cli.py weights --list
```

`configs.yaml` 里 `model_path` 留空即取最新登记权重。

### 3.3 参数预设

`configs/presets/*.yaml` 是**增量覆盖**：只写要改的字段，未写的沿用 `configs.yaml`。
新建任务页的下拉即读这里（`GET /api/meta/presets` 会连覆盖字段一起返回，
选中后在表单里直接展示"这个预设改了什么"）；也可在请求里用 `params` 覆盖任意字段。

**内置两个预设**：

| 预设 | 覆盖字段 | 含义 |
| --- | --- | --- |
| `fast`（快检） | `frame_stride: 3`、`snapshots.enabled: false`、`sahi.batch: 8` | 抽帧到 1/3（约 3 倍速）、不写快照，只要计数 |
| `accurate`（高精度） | `frame_stride: 1`、`sahi.multi_scale: true`、`sahi.conf: 0.55`、`sahi.batch: 4`、`tracker.confirm_enabled: true`、`confirm_window: 10`、`confirm_min_hits: 8` | 逐帧 + 多尺度切片 + 放宽阈值提召回；稳定确认门控压闪光误检（8GB 显存下 batch 调小防 OOM） |

**改 / 加预设**：直接编辑 `configs/presets/<name>.yaml`，或新增一个 `<name>.yaml`
——接口按目录扫描，前端下拉与 `POST /api/jobs` 的 `preset` 字段自动识别，无需改代码。

---

## 4. 启动

### 4.1 一键脚本（推荐）

脚本会自动探测"装有项目依赖"的解释器、做一遍环境自检、必要时构建前端，然后启动服务
（无需手动 `conda activate`）。

**Linux / macOS**（首次使用需 `chmod +x scripts/*.sh`）：

```bash
./scripts/start.sh                                   # 自检 + 启动；Ctrl+C 停止
./scripts/start.sh --host 0.0.0.0 --port 8000        # 对外提供服务
./scripts/start.sh --build                           # 首次 / 前端有改动：先构建前端
./scripts/start.sh --install                         # 依赖缺失时自动装 Web 依赖
./scripts/check.sh                                   # 只自检不启动（退出码 0 通过 / 1 有错误）
```

**Windows**：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -BindHost 0.0.0.0 -Port 8000 -Build
```

两个平台的自检项一致：解释器/依赖、`configs.yaml`、模型权重、前端产物、Node/npm、
ffmpeg、端口占用、数据目录可写性。`[WARN]` 不影响启动，`[FAIL]` 会终止并给出解决办法。

### 4.2 手动启动

```bash
# 直接启动
python -m pestdet.server --host 0.0.0.0 --port 8000

# 或安装后的入口
pestdet-server --host 0.0.0.0 --port 8000
```

### 4.3 常驻服务（systemd）

```bash
sudo ./scripts/install-service.sh --host 0.0.0.0 --port 8000
# 独立数据盘 + 非 root 运行:
sudo ./scripts/install-service.sh --home /data/pest_detector --user pest --group pest
# 显式指定解释器:
sudo ./scripts/install-service.sh --python /opt/conda/envs/yolo11/bin/python
```

安装脚本会：探测解释器 → 创建 `data/uploads`、`runs`、`logs` → 生成
`/etc/systemd/system/pestdet.service` → `daemon-reload` + `enable --now`。
卸载用 `sudo ./scripts/uninstall-service.sh`（只删单元，不动数据目录）。
手工配置参考模板 [`deploy/systemd/pestdet.service`](../deploy/systemd/pestdet.service)。

> **`PESTDET_HOME` 与前端产物**：代码从 `$PESTDET_HOME/web/dist` 挂载前端
> （见 `api/app.py`）。用 `--home` 指向独立数据盘时，安装脚本会自动把该目录下的
> `web/dist` 软链到仓库的 `web/dist`；同时需保证 `$PESTDET_HOME/configs.yaml` 存在
> （脚本会提示 `cp`）。若嫌麻烦，直接把 `PESTDET_HOME` 设为仓库根即可。

**务必单 worker**：任务执行器是进程内的（线程池 + 内存事件总线 + 单 SQLite）。
用 `--workers > 1` 会导致任务库与事件总线各自为政，进度/取消行为错乱。
多 worker 属于下一阶段（见第 7 节）。

---

## 5. 反向代理（可选）

Nginx 示例：静态与 API 同源，重点是 **SSE 不能缓冲**。

```nginx
server {
    listen 80;
    server_name pest.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # SSE（/api/jobs/*/events）必须关闭缓冲，否则进度不实时
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    client_max_body_size 4g;   # 浏览器上传源视频（data/uploads/）；与 PESTDET_MAX_UPLOAD_MB 保持一致
}
```

---

## 6. 运维要点

| 事项 | 说明 |
| --- | --- |
| 数据落点 | 任务库 `runs/jobs.db`；日志 `logs/<job_id>.log`；产物 `runs/<视频名>_<时间戳>/`；用户上传 `data/uploads/` |
| 显存 | 单任务串行，避免并发争显存 OOM；前端表单已标注 batch / imgsz 为"显存敏感" |
| 取消 | 运行中任务可取消，状态落 `cancelled`；已产出的中间产物保留 |
| 清理 | `runs/` 与 `logs/` 会持续增长，建议定期归档旧目录 |
| 日志 | 服务日志走 stdout（交给 systemd/journald 收集）；任务日志按 job 分文件 |

systemd 服务推荐用安装脚本生成（见 [4.3](#43-常驻服务systemd)）：

```bash
sudo ./scripts/install-service.sh --host 0.0.0.0 --port 8000
```

需手工配置时，参考模板 [`deploy/systemd/pestdet.service`](../deploy/systemd/pestdet.service)
（含 `PESTDET_HOME` / `PYTHONPATH` / 重启策略等字段说明）。

---

## 7. 从 MVP 走向多用户（演进点）

本期架构**已按多用户预留接口**，升级时替换三处即可，不需重写：

| 替换点 | 现状 | 升级方向 |
| --- | --- | --- |
| `jobs/runner.py` | 进程内 `ThreadPoolExecutor(1)` | RQ / Celery / arq + Redis：队列、并发上限、配额 |
| `jobs/events.py` | 内存 pub/sub | Redis Pub/Sub：跨进程 / 多 worker 事件 |
| `Job.owner` | 恒为 `None` | 落地鉴权（JWT/OAuth），列表按 owner 过滤 |

另外建议：推理进程独立于 API 进程（GPU 只允许一个持有者），API 侧水平扩展。

---

## 8. 浏览器上传与云端推理（架构方案）

### 8.1 现状（已实现）

- 前端 `Upload.Dragger` 拖拽/选择本地视频 → `POST /api/uploads?name=<文件名>`
  以**原始请求体流式直传**（非 multipart，无需 `python-multipart`，内存占用与文件大小无关）。
- 服务端边收边写 `data/uploads/`，按内容 sha256 去重命名；大小上限
  `PESTDET_MAX_UPLOAD_MB`（默认 4096MB）。
- 上传项可直接作为 `POST /api/jobs` 的 `source`（如 `data/uploads/xxx.mp4`），
  完成"上传 → 建任务"闭环；上传历史随页面刷新保留（读 `GET /api/uploads`）。

### 8.2 传到"云端 GPU 服务器"的三条路线

| 路线 | 做法 | 适用 |
| --- | --- | --- |
| A. 单机同源（当前） | 前端与推理同进程同机，浏览器直传本机 `data/uploads/` | 单机、内网、个人 / 小团队 |
| B. 前端 + 远端 GPU（推荐起步） | 前端与 API 部署在普通机器；上传后由 API 用 `rsync`/HTTP 推给 GPU 机，或直接由 GPU 机的 API 接收上传 | 前后端分离、GPU 机在内网 |
| C. 对象存储中转（规模化） | 前端直传 S3/OSS（预签名 URL），GPU worker 从对象存储拉取、跑完把产物写回，DB 记 key | 多机、弹性伸缩、大文件 |

**路线 B 落地要点**：
1. 上传落到"入口机"的 `data/uploads/`；
2. 建任务时若 `source` 不在本机，由 `services/analyze` 先 `_ensure_local(source)`
   （本地有则跳过，否则从远端/对象存储拉到本地临时目录）；
3. 推理在 GPU 机执行，产物写 `runs/`，`out_dir` 落库；
4. 前端读产物仍走 `/api/jobs/{id}/video`（入口机反代 GPU 机产物目录，或产物回传）。

**路线 C 落地要点**：
1. 后端加 `POST /api/uploads/presign` 返回对象存储预签名 URL；
2. 前端 `PUT` 直传对象存储（绕过 API，省带宽）；
3. 上传完成回调 `POST /api/uploads/commit {key}`，API 校验后建任务；
4. `jobs/runner.py` 换成 RQ / Celery，worker 从对象存储下载 → 推理 → 回传产物；
5. `jobs/store.py` 由 SQLite 换 Postgres（多机共享状态）。

### 8.3 断点续传与秒传（大文件优化，可选）

- **秒传**：上传前先算文件 sha256 前 8 位，命中则直接复用（当前已按内容去重，补一个查询接口即可）。
- **断点续传**：分片 `PUT /api/uploads/{id}/chunk?index=N`，服务端按 index 落盘再合并；前端用 `File.slice()` 切片。

### 8.4 安全与配额（多用户时必做）

- 上传鉴权（`api/deps.py` 已预留位）+ 每用户配额；
- 文件类型按**魔数**校验（不只看扩展名）；
- 定期清理 `data/uploads/` 中无任务引用的孤儿文件。

---

## 9. 故障排查

| 现象 | 排查 |
| --- | --- |
| 页面打不开 | 是否 `npm run build` 生成了 `web/dist`；服务是否在监听该端口 |
| 进度条不动 | 反代是否 `proxy_buffering off`；浏览器 Network 里 `/events` 是否持续有 `data:` |
| 播放卡顿 | ffmpeg 是否可用（未转码则保留 mp4v，无硬件解码）；`encode.h264` 是否被关 |
| 配置报错 422 | 响应体 `errors` 是逐条字段级中文提示，照着改 `configs.yaml` 或请求 `params` |
| 任务失败 | 看任务详情页日志，或 `logs/<job_id>.log`；`Job.error.message` 含原因 |