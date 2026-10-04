# pest_detector Web 化 MVP — 执行清单（todo.md）

> 配套文档：[PLAN_web_mvp.md](./PLAN_web_mvp.md)
> 本文档按**执行顺序**列出每一步要动哪些文件（新建 / 修改 / 删除），可逐条勾选。
> 范围：仅 MVP（P0–P3），不含多用户完整版。

---

## 0. Skill 盘点

### 0.1 本地已有、且本项目会用到的 skill

| Skill | 用途 | 用在阶段 | 本地状态 |
| --- | --- | --- | --- |
| `frontend-design` | 生产级前端界面设计（React 页面/组件/仪表盘） | **P2 主力** | ✅ 已装 `~/.trae-cn/skills/frontend-design` |
| `trae-remote-official:web-app-development:uicraft` | 前端 UI 打磨/审计/响应式（frontend-design 的增强备选） | P2 备选 | ✅ 已装（插件 `web-app-development@0.1.1`） |
| `TRAE-browseruse` | 浏览器自动化，验证前端页面渲染与交互 | P2/P3 验收 | ✅ 已装 `builtin_skills/TRAE-browseruse` |
| `doc-writing-guide` | 结构化文档写作（README / DEPLOY.md） | P0、P3 | ✅ 已装（内置） |
| `skill-creator` | 把项目流程沉淀成可复用 skill | 可选（后续） | ✅ 已装 `builtin_skills/skill-creator` |

### 0.2 本地没有、但可能需要（结论：不需要额外安装）

| 可能需要的 skill | 结论 |
| --- | --- |
| Python 后端 / 工程化 / 重构 skill | **本地无，也不需要**——P0/P1 是常规 Python 工程改造，用内置编码能力直接做 |
| 测试生成 skill | **本地无**，用 `pytest` 手写即可，无需 skill |
| 打包（PyInstaller/Docker）skill | **本地无**，且不在 MVP 范围 |
| FastAPI / Pydantic 专用 skill | **本地无**，属通用框架知识，无需 skill |

> 结论：**MVP 全程只需 2 个功能性 skill（P2 前端 + P3 文档）+ 1 个验证 skill（浏览器）**，其余靠内置能力。

### 0.3 本地有、但本项目明确不用

| Skill | 不用的原因 |
| --- | --- |
| `html-report` / `html-deck` / `dynamic-ui` | 你的规则是**报告用 md 而非 html**，且本项目不产出报告类交付物 |
| `trae-remote-official:lark:*`（全部） | 与项目无关（飞书协作） |
| `chinese-copyright-application` / `software-copyright-materials` | 非本期目标；**将来申请软著时可用**（本项目是完整软件，适配度高） |
| `xlsx` / `docx` / `pdf` | 报告导出不在 MVP 范围（后续阶段做"结果导出"时可用） |
| `research-guide` / `TRAE-product-knowledge` / `feedback` | 与本任务无关 |

---

## 1. 执行顺序总览

```
P0 工程与配置打底 ──► P1 服务层与任务模型 ──► P2 前端 MVP ──► P3 收尾与文档
   (1–2 天)              (2–3 天)               (3–5 天)          (2–3 天)
   Git/包结构/            Job/SSE/FastAPI       表单/进度/        预设/测试/
   配置去全局             /取消/静态服务         结果可视化        启动脚本/DEPLOY
```

| 阶段 | 完成标志（验收） | 依赖 skill |
| --- | --- | --- |
| P0 | 旧命令行为不变；配置写错返回结构化错误而非杀进程 | `doc-writing-guide`（仅 README） |
| P1 | `curl` 提交任务 → SSE 收到进度 → 拿到 result.json 与 tracked.mp4；取消生效 | 无 |
| P2 | 浏览器完成"选视频 → 跑 → 看进度 → 看结果"全链路 | `frontend-design`、`TRAE-browseruse` |
| P3 | 按文档在新机器跑通；测试全绿 | `doc-writing-guide` |

---

## 2. 文件变更总清单

### 2.1 需新建（共约 50 个）

**P0 — 工程与配置打底**

