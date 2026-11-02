# pest_detector Web 化 MVP 实施计划

> 目标：把当前"CLI + configs.yaml"的科研脚本，改造成**可在 GPU 服务器上部署、浏览器操作、单任务跑通 + 结果可视化**的规范 Web 应用。
>
> 本文档为 MVP 阶段的实施计划，不含后续多用户完整版（队列/权限/审计/报告导出/离线打包）的实现细节，但**架构选型按多用户目标做，只把实现推迟**。

---

## 0. 已锁定的决策

| 决策项 | 选择 | 含义 |
| --- | --- | --- |
| GUI 形态 | 本地 Web 应用 | FastAPI 后端 + 浏览器前端；后续可用 Tauri/pywebview 包壳成桌面 exe |
| 使用场景 | 部署到 GPU 服务器，多用户 | 架构必须无全局可变状态、无进程级退出、支持并发接入 |
| 本期范围 | MVP：单任务跑通 + 结果可视化 | 不做登录/权限/队列调度/报告导出/离线打包 |

**本期核心矛盾与处理原则**：目标场景是多用户服务器，但本期只做 MVP。因此——
**架构按多用户设计（无全局状态、任务可取消、进度可多客户端订阅、日志按任务隔离），实现只做单任务串行**。凡属"多用户专属"的能力（鉴权、调度、配额），本期只留接口，不写实现。

---

## 1. MVP 范围定义

### 1.1 本期必须交付（验收即看这几条）

1. 浏览器可**选择服务器上 `videos/` 目录的视频**、选择检测模式（sahi / direct）、调整常用参数，提交任务。
2. 任务运行中可看到**实时进度**（已处理帧数 / 总数 / 百分比 / ETA）与**实时日志**。
3. 运行中的任务可**取消**，状态正确落为 `cancelled`。
4. 结果页展示：**唯一计数**、**标注视频（可播放、可拖动进度）**、**检出帧快照网格**、**逐帧计数曲线**、**轨迹与参数 JSON**。
5. **任务列表**可见本次服务生命周期内的历史任务及其状态。
6. 配置错误返回**结构化字段级错误**（HTTP 422 + 字段路径），不再杀进程。
7. 全部产物仍落在 `runs/<视频名>_<时间戳>/`，格式与现有 `result.json` 兼容。

### 1.2 明确不在本期（已留接口）

| 不做的事 | 预留方式 |
| --- | --- |
| 用户登录 / 权限 / 审计 | Job 模型预留 `owner` 字段；API 层预留鉴权依赖注入位 |
| 任务队列 / 并发调度 / 配额 | `jobs/runner.py` 单 worker 线程池，接口不变可换 RQ/Celery/arq |
| 跨重启的历史检索、全文筛选 | SQLite 已落库，本期只做基础列表查询 |
| 报告导出（PDF / Excel） | `result.json` 已含全部所需字段，导出层可后置 |
| 大视频浏览器上传 | MVP 走"服务器本地路径选择"（4K 文件上传体验差且慢） |
| 离线 exe 打包 | 前端为静态产物，后续 Tauri/pywebview 包壳即可 |
| 多模型/ONNX/TensorRT 加速 | 权重登记接口保留，本期沿用 `best.pt` + Ultralytics |

---

## 2. 目标架构

### 2.1 目录结构（src 布局 + 分层）

