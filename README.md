# pest_detector — 4K 视频/图片<害虫>检测与计数

在 4K 无人机航拍视频中检测草地上的小目标害虫，通过跨帧关联去重，
输出"视频里一共有多少只虫"的唯一计数，并产出标注视频、检出帧快照与结构化数据。

两种用法：

- **Web 应用**（推荐）：浏览器选视频 → 提交任务 → 看实时进度 → 看结果（计数/视频/快照/曲线）
- **命令行**：`python cli.py sahi|direct|roi|weights ...`，适合脚本化与调试

---

## 快速开始

```powershell
# 1. 安装依赖
#    CUDA 版 PyTorch 需先从专用源装（适配 RTX 50 系 / CUDA 12.8），否则 pip 会拉 CPU 轮子
pip install torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[web,dev]"        # 只要命令行可省去 [web]

# 2. 启动（首次加 -Build 先构建前端）
#    脚本会自动找到装有依赖的解释器，无需手动 conda activate；也可直接双击 scripts\start.bat
.\scripts\start.ps1 -Build

# 3. 浏览器打开 http://127.0.0.1:8000/   （API 文档: /docs）
```

> 未 `pip install -e .` 时，仓库根的 `cli.py` 会自动把 `src/` 加入 `sys.path`，
> `python cli.py ...` 依然可用；Web 侧请设 `PYTHONPATH=src` 或直接安装。

### 命令行直接跑

```powershell
python cli.py sahi --source videos/test0.mp4      # 切片检测（精度优先）
python cli.py direct --source videos/test0.mp4    # 整帧直推（速度优先）
```

产物默认写到 `runs/<视频名>_<时间戳>/`：

| 文件 | 内容 |
| --- | --- |
| `tracked.mp4` | 推理后视频（检测框 + track ID + 轨迹尾迹 + 计数面板；默认转 H.264，见下） |
| `frames/` | 检出帧快照（粒度见 `snapshots.mode`：`track`=每只虫一张代表图，取该虫置信度最高的帧；`frame`=每个有虫帧一张） |
| `result.json` | 结构化数据（`counting.unique_count` 即最终计数） |

---

## 启动 Web 应用

Web 端 = **后端**（FastAPI + Uvicorn）+ **前端**（Vite 构建产物 `web/dist`，由后端同源挂载）。
前端**只需构建一次**，之后启动后端即可访问完整界面。

### 方式一：一键脚本（推荐）

脚本会先做一次环境自检，通过后自动启动服务，**不需要手动 `conda activate`**。

**Linux / macOS**（首次使用需 `chmod +x scripts/*.sh`）：

```bash
./scripts/start.sh                                 # 自检 + 启动；Ctrl+C 停止
./scripts/check.sh                                 # 只自检不启动（退出码 0 通过 / 1 有错误）
./scripts/start.sh --build                         # 首次 / 前端有改动：先构建前端再启动
./scripts/start.sh --reload                        # 开发热重载（改后端代码自动重启）
./scripts/start.sh --host 0.0.0.0 --port 8000      # 对外提供服务（服务器 / 局域网）
./scripts/start.sh --install                       # 依赖缺失时，自动装 Web 依赖
```

Linux 服务器常驻（systemd）：`sudo ./scripts/install-service.sh --host 0.0.0.0 --port 8000`
会生成单元文件并 `enable --now`；卸载用 `sudo ./scripts/uninstall-service.sh`。
细节见 [docs/DEPLOY.md](docs/DEPLOY.md)。

**Windows**：在资源管理器里**双击 `scripts\start.bat`**，或在任意终端执行 `.\scripts\start.ps1`。

```powershell
.\scripts\start.ps1                                # 自检 + 启动；Ctrl+C 停止
.\scripts\start.ps1 -Open                          # 启动后自动打开浏览器
.\scripts\check.ps1                                # 只自检不启动（退出码 0 通过 / 1 有错误）
.\scripts\start.ps1 -Build                         # 首次 / 前端有改动：先构建前端再启动
.\scripts\start.ps1 -Reload                        # 开发热重载（改后端代码自动重启）
.\scripts\start.ps1 -BindHost 0.0.0.0 -Port 8000   # 对外提供服务（服务器 / 局域网）
.\scripts\start.ps1 -Install                       # 依赖缺失时，自动装进当前 conda 环境
```