| # | 文件 | 说明 |
| --- | --- | --- |
| 1 | `pyproject.toml` | src 布局、依赖、`[project.optional-dependencies].dev`、ruff/black/pytest 配置 |
| 2 | `.pre-commit-config.yaml` | ruff + black 钩子（可选但推荐） |
| 3 | `src/pestdet/__init__.py` | 包根，暴露 `__version__` |
| 4 | `src/pestdet/core/__init__.py` | — |
| 5 | `src/pestdet/core/detector.py` | `build_detector` / `_SahiDetector` / `_DirectDetector`（自 `pipeline.py` 迁入） |
| 6 | `src/pestdet/core/pipeline.py` | `VideoPipeline`（自 `pipeline.py` 迁入，改注入 logger/progress/cancel） |
| 7 | `src/pestdet/core/tracker.py` | 自 `utils/tracker.py` 迁入，**去掉 `PIPELINE_CONFIG` 全局依赖** |
| 8 | `src/pestdet/core/roi.py` | 自 `utils/roi.py` 迁入 |
| 9 | `src/pestdet/core/sahi.py` | 自 `utils/sahi.py` 迁入 |
| 10 | `src/pestdet/core/render.py` | 自 `utils/render.py` 迁入（`print` → `logging`） |
| 11 | `src/pestdet/core/snapshots.py` | 自 `utils/snapshots.py` 迁入 |
| 12 | `src/pestdet/core/errors.py` | 领域异常：`JobCancelled`、`DetectionError` 等 |
| 13 | `src/pestdet/config/__init__.py` | — |
| 14 | `src/pestdet/config/schema.py` | Pydantic 模型（替换 `_PIPELINE_SCHEMA`） |
| 15 | `src/pestdet/config/loader.py` | `load_config` / `merge_overrides` / `to_json_schema` |
| 16 | `src/pestdet/config/errors.py` | `ConfigError`（结构化字段错误，替代 `SystemExit`） |
| 17 | `src/pestdet/infra/__init__.py` | — |
| 18 | `src/pestdet/infra/paths.py` | 自 `utils/paths.py` 迁入（`PROJECT_ROOT` 改为可配置工作根） |
| 19 | `src/pestdet/infra/imageio.py` | 自 `utils/imageio.py` 迁入 |
| 20 | `src/pestdet/infra/logging.py` | 日志装配：控制台 + `logs/<job_id>.log` |
| 21 | `src/pestdet/infra/registry.py` | 自 `utils/registry.py` 迁入 |
| 22 | `src/pestdet/cli/__init__.py` | — |
| 23 | `src/pestdet/cli/main.py` | 薄 CLI（argparse），复用 services，保留全部旧子命令 |
| 24 | `tests/__init__.py` | — |
| 25 | `tests/conftest.py` | fixture：临时配置、假检测器、临时输出目录 |
| 26 | `tests/test_config.py` | 配置校验（含错误分支） |
| 27 | `tests/test_tracker_golden.py` | golden test：固定帧序列 → 固定计数 |
| 28 | `logs/.gitkeep` | 占位，保证目录存在 |

**P1 — 服务层与任务模型**

| # | 文件 | 说明 |
| --- | --- | --- |
| 29 | `src/pestdet/jobs/__init__.py` | — |
| 30 | `src/pestdet/jobs/models.py` | `Job` + `JobStatus` 状态枚举（含预留字段 `owner`） |
| 31 | `src/pestdet/jobs/store.py` | SQLite 建表与增删查改 |
| 32 | `src/pestdet/jobs/runner.py` | 单 worker 线程池执行器 + 取消（多用户阶段换 RQ/Celery 的替换点） |
| 33 | `src/pestdet/jobs/events.py` | 进度/日志事件总线（内存 pub/sub，多订阅者） |
| 34 | `src/pestdet/services/__init__.py` | — |
| 35 | `src/pestdet/services/analyze.py` | `AnalyzeService`：编排 config + core + job + 落盘 |
| 36 | `src/pestdet/api/__init__.py` | — |
| 37 | `src/pestdet/api/app.py` | FastAPI 装配（路由、静态目录、CORS、异常处理） |
| 38 | `src/pestdet/api/routes_jobs.py` | 任务路由（创建/查询/SSE/取消/结果/视频/快照/日志） |
| 39 | `src/pestdet/api/routes_meta.py` | videos / weights / config-schema / presets |
| 40 | `src/pestdet/api/errors.py` | 领域异常 → HTTP 状态码 + 结构化 body |
| 41 | `src/pestdet/api/deps.py` | 依赖注入位（**预留鉴权**，本期空实现） |
| 42 | `src/pestdet/server.py` | uvicorn 启动入口（`python -m pestdet.server`） |