```
pest_detector/
├── pyproject.toml                # 可安装 / 可打包 / 工具链配置（ruff、pytest）
├── configs.yaml                  # 保留：默认参数模板（前端表单的默认值来源）
├── configs/presets/*.yaml        # 参数预设（"快检" / "高精度"），可增删
├── best.pt
├── cli.py                        # 保留：薄转发入口 → pestdet.cli.main（旧命令不破坏）
├── src/pestdet/
│   ├── core/                     # 纯领域逻辑：无 I/O 副作用、无全局配置、可单测
│   │   ├── detector.py           #   build_detector / _SahiDetector / _DirectDetector
│   │   ├── pipeline.py           #   VideoPipeline（注入 logger / progress / cancel）
│   │   ├── tracker.py            #   从 utils/tracker.py 迁入，去掉 PIPELINE_CONFIG 依赖
│   │   ├── roi.py                #   从 utils/roi.py 迁入
│   │   ├── sahi.py               #   从 utils/sahi.py 迁入
│   │   ├── render.py             #   从 utils/render.py 迁入
│   │   └── snapshots.py          #   从 utils/snapshots.py 迁入
│   ├── config/
│   │   ├── schema.py             #   Pydantic 模型（替换 utils/config.py 的 _PIPELINE_SCHEMA）
│   │   ├── loader.py             #   load_config / merge_overrides / to_json_schema
│   │   └── errors.py             #   ConfigError（结构化字段错误，替代 SystemExit）
│   ├── jobs/
│   │   ├── models.py             #   Job 数据模型 + 状态枚举
│   │   ├── store.py              #   SQLite 持久化（job 记录 + 结果索引）
│   │   ├── runner.py             #   单 worker 执行器（ThreadPoolExecutor(max_workers=1)）
│   │   └── events.py             #   进度/日志事件总线（内存 pub/sub，多订阅者）
│   ├── services/
│   │   └── analyze.py            #   AnalyzeService：编排 config + core + job + 落盘
│   ├── infra/
│   │   ├── paths.py              #   从 utils/paths.py 迁入（PROJECT_ROOT 改为包相对解析）
│   │   ├── imageio.py            #   从 utils/imageio.py 迁入
│   │   ├── logging.py            #   日志装配：控制台 + logs/<job_id>.log
│   │   └── registry.py           #   权重登记（从 utils/registry.py 迁入）
│   ├── api/
│   │   ├── app.py                #   FastAPI 装配（路由、静态目录、CORS、异常处理）
│   │   ├── routes_jobs.py        #   任务相关路由
│   │   ├── routes_meta.py        #   videos / weights / config schema
│   │   └── errors.py             #   领域异常 → HTTP 状态码 + 结构化 body
│   └── cli/
│       └── main.py               #   薄 CLI：复用 services，保留现有全部子命令
├── web/                          # 前端（Vite + React + TS + Ant Design）
│   └── src/
│       ├── api/client.ts         #   API 封装 + SSE 订阅
│       ├── pages/NewJob.tsx      #   新建任务：视频选择 + 参数表单 + 提交
│       ├── pages/JobDetail.tsx   #   任务详情：进度 + 日志 + 结果可视化
│       └── pages/Jobs.tsx        #   任务列表
├── tests/
│   ├── test_config.py            #   配置校验（含错误分支）
│   ├── test_tracker_golden.py    #   golden test：固定帧序列 → 固定计数
│   └── test_api.py               #   API 冒烟（TestClient）
├── logs/                         # 运行日志（gitignore）
└── runs/                         # 运行产物（gitignore）
```

### 2.2 分层依赖规则（必须遵守，否则多用户阶段会返工）

```
api / cli  →  services  →  jobs  →  core
                 ↓          ↓
              config      infra
```

- **core 不得 import api / services / jobs**，不得读全局配置单例，不得 `print`、不得 `sys.exit`。
- **core 不得有 I/O 副作用**：文件读写、日志、进度上报全部由 `services` 注入。
- **config 是纯数据模型**：Pydantic 模型 + 加载器，无副作用。
- 每个任务持有**独立的 config 实例**（多用户并发的硬前提）。

### 2.3 技术栈

| 层 | 选型 | 理由 |
| --- | --- | --- |
| Web 框架 | **FastAPI + Uvicorn** | 原生 Pydantic v2，直接承接现有配置校验体系；OpenAPI 自动文档 |
| 配置模型 | **Pydantic v2** | 替换 `_PIPELINE_SCHEMA`；可导出 JSON Schema 驱动前端表单 |
| 进度推送 | **SSE（Server-Sent Events）** | 单向进度/日志流，比 WebSocket 简单、自动重连、过反向代理友好 |
| 阻塞推理执行 | **线程池（max_workers=1）** | 推理是阻塞式 CPU/GPU 调用，绝不能跑在 asyncio 事件循环里 |
| 任务持久化 | **SQLite（stdlib sqlite3）** | 零部署成本；多用户阶段无需换库 |
| 前端 | **Vite + React + TypeScript + Ant Design** | Form/Table/Progress/Upload 组件开箱即用，表单与任务列表开发量骤降 |
| 前端替代方案 | Vue 3 + Element Plus | 等价可行；若团队更熟 Vue 可替换，不影响后端 |
| 日志 | **标准 logging** | 控制台 + `logs/<job_id>.log`，替代 core 内的 print |
| 测试 | **pytest + coverage** | 见第 5 节 |