`scripts\start.bat` 是双击入口，等价于 `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`，
并支持透传参数（如 `start.bat -Build -Open`）。

#### 启动前的自动自检

每次启动都会先跑一遍检查（也可单独执行 `.\scripts\check.ps1`），逐项给出 `[OK] / [WARN] / [FAIL]`：

| 检查项 | `FAIL` / `WARN` 的后果 |
| --- | --- |
| Python 解释器 + 依赖 | `FAIL` 终止启动（找不到含 `torch`/`ultralytics`/`fastapi`/`uvicorn` 的解释器） |
| `configs.yaml` | `FAIL` 终止启动（文件缺失） |
| 模型权重 | `FAIL` 终止（`model_path` 指向的文件不存在）；`WARN`（`model_path` 为空且无登记权重） |
| 前端产物 `web/dist` | `WARN`，启动时会尝试自动构建 |
| Node / npm | `WARN`（无 npm 时无法构建前端；已有 `web/dist` 不影响启动） |
| ffmpeg | `WARN`（输出视频保留 mp4v，4K 拖动可能卡） |
| 端口占用 | `FAIL` 终止启动，提示换 `-Port` |
| 数据目录可写 | `FAIL` 终止（`data/uploads`、`runs` 不可写） |

> `WARN` 不影响启动；`FAIL` 会打印解决办法并退出。

#### 解释器是怎么找到的

探测顺序：`-Python` > `$env:PESTDET_PYTHON` > **缓存** > 当前 conda 环境 > PATH 的 `python` >
自动发现的其它 conda 环境（由 `conda` / `python` 所在安装根推出 `envs\*`，并扫描常见安装位置）> `.venv`。

首次成功启动后，选中的解释器路径会写入项目根 `.pestdet-python`（已 gitignore）。之后**即使不激活 conda、
甚至直接双击**（PATH 里没有 conda），也能凭缓存直接找到 yolo11。换了环境后删掉该文件即可重新探测。

> 因此 `powershell -ExecutionPolicy Bypass -File scripts\start.ps1` 也能用：即便子 PowerShell 把环境
> 切成 base，脚本也会自己找到 yolo11。若提示"禁止运行脚本"，执行一次：
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

<details>
<summary>背景：以前为什么会报 <code>No module named 'uvicorn'</code></summary>

1. `powershell -File` 会新开子 PowerShell，其 profile 按 `auto_activate_base` 激活 **base**，顶掉了父 shell 的 `yolo11`。
2. `pip install -e ".[web]"` 若发现依赖已在**用户级 site-packages**（`%APPDATA%\Python\Python3xx`）里，
   会判定"已满足"而**跳过装进环境本身** → 换环境或禁用 user site 后又找不到。

以上现在都由脚本自动处理（自动探测环境 / `-Install` 装依赖）。
</details>

### 方式二：手动命令

```powershell
# 1) 装后端依赖（含 Web）
pip install -e ".[web]"

# 2) 构建前端（首次，或前端代码有改动时）
cd web
npm install
npm run build          # 产出 web/dist
cd ..

# 3) 启动服务（单 worker！推理在进程内串行执行）
python -m pestdet.server --host 127.0.0.1 --port 8000
#   或（pip install -e . 之后）
pestdet-server --host 127.0.0.1 --port 8000
```

浏览器打开 **http://127.0.0.1:8000/** ； 接口文档 **http://127.0.0.1:8000/docs** 。

> 未 `pip install -e .` 时，给启动命令加 `PYTHONPATH`：
> `$env:PYTHONPATH="src"; python -m pestdet.server --host 127.0.0.1 --port 8000`

### 方式三：前端开发模式（改前端热更新）

前后端分开跑，`/api` 由 Vite 代理到 8000，改前端即时生效、无需重新构建：

```powershell
# 终端 A：只起后端 API
python -m pestdet.server --host 127.0.0.1 --port 8000

# 终端 B：Vite 开发服务器
cd web
npm install
npm run dev            # http://localhost:5173
```

### 启动前后检查