**P2 — 前端 MVP**

| # | 文件 | 说明 |
| --- | --- | --- |
| 43 | `web/package.json` / `web/vite.config.ts` / `web/tsconfig.json` / `web/index.html` | Vite + React + TS 脚手架 |
| 44 | `web/src/main.tsx` / `web/src/App.tsx` | 应用入口 + 路由 |
| 45 | `web/src/api/client.ts` / `web/src/api/types.ts` | API 封装 + SSE 订阅 + 类型定义 |
| 46 | `web/src/pages/NewJob.tsx` | 新建任务：视频选择 + 模式切换 + 参数表单 + 提交 |
| 47 | `web/src/pages/JobDetail.tsx` | 任务详情：进度 + 日志 + 结果可视化 |
| 48 | `web/src/pages/Jobs.tsx` | 任务列表 |
| 49 | `web/src/components/*.tsx` | `ProgressPanel` / `LogViewer` / `ResultView` / `SnapshotGrid` / `PerFrameChart` |

**P3 — 收尾与文档**

| # | 文件 | 说明 |
| --- | --- | --- |
| 50 | `configs/presets/fast.yaml`、`configs/presets/accurate.yaml` | 参数预设（"快检" / "高精度"） |
| 51 | `scripts/start.ps1` | 一键启动（构建前端 → 启动 uvicorn） |
| 52 | `docs/DEPLOY.md` | GPU 服务器部署说明 |
| 53 | `tests/test_api.py` | API 冒烟（`TestClient`） |
| 54 | `.github/workflows/ci.yml` | CI：lint + test（可选，无远端可先只写脚本） |

### 2.2 需修改

| # | 文件 | 改什么 | 阶段 |
| --- | --- | --- | --- |
| 1 | `.gitignore` | 补 `logs/`、`web/node_modules/`、`web/dist/`、`*.db`、`.venv/`、`.ruff_cache/` | P0 |
| 2 | `cli.py`（根） | 改为**薄转发入口**：`from pestdet.cli.main import main`，旧命令继续可用 | P0 |
| 3 | `configs.yaml` | 保留为**默认模板**；补注释说明"支持 per-job 覆盖 / presets" | P0 |
| 4 | `README.md` | 重写：新目录结构、安装、启动、旧命令兼容说明 | P0（初版）/ P3（定稿） |
| 5 | `docs/PLAN_web_mvp.md` | 随进展勾选完成项 | 全程 |

### 2.3 需删除

| # | 路径 | 原因 | 阶段 | 风险 |
| --- | --- | --- | --- | --- |
| 1 | `pipeline.py` | 内容迁入 `src/pestdet/core/pipeline.py` + `cli/main.py` | P0 | 低（根 `cli.py` 转发已兜底） |
| 2 | `requirements.txt` | 迁入 `pyproject.toml` | P0 | 低 |
| 3 | `utils/`（整包 9 个 .py + `__init__.py`） | 拆入 `core/` 与 `infra/` | P0 | 低（已确认 `python -m utils.sahi` 未被使用，可直接删除） |
| 4 | `__pycache__/` | 缓存，无价值 | P0 | 无 |

### 2.4 破坏性变更：删除 `utils/`（**已确认执行**）

**决策：方案 A — 一次性删除，不留转发层。** 用户已确认 `python -m utils.sahi` 未被使用。

删除范围与连带影响：

| 被删入口 | 连带影响 | 替代方式 |
| --- | --- | --- |
| `python -m utils.sahi` | 纯切片推理调试入口失效 | 用 `python cli.py sahi`（完整视频流程）；若日后确需"只切片、不跟踪计数"的纯调试，在 `cli/` 下补一个 `slice` 子命令 |
| `python -m utils.roi` | ROI 调参预览入口失效 | `python cli.py roi`（根转发入口保留，不受影响） |
| `python -m utils.registry` | 权重登记入口失效 | `python cli.py weights`（根转发入口保留，不受影响） |