> 前端框架是本期唯一"可自由替换"的选型，后端接口不因此改变。

---

## 3. 现有资产复用（重要）

改造不是重写，以下资产直接复用，这是本项目的优势：

| 资产 | 现状 | MVP 处理 |
| --- | --- | --- |
| **`result.json` 结构** | 已含 `counting.unique_count`、`tracks[].path`（逐帧中心点）、`per_frame`、`roi`、`snapshots`、`config` | **不重构**。README 已注明"供 UI 下游读取"，字段即前端数据契约 |
| **H.264 转码** | `utils/render.py` 写完视频自动转 H.264 | **直接受益**：浏览器 `<video>` 原生可播、可拖动，无需额外转码 |
| **进度回调** | `VideoPipeline.run(progress_cb=...)` | 接事件总线 → SSE，几乎零改造 |
| **检测器注入** | `build_detector(..., detector=...)` / `_detect_batch` 回退分支 | 保留，供测试注入假检测器（golden test 用） |
| **快照输出** | `utils/snapshots.py` 落 `frames/` | 静态目录直接暴露给前端网格展示 |
| **配置字段校验** | `_PIPELINE_SCHEMA` 已覆盖全部字段与取值范围 | 逐字段翻译成 Pydantic 模型，校验能力不丢 |

---

## 4. 关键改造点（文件级）

| 文件 | 现状问题 | 改造方案 |
| --- | --- | --- |
| `utils/config.py` | **导入即 `load_pipeline_config()` + 校验失败 `raise SystemExit(1)`** | 拆为 `config/schema.py`（Pydantic 模型）+ `config/loader.py`（`load_config()` 返回模型或抛 `ConfigError`）。**移除全部 import 期副作用** |
| `utils/tracker.py` | `IoUTracker.__init__` 读全局 `PIPELINE_CONFIG["tracker"]` | 改为**显式传入** tracker 配置 dict；core 不再依赖任何全局单例 |
| `pipeline.py` | 混合了 argparse、print、流程逻辑；无取消机制 | 拆为 `core/pipeline.py`（纯流程，注入 logger/progress/cancel）+ `cli/main.py`（argparse）+ `services/analyze.py`（编排） |
| `utils/render.py` | `print` 告警 | 改 `logging.warning`，行为不变 |
| `cli.py`（根） | 直接实现子命令分发 | 保留为**转发入口**（`from pestdet.cli.main import main`），旧命令 `python cli.py sahi ...` 继续可用 |
| `utils/paths.py` | `PROJECT_ROOT = utils 的父目录` 硬编码 | 迁入 `infra/paths.py`，改为可配置的工作根（支持 `PESTDET_HOME` 环境变量） |
| `configs.yaml` | 全局唯一配置源 | 保留为**默认模板**；支持 per-job 覆盖；新增 `configs/presets/*.yaml` |
| `requirements.txt` | 无包元数据、无工具链 | 迁移到 `pyproject.toml`（`[project]` + `[project.optional-dependencies]` dev） |

### 4.1 取消机制（MVP 必须有）

当前 `VideoPipeline.run` 无取消能力。多用户服务器上，一个失控的 4K 任务会**占死 GPU**，必须能停。

改造方式：`run(..., cancel=None)` 接收一个可调用对象/事件，在帧循环内每帧检查一次：

```python
# core/pipeline.py 帧循环内
if cancel is not None and cancel():
    logger.info("任务被取消，已处理 %d 帧", processed)
    cap.release()
    raise JobCancelled(processed)
```

`JobCancelled` 由 `services` 捕获 → 状态置 `cancelled` → 已产出的中间产物保留、不写最终 JSON。

---