| 项 | 说明 |
| --- | --- |
| 前端未构建 | `web/dist` 不存在时服务仍能起，但根路径没有界面，只能用 `/docs` 调 API |
| Python 环境 | 必须用装有项目依赖的解释器（先 `conda activate yolo11`，或用 `-Python` 指定），否则报 `No module named 'uvicorn'` |
| 端口被占用 | 换 `--port`；或查占用进程 `Get-NetTCPConnection -LocalPort 8000 -State Listen` |
| 必须单 worker | 任务执行器是进程内的（线程池 + 内存事件总线 + SQLite），多 worker 会导致进度/取消错乱 |
| 服务重启 | 上次遗留的 `queued/running` 任务会在启动时自动标记为失败，不会永远卡在"运行中" |
| 深链刷新 | `/jobs`、`/jobs/<id>` 支持直接访问与刷新（后端已做 SPA 回退到 `index.html`） |
| 数据落点 | 用户上传 `data/uploads/`、任务库 `runs/jobs.db`、产物 `runs/`、日志 `logs/` |

#### 排障：`No module named 'uvicorn'`

含义是"你正在用的解释器里没有 Web 依赖"。两种常见成因：**用错了环境**（如被自动激活的 base
顶掉了 yolo11），或**依赖只装在用户级 site-packages**（`%APPDATA%\Python\Python3xx`）而没进环境本身。

注意：直接 `pip install -e ".[web]"` 往往**无效**——pip 在 user site 里看到依赖会判定"已满足"而跳过。
要装进环境本身，安装时临时禁用 user site：

```powershell
conda activate yolo11
$env:PYTHONNOUSERSITE = "1"            # 关键：否则 pip 会因"已满足"而跳过
python -m pip install -e ".[web]"
Remove-Item Env:PYTHONNOUSERSITE
python -c "import uvicorn; print(uvicorn.__file__)"   # 期望 ...\envs\yolo11\Lib\site-packages\...
```

启动脚本会打印它实际使用的解释器路径，可据此判断是否选对了环境。

---

## Web 应用

### 页面

| 页面 | 能力 |
| --- | --- |
| 新建任务 | **拖拽/选择本地视频上传**（存 `data/uploads/`，刷新不丢、可复用/删除）或选 `videos/` 里的视频；切 sahi/direct、调参数（含预设，选中即展示覆盖了哪些字段）、提交 |
| 任务详情 | SSE 实时进度条 + 实时日志尾随 + 取消按钮；完成后展示结果 |
| 结果可视化 | 唯一计数卡片、`tracked.mp4` 播放器（可拖动）、快照网格（可放大）、逐帧虫数曲线、轨迹与参数 JSON |
| 任务列表 | 状态标签、时间、计数，点击进详情 |

### API（MVP）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/meta/videos` | 列出 `videos/` 可用视频（名称/路径/大小/时长） |
| `GET` | `/api/meta/weights` | 已登记权重（pest{N}/标签/mAP/路径） |
| `GET` | `/api/meta/config-schema` | 参数 JSON Schema + 默认值（前端表单用） |
| `GET` | `/api/meta/presets` | 参数预设列表（含每个预设覆盖的字段） |
| `POST` | `/api/uploads?name=<文件名>` | 上传源视频（原始请求体流式直传，按内容去重） |
| `GET` | `/api/uploads` | 已上传视频列表（刷新/重开网页后仍在的"历史"） |
| `GET` | `/api/uploads/{name}/video` | 上传视频预览（支持 HTTP Range） |
| `GET` | `/api/uploads/{name}/download` | 下载原始上传文件 |
| `DELETE` | `/api/uploads/{name}` | 删除上传文件 |
| `POST` | `/api/jobs` | 创建并启动任务，body `{source, mode, params, preset?}` |
| `GET` | `/api/jobs` | 任务列表（分页，创建时间倒序） |
| `GET` | `/api/jobs/{id}` | 状态 + 进度快照 + 结果摘要 |
| `GET` | `/api/jobs/{id}/events` | **SSE**：进度事件 + 日志行，直到终态 |
| `POST` | `/api/jobs/{id}/cancel` | 请求取消 |
| `GET` | `/api/jobs/{id}/result` | `result.json` |
| `GET` | `/api/jobs/{id}/video` | 标注视频（支持 HTTP Range，可拖动） |
| `GET` | `/api/jobs/{id}/frames` | 检出帧快照列表 |
| `GET` | `/api/jobs/{id}/frames/{name}` | 单张快照 |
| `GET` | `/api/jobs/{id}/logs` | 完整日志文本 |

任务状态机：`queued → running → succeeded | failed | cancelled`。

```powershell
# 用 curl 跑一次（示例）
curl -X POST http://127.0.0.1:8000/api/jobs -H "Content-Type: application/json" `
  -d '{"source":"videos/test0.mp4","mode":"sahi","params":{"max_frames":50}}'