**P0.18 必须同步完成两件事**：
1. 更新 `README.md` 中所有 `python -m utils.*` 用法与目录结构说明；
2. **更新项目记忆**中"`python -m utils.sahi` 是纯切片推理调试入口"这条硬约束，改为记录新的包结构约定（`src/pestdet/{core,infra,config,jobs,services,api,cli}`）。

---

## 3. 分阶段详细 Todo（按执行顺序）

### P0 — 工程与配置打底（1–2 天）

- [ ] **P0.1** `git init`；完善 `.gitignore`（补 `logs/`、`web/node_modules/`、`web/dist/`、`*.db`、`.venv/`、`.ruff_cache/`）
- [ ] **P0.2** 首次提交（先把当前可运行状态入库，作为改造前的基线）
- [ ] **P0.3** 新建 `pyproject.toml`（src 布局、依赖迁移自 `requirements.txt`、dev 依赖、ruff/black/pytest 配置）
- [ ] **P0.4** 建 `src/pestdet/` 包骨架（`__init__.py` × 各层）
- [ ] **P0.5** 迁移 `utils/paths.py` → `src/pestdet/infra/paths.py`（`PROJECT_ROOT` 改为可配置工作根，支持 `PESTDET_HOME`）
- [ ] **P0.6** 迁移 `utils/imageio.py` → `src/pestdet/infra/imageio.py`
- [ ] **P0.7** 迁移 `utils/registry.py` → `src/pestdet/infra/registry.py`
- [ ] **P0.8** 迁移 `utils/{tracker,roi,sahi,render,snapshots}.py` → `src/pestdet/core/`
- [ ] **P0.9** `core/tracker.py`：**去掉 `PIPELINE_CONFIG` 全局依赖**，`IoUTracker(config=...)` 显式传参
- [ ] **P0.10** `core/render.py`：`print` 告警 → `logging.warning`
- [ ] **P0.11** 迁移 `pipeline.py` 的检测器部分 → `core/detector.py`
- [ ] **P0.12** 迁移 `pipeline.py` 的 `VideoPipeline` → `core/pipeline.py`（去掉 argparse/print，注入 logger/progress）
- [ ] **P0.13** `core/pipeline.py`：新增 `cancel` 参数 + 帧循环内协作式取消检查 + 抛 `JobCancelled`
- [ ] **P0.14** `utils/config.py` → `config/schema.py`（Pydantic 模型，逐字段翻译 `_PIPELINE_SCHEMA`）
- [ ] **P0.15** `config/loader.py` + `config/errors.py`：**移除 import 期副作用与 `SystemExit`**，改抛 `ConfigError`
- [ ] **P0.16** 迁移 argparse 部分 → `cli/main.py`（保留 `sahi` / `direct` / `roi` / `weights` 全部子命令）
- [ ] **P0.17** 根 `cli.py` 改为转发 `pestdet.cli.main:main`
- [ ] **P0.18** 删除 `pipeline.py`、`requirements.txt`、`utils/`（方案 A，一次性删除）、`__pycache__/`；同步更新 `README.md` 与项目记忆（见 2.4）
- [ ] **P0.19** 写 `tests/conftest.py` + `tests/test_config.py`（配置校验，含错误分支）
- [ ] **P0.20** 写 `tests/test_tracker_golden.py`（用 `detector` 注入假检测器，锁死"固定帧序列 → 固定计数"）
- [ ] **P0.21** **冒烟对比**：`python cli.py sahi --source videos/test0.mp4 --max-frames 20` 与改造前输出一致
- [ ] **P0.22** `README.md` 初版更新（新结构 + 兼容说明）

**P0 验收**：旧命令行为不变；配置写错返回结构化错误而非杀进程；`pytest` 通过。

### P1 — 服务层与任务模型（2–3 天）