## 5. API 契约（MVP）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/meta/videos` | 列出 `videos/` 下可用视频（名称、路径、大小、时长） |
| `GET` | `/api/meta/weights` | 列出已登记权重（pest{N}、标签、mAP、路径） |
| `GET` | `/api/meta/config-schema` | 返回参数 JSON Schema（供前端生成表单）+ 默认值 |
| `GET` | `/api/meta/presets` | 列出参数预设 |
| `POST` | `/api/jobs` | 创建并启动任务，body = `{source, mode, params, preset?}`，返回 `{job_id}` |
| `GET` | `/api/jobs` | 任务列表（分页、按创建时间倒序） |
| `GET` | `/api/jobs/{id}` | 任务状态 + 进度快照 + 结果摘要 |
| `GET` | `/api/jobs/{id}/events` | **SSE**：进度事件 + 日志行，直到任务终态 |
| `POST` | `/api/jobs/{id}/cancel` | 请求取消 |
| `GET` | `/api/jobs/{id}/result` | 返回 `result.json` |
| `GET` | `/api/jobs/{id}/video` | 标注视频（支持 HTTP Range，浏览器可拖动） |
| `GET` | `/api/jobs/{id}/frames` | 检出帧快照列表 |
| `GET` | `/api/jobs/{id}/frames/{name}` | 单张快照图片 |
| `GET` | `/api/jobs/{id}/logs` | 完整日志文本 |

**Job 状态机**：`queued → running → succeeded | failed | cancelled`

```python
@dataclass
class Job:
    id: str
    status: JobStatus
    owner: str | None          # 多用户预留，本期恒为 None
    source: str
    mode: str                  # sahi | direct
    params: dict               # 生效的完整参数快照（可复现）
    created_at: str
    started_at: str | None
    finished_at: str | None
    progress: dict             # {done, total, elapsed}
    out_dir: str | None
    summary: dict | None       # 结果摘要（unique_count 等）
    error: dict | None         # {code, message}
```

---

## 6. 任务拆解与排期

> 工时按单人全职估算，仅供排序参考；每阶段结束均有可验证产物。

### P0 — 工程与配置打底（MVP 前置最小集，约 1–2 天）

> 不做这步，Web 应用无从谈起（导入即 `SystemExit` 的配置模块无法在服务里运行）。

- [ ] `git init`，完善 `.gitignore`（补 `logs/`、`web/node_modules/`、`web/dist/`、`*.db`），首次提交
- [ ] 建 `pyproject.toml`：src 布局、依赖、`[project.optional-dependencies].dev`（pytest/ruff/black）、ruff/black/pytest 配置
- [ ] `utils/*` → `src/pestdet/{core,infra}/` 迁移；根 `cli.py` 保留为转发入口
- [ ] `utils/config.py` → Pydantic 模型 + `ConfigError`，**移除 import 期副作用与 `SystemExit`**
- [ ] `IoUTracker` 去掉全局 `PIPELINE_CONFIG` 依赖，改显式传参
- [ ] core 内 `print` → `logging`
- [ ] **冒烟对比**：`python cli.py sahi --source videos/test0.mp4 --max-frames 20` 结果与改造前一致

**验收**：旧命令行为不变；配置写错返回结构化错误而非杀进程。

### P1 — 服务层与任务模型（约 2–3 天）

- [ ] `jobs/models.py`：Job + 状态枚举
- [ ] `jobs/store.py`：SQLite 建表与增删查改
- [ ] `jobs/events.py`：进度/日志事件总线（支持多订阅者）
- [ ] `jobs/runner.py`：单 worker 线程池执行器 + 取消
- [ ] `core/pipeline.py`：加 `cancel` 参数，帧循环内协作式检查
- [ ] `services/analyze.py`：装配 config → core → job，写 `result.json`，产出落盘
- [ ] `infra/logging.py`：按 job 落 `logs/<job_id>.log`，同时推给事件总线
- [ ] `api/`：FastAPI 装配 + 全部路由 + 异常映射 + `runs/` 静态目录（含 Range 支持）

**验收**：`curl` 提交任务 → SSE 收到进度 → 拿到 `result.json` 与 `tracked.mp4`；取消生效。

### P2 — 前端 MVP（约 3–5 天）