```

> **部署到 GPU 服务器**（反代 / systemd / 多用户演进点 / 排障）见
> [docs/DEPLOY.md](docs/DEPLOY.md)。

---

## 命令行入口

所有功能收敛到根目录 `cli.py`（薄转发层），实际实现位于 `src/pestdet/cli/main.py`，
用子命令区分：

| 子命令 | 作用 | 底层实现 |
| --- | --- | --- |
| `sahi` | 切片检测 → 跨帧去重计数 → 视频/JSON | `pestdet.core.pipeline.VideoPipeline` |
| `direct` | 整帧直推 → 跨帧去重计数 → 视频/JSON | `pestdet.core.pipeline.VideoPipeline` |
| `roi` | 草地 ROI 遮罩调参预览 | `pestdet.core.roi` |
| `weights` | 权重登记管理（pest{N} 版本链） | `pestdet.infra.registry` |

检测模式直接作为子命令，两者共用同一套视频流程（遮罩 → 检测 → 跨帧去重计数 → 产物），
不再有 `detect` 中间层；差异只在检测器本身（切片 / 整帧）。

安装后也可用等价的 `pestdet` 命令（`[project.scripts]` 注册）：

```powershell
python cli.py --help              # 列出全部子命令
python cli.py sahi --help         # 查看某子命令的参数
pestdet sahi --source videos/test0.mp4   # 与 python cli.py sahi 等价（需 pip install -e .）
```

---

## 目录结构

```
pest_detector/
├── cli.py                # 统一命令行入口（薄转发 → pestdet.cli.main:main）
├── pyproject.toml        # 包元数据 / 依赖 / ruff / black / pytest 配置
├── configs.yaml          # 部署参数（默认模板，唯一默认值来源）
├── configs/presets/      # 参数预设（fast / accurate，增量覆盖）
├── best.pt               # 部署权重（YOLO11x-P2 单类别模型，Git LFS 管理）
├── README.md
├── .gitattributes        # Git LFS 规则（*.pt 等大文件）
│
├── docs/
│   ├── PLAN_web_mvp.md   # Web 化 MVP 规划
│   ├── DEPLOY.md         # GPU 服务器部署说明
│   ├── todo.md           # 分阶段执行清单
│   └── yolo11x_p2.yaml   #   归档: YOLO11x-P2 训练用模型结构定义（部署链路不引用）
│
├── scripts/              # 启动与运维脚本（Windows PowerShell + Linux Shell）
│   ├── start.ps1         #   Windows 一键启动（可选先构建前端）
│   ├── check.ps1         #   Windows 仅自检
│   ├── start.bat         #   Windows 双击入口
│   ├── start.sh          #   Linux / macOS 一键启动（自检 + 构建 + 启动）
│   ├── check.sh          #   Linux / macOS 仅自检
│   └── install-service.sh / uninstall-service.sh   # systemd 服务安装 / 卸载
│
├── deploy/systemd/       # systemd 单元模板（pestdet.service，手工配置参考）
│
├── src/pestdet/          # 应用主包（src 布局，依赖单向）
│   ├── config/           #   配置模型与加载
│   │   ├── schema.py     #     Pydantic 模型（字段级校验）
│   │   ├── loader.py     #     load_config / merge_overrides / to_json_schema
│   │   └── errors.py     #     ConfigError + 校验错误中文逐条化
│   ├── core/             #   领域逻辑（无 I/O 副作用、无全局配置、不 print）
│   │   ├── detector.py   #     build_detector / detect_batch（sahi / direct）
│   │   ├── pipeline.py   #     VideoPipeline（注入 logger/progress/cancel）
│   │   ├── tracker.py    #     跨帧 IoU 关联 + 轨迹后处理三步清洗
│   │   ├── roi.py        #     草地四边形 ROI 遮罩
│   │   ├── sahi.py       #     SAHI 切片推理 + WBF/NMS 融合
│   │   ├── render.py     #     第二遍重绘 + 视频写出 + ffmpeg 转 H.264
│   │   ├── snapshots.py  #     检出帧快照
│   │   └── errors.py     #     JobCancelled / PestDetectorError
│   ├── jobs/             #   任务模型与执行（多用户演进点）
│   │   ├── models.py     #     Job + 状态枚举
│   │   ├── store.py      #     SQLite 持久化（runs/jobs.db）
│   │   ├── events.py     #     进度/日志事件总线（进程内 pub/sub）
│   │   └── runner.py     #     单 worker 执行器 + 取消
│   ├── services/         #   编排层
│   │   └── analyze.py    #     AnalyzeService: 配置 + core + 任务 + 落盘
│   ├── api/              #   FastAPI
│   │   ├── app.py        #     装配（lifespan / CORS / 静态站点 / 异常处理）
│   │   ├── routes_jobs.py#     任务路由（含 SSE 与 Range 视频）
│   │   ├── routes_meta.py#     videos / weights / schema / presets
│   │   ├── deps.py       #     依赖注入（服务单例、分页）
│   │   └── errors.py     #     领域异常 → HTTP 状态码
│   ├── infra/            #   基础设施
│   │   ├── paths.py      #     路径常量（支持 PESTDET_HOME）
│   │   ├── imageio.py    #     图片读取（兼容非 ASCII 路径）
│   │   ├── registry.py   #     权重登记（pest{N} 版本链）
│   │   └── logging.py    #     日志装配（控制台 + 按 job 文件 + 事件总线）
│   ├── cli/main.py       #     子命令实现（sahi / direct / roi / weights）
│   └── server.py         #     Uvicorn 启动入口
│
├── web/                  # 前端（Vite + React + TS + Ant Design）
│   └── src/
│       ├── api/          #   client.ts（REST + SSE 封装）/ types.ts
│       ├── pages/        #   NewJob / Jobs / JobDetail
│       └── components/   #   ProgressPanel / LogViewer / ResultView / SnapshotGrid / PerFrameChart
│
├── tests/                # pytest（conftest / config / tracker_golden / pipeline_smoke / api）
├── videos/               # 待检测视频统一存放
├── runs/                 # 运行产物（含 jobs.db 与每次运行的独立目录）
└── logs/                 # 按任务隔离的运行日志（logs/<job_id>.log）
```

分层依赖规则（**必须遵守**，否则多用户阶段会返工）：

```
api / cli  →  services  →  jobs  →  core
                 ↓          ↓
              config      infra