- [ ] **P1.1** `jobs/models.py`：`Job` + `JobStatus`（含预留 `owner`）
- [ ] **P1.2** `jobs/store.py`：SQLite 建表 + CRUD
- [ ] **P1.3** `jobs/events.py`：事件总线（支持多订阅者，供 SSE）
- [ ] **P1.4** `jobs/runner.py`：`ThreadPoolExecutor(max_workers=1)` + 取消
- [ ] **P1.5** `infra/logging.py`：按 job 落 `logs/<job_id>.log`，同时推给事件总线
- [ ] **P1.6** `services/analyze.py`：装配 config → core → job → 写 `result.json`
- [ ] **P1.7** `api/errors.py`：领域异常 → HTTP + 结构化 body
- [ ] **P1.8** `api/deps.py`：依赖注入位（预留鉴权，本期空实现）
- [ ] **P1.9** `api/routes_meta.py`：videos / weights / config-schema / presets
- [ ] **P1.10** `api/routes_jobs.py`：创建 / 列表 / 详情 / **SSE 事件流** / 取消 / result / video（**支持 Range**）/ frames / logs
- [ ] **P1.11** `api/app.py`：装配路由 + `runs/` 静态目录 + CORS + 异常处理
- [ ] **P1.12** `server.py`：uvicorn 启动入口

**P1 验收**：`curl` 建任务 → SSE 收到进度 → 拿到 `result.json` 与 `tracked.mp4`；取消生效且状态为 `cancelled`。

### P2 — 前端 MVP（3–5 天）

> 调用 skill：`frontend-design`（主力），必要时叠加 `trae-remote-official:web-app-development:uicraft` 打磨。

- [ ] **P2.1** Vite + React + TS + Ant Design 脚手架（`web/`）
- [ ] **P2.2** `api/client.ts` + `api/types.ts`：API 封装与 SSE 订阅
- [ ] **P2.3** 布局与路由（`App.tsx`）
- [ ] **P2.4** `NewJob.tsx`：服务器视频下拉、模式切换、**schema 驱动参数表单**、提交
- [ ] **P2.5** `ProgressPanel.tsx` + `LogViewer.tsx`：SSE 进度条 + 实时日志尾随 + 取消按钮
- [ ] **P2.6** `ResultView.tsx`：计数卡片 + `tracked.mp4` 播放器（可拖动）
- [ ] **P2.7** `SnapshotGrid.tsx`：检出帧快照网格 + 大图预览
- [ ] **P2.8** `PerFrameChart.tsx`：逐帧计数曲线（数据来自 `per_frame`）
- [ ] **P2.9** `Jobs.tsx`：任务列表（状态标签、时间、计数、进入详情）
- [ ] **P2.10** 用 `TRAE-browseruse` 验证全链路，修交互与样式问题

**P2 验收**：浏览器完成"选视频 → 跑 → 看进度 → 看结果"全链路。

### P3 — 收尾与文档（2–3 天）

- [ ] **P3.1** 轨迹叠加到帧上（用 `tracks[].path` 逐帧中心点）
- [ ] **P3.2** `configs/presets/*.yaml` + 前端预设保存/加载
- [ ] **P3.3** `scripts/start.ps1`：构建前端 → 启动 uvicorn
- [ ] **P3.4** `tests/test_api.py`：API 冒烟
- [ ] **P3.5** `docs/DEPLOY.md`（GPU 服务器部署：CUDA 环境、端口、ffmpeg、数据目录）
- [ ] **P3.6** `README.md` 定稿
- [ ] **P3.7** 更新项目记忆（目录结构、入口约定、配置模型变更）

**P3 验收**：按文档在新机器跑通；`pytest` 全绿。

---

## 4. 开工前的待确认项

| # | 待确认 | 影响 |
| --- | --- | --- |
| 1 | ~~`utils/` 删除还是保留转发层~~ **已确认：方案 A（一次性删除）** | 已解决，无影响 |
| 2 | 前端框架：默认 React + Ant Design，是否改用 Vue 3 + Element Plus | 决定 P2 全部文件 |
| 3 | 视频来源：确认本期走"服务器本地目录选择"，不做浏览器上传 | 决定 P1.9 / P2.4 |
| 4 | 服务监听与端口：是否固定（如 `0.0.0.0:8000`） | 决定 `server.py` / 启动脚本 |
| 5 | `best.pt`（124MB）继续走 Git LFS，还是排除出版本库 | 决定 `.gitattributes` / `.gitignore` |