- [ ] Vite + React + TS + Ant Design 脚手架，`api/client.ts` 封装
- [ ] **新建任务页**：服务器视频下拉、检测模式切换、常用参数表单（schema 驱动）、提交
- [ ] **任务详情页**：SSE 进度条 + 实时日志尾随 + 取消按钮
- [ ] **结果可视化**：计数卡片、`tracked.mp4` 播放器、快照网格、逐帧计数曲线、轨迹/参数 JSON
- [ ] **任务列表页**：状态标签、时间、计数、进入详情

**验收**：浏览器完成"选视频 → 跑 → 看进度 → 看结果"全链路。

### P3 — 收尾与文档（约 2–3 天）

- [ ] 快照大图预览、轨迹叠加到帧上（用 `tracks[].path`）
- [ ] 参数预设保存/加载（`configs/presets/*.yaml`）
- [ ] 一键启动脚本（构建前端 → 启动 uvicorn）+ 开发模式说明
- [ ] 最小测试集：`test_config.py`、`test_tracker_golden.py`、`test_api.py`
- [ ] README 重写：安装、启动、部署到 GPU 服务器的步骤
- [ ] 写一份 `docs/DEPLOY.md`（GPU 服务器部署说明）

**验收**：按文档在新机器上能跑起来；测试全绿。

---

## 7. 风险与对策

| # | 风险 | 影响 | 对策 |
| --- | --- | --- | --- |
| 1 | 8GB 显存 OOM（4K + batch 过大） | 任务失败、GPU 卡死 | 单 worker 串行；捕获 CUDA OOM 转成可读提示；前端暴露 batch/imgsz 但标注"显存敏感" |
| 2 | 推理阻塞 asyncio 事件循环 | 所有用户一起卡死 | 推理强制走线程池；禁止在路由里直接 `await` 阻塞调用 |
| 3 | 4K 视频浏览器播放/拖动卡顿 | 结果页不可用 | 复用现有 H.264 转码 + `/video` 支持 HTTP Range |
| 4 | 迁移破坏现有 CLI 与 `python -m utils.*` 入口 | 旧用法失效 | 根 `cli.py` 转发；`utils/` 迁移后更新 README；P0 做冒烟对比 |
| 5 | 配置去 `SystemExit` 影响面广 | 遗漏调用点导致崩溃 | 一次性改完 + `test_config.py` 覆盖错误分支 |
| 6 | 长任务 + 无取消 → GPU 被占死 | 服务器不可用 | 取消机制列入 MVP 必做项（P1） |
| 7 | 前端经验不足拖慢进度 | P2 超期 | 选 Ant Design，表单/表格/进度开箱即用；后端接口先行，前端可并行 |
| 8 | 全局配置单例残留 | 多用户并发互相污染 | 分层规则 + code review 卡点：core 禁止 import 全局配置 |

---

## 8. 架构演进路径（本期之后，供决策参考）

```
本期 MVP（单任务串行）
   └─ 单进程 Uvicorn + 1 worker 线程池 + 内存事件总线 + SQLite

下一阶段（多用户）
   ├─ 鉴权：JWT/OAuth，Job.owner 落地，按 owner 过滤列表
   ├─ 调度：runner 换为 RQ/Celery/arq + Redis，队列 + 并发上限 + 配额
   ├─ 资源隔离：模型常驻独立推理进程（GPU 只允许一个持有者），API 与推理进程分离
   ├─ 事件总线：内存 pub/sub → Redis Pub/Sub（跨进程/多 Uvicorn worker）
   └─ 报告导出：基于 result.json 生成 PDF/Excel
```

> 关键：本期的 `jobs/runner.py`、`jobs/events.py`、`Job.owner` 三个接口，就是上述演进的替换点。**MVP 阶段把这三个接口定对，后续多用户不需要重写。**

---

## 9. 待确认项（开工前）

1. 前端框架：默认 **React + Ant Design**，是否改用 **Vue 3 + Element Plus**？
2. 服务器上视频的放置方式：确认本期走"服务器本地目录选择"（不做浏览器上传）？
3. 服务监听与端口：是否需要在 `pyproject.toml`/启动脚本里固定（如 `0.0.0.0:8000`）？
4. 是否需要把 `best.pt`（124MB）继续用 Git LFS 管理，还是排除出版本库？