```

- `core` 不得 import `api/services/jobs`，不得读全局配置单例、不 `print`、不 `sys.exit`
- 每个任务持有**独立的配置实例**（多用户并发的硬前提）

---

## 配置

所有部署参数集中在项目根的 **`configs.yaml`**，改参数只改该文件，无需动代码。
优先级链：**CLI 显式参数 / 请求 params > 预设 > `configs.yaml`**。

配置由 `pestdet.config`（Pydantic 模型）在**显式调用 `load_config()` 时**校验，
**不在 import 期读盘**，失败抛 `ConfigError`（而非 `SystemExit`）——
CLI 会打印后退出，API 会转成 **422 + 字段级错误列表**：

```
[错误] 部署配置校验失败: configs.yaml
  - mode: 取值应为 sahi/direct 之一
  - sahi.conf: 应 ≤ 1.0
  - sahi.slice_sise: 未知字段（可用字段: slice_size, overlap_ratio, ...）
```

缺字段、类型写错、取值越界、字段名拼错都会逐条报错。`mask` / `tracker` /
`snapshots` / `encode` 四节必须写全（默认值只存在于 `configs.yaml` 一处）。

### 参数预设（`configs/presets/*.yaml`）

预设是**增量覆盖**：只写要改的字段，其余沿用 `configs.yaml`。

| 预设 | 用途 |
| --- | --- |
| `fast` | 抽帧 1/3、关视频与快照 —— 快速出计数 |
| `accurate` | 逐帧 + 多尺度切片 + 稳定确认门控 —— 慢但召回高 |

```powershell
python cli.py sahi --source videos/test0.mp4   # CLI 侧直接改 configs.yaml 即可
curl -X POST http://127.0.0.1:8000/api/jobs -H "Content-Type: application/json" `
  -d '{"source":"videos/test0.mp4","mode":"sahi","preset":"fast"}'
```

### 输出视频编码（`encode`）

本机 OpenCV 只能写出 **mp4v**（MPEG-4 Part 2），它**没有硬件解码**，4K60 播放时软解
跟不上会卡顿；所以视频写完后再用系统 **ffmpeg** 就地转成 **H.264**（可硬件解码，播放
流畅、体积更小）。`encode` 节控制这一行为：

| 字段 | 含义 | 取值 |
| --- | --- | --- |
| `h264` | 是否转码成 H.264 | `true`（默认，转） / `false`（保留 mp4v） |
| `ffmpeg` | ffmpeg 可执行文件路径 | 留空 = 自动探测；也可填完整路径 |
| `crf` | H.264 质量，越小越清晰也越大 | `0`–`51`（默认 `23`，接近视觉无损） |
| `preset` | x264 预设，越慢压得越小 | `ultrafast`–`veryslow`（默认 `veryfast`） |

**ffmpeg 定位顺序**：`encode.ffmpeg` 显式路径 → 系统 `PATH` → 常见安装位置
（`C:\ffmpeg\bin` 等）→ TRAE 自带（`<TRAE 安装目录>\resources\app\bin`）。
最后一项是因为 TRAE 的 ffmpeg **只在 IDE 自己的终端里进 PATH**，你在自己终端跑
`cli.py` 时看不到，所以代码额外探了一遍。

全都找不到、转码失败或 `h264: false` 时，**原 mp4v 文件原样保留**并打印告警（不中断流程）。
转码走临时文件 + 成功后原子替换，失败不会破坏原视频。

### 工作根（`PESTDET_HOME`）

`configs.yaml` / `runs/` / `videos/` / `logs/` 默认相对**仓库根**解析。部署到服务器时，
可设环境变量 `PESTDET_HOME` 指向数据根目录，`paths.py` 会优先使用它。

> 注意：前端产物同样从 `$PESTDET_HOME/web/dist` 挂载。若 `PESTDET_HOME` 不是仓库根，
> 需保证该目录下有 `configs.yaml` 且 `web/dist` 可见；`scripts/start.sh` 与
> `scripts/install-service.sh` 会自动把 `web/dist` 软链过去。

---

## 模型权重（Git LFS）

`best.pt` 约 124 MB，已通过 `.gitattributes` 交给 **Git LFS** 管理：

```powershell
git init            # 若尚未初始化仓库
git lfs install     # 首次启用 LFS 钩子
git add .gitattributes best.pt
```

若不想把权重入库，取消 `.gitignore` 中 `# *.pt` 的注释即可。

---

## 常用命令

```powershell
# 指定权重（登记名 pest1 / 直接路径；--weights 是 --model 的同义写法）
python cli.py sahi --source videos/test0.mp4 --model pest1

# 调试：抽帧加速、关闭草地遮罩、不存快照
python cli.py sahi --source videos/test0.mp4 --stride 2
python cli.py sahi --source videos/test0.mp4 --no-mask
python cli.py sahi --source videos/test0.mp4 --no-snapshots

# 权重登记与查询
python cli.py weights --save best.pt --tag deploy
python cli.py weights --save best.pt --tag deploy --metrics mAP50=0.87
python cli.py weights --list

# ROI 调参预览（确认绿色分割是否贴合草地）
python cli.py roi --source videos/test0.mp4 --out runs/roi_preview.png
```

---

## 开发

```powershell
pip install -e ".[web,dev]"   # 后端 + Web + 测试/工具链
pytest                         # 跑测试（全部 CPU，不加载模型）
ruff check src tests           # 静态检查
black src tests                # 格式化

# 前端启动 / 构建见「启动 Web 应用」（方式三为热更新开发模式）
```

---

## 注意

- 输出目录 **按需创建**：只有真正要写文件（视频 / JSON / 快照）时才建
  `runs/<视频名>_<时间戳>/`。因此"输出全关"或"中途报错"的运行**不会留下空目录**。
- 视频上的标注文字一律用 **ASCII**：`cv2.putText` 不支持中文，写中文会渲染成乱码；
  中文说明只出现在终端输出、`logs/` 与 `result.json` 里。
- `runs/`、`logs/`、`*.db` 为运行产物，已加入 `.gitignore`，不入库。
- 检测与绘制分两遍执行：第一遍只检测+关联，第二遍按后处理后的最终 ID 重绘，
  保证**画面中的框与 ID 和最终计数严格一致**。
- 图片读取统一走 `pestdet.infra.imageio.imread`（`np.fromfile` + `cv2.imdecode`），
  以兼容中文/非 ASCII 路径（`cv2.imread` 遇非 ASCII 路径会静默返回 `None`）。
- Web 服务**必须单 worker**：任务执行器是进程内的（线程池 + 内存事件总线 + SQLite）。