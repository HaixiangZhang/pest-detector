# 网页端使用说明

本页由仓库内的 `docs/WEB_GUIDE.md` 渲染，断网也能看。

## 1. 启动（三种方式，任选其一）

### 方式一：Windows 双击

在资源管理器里双击项目根目录的 **`start.bat`**：脚本会自动找解释器 → 自检环境 → 启动服务 → 打开浏览器。

> 首次启动若 `web/dist` 缺失会自动构建前端（需要 Node.js）；仓库已附带构建产物时无需 Node。

### 方式二：PowerShell / 终端

```powershell
.\scripts\start.ps1 -Open          # 自检 + 启动 + 自动打开浏览器
.\scripts\start.ps1 -Build -Open   # 前端有改动时先重建再启动
.\scripts\start.ps1 -Port 8001     # 端口被占用时换端口
```

### 方式三：Linux / macOS

```bash
./app/scripts/start.sh --open
```

启动成功后浏览器打开 `http://127.0.0.1:8000/`；接口文档在 `/api/docs`（Swagger）。

## 2. 打开页面后自动做了什么

页面加载时会调用 `/api/system/info` 自动检测：

| 项目 | 说明 |
| --- | --- |
| CPU / 内存 | 型号、逻辑核心数、内存总量与可用量 |
| GPU | 显卡型号、显存总量 / 空闲、算力、驱动版本、CUDA 版本 |
| 软件 | Python、PyTorch、Ultralytics、OpenCV、FastAPI、ffmpeg |
| 权重 | `configs.yaml` 的 `model_path` 是否存在、体积是否正常 |

**权重自动下载**：检测到权重缺失（或只是 Git LFS 指针文件）时，页面顶部会出现进度条，
后台自动从 RicePest 的 GitHub Release 下载到 `model_path` 位置，并做 SHA256 校验。
下载失败时顶部会给出失败原因和手动下载地址。内网环境可以设置：

```powershell
$env:PESTDET_WEIGHT_URL = "http://内网镜像/tiling_104121.pt"
```

## 3. 页面功能

- **新建任务**：上传视频（或从服务器视频库选）→ 选检测模式 → 调参数 → 提交。
- **任务列表**：查看历史任务与状态，5 秒自动刷新。
- **任务详情**：进度、实时日志、结果（唯一计数 / 标注视频 / 检出帧 / 逐帧曲线 / 轨迹）。
- **系统环境**：完整硬件与软件清单，可「重新检测」或手动触发权重下载。
- **使用文档**：就是本页，外加 `README.md` 与 `docs/DEPLOY.md`。

## 4. 检测模式怎么选

| 模式 | 特点 | 适用 |
| --- | --- | --- |
| `sahi` 切片 | 640 切片分别推理再融合，4K 小目标召回高 | 默认，精度优先 |
| `direct` 整帧直推 | 整帧缩放到 `imgsz` 一次前向，速度快 | 追求吞吐、目标较大 |

显存参考（`batch` 是显存敏感项）：

| 显存 | `sahi.batch` | `direct.batch` |
| --- | --- | --- |
| 8 GB | 1–4 | 1–2 |
| 12–16 GB | 4–8 | 2–4 |
| 24 GB+ | 8–16 | 4–8 |

## 5. 保存推理配置

在「新建任务」页调好参数后，点 **「保存推理配置」**：

- 参数写入 `configs/presets/default.yaml`（即「默认」预设）；
- 下次打开页面会自动带出保存的参数；
- 想恢复 `configs.yaml` 的原始取值，直接编辑该文件或删除它即可。

## 6. 常见问题

**提示找不到装有依赖的 Python**
脚本会自动扫描 conda 环境；仍失败时显式指定：

```powershell
.\scripts\start.ps1 -Python "D:\miniconda3\envs\yolo11\python.exe" -Open
```

**提示端口被占用**：如果占用者就是本项目的服务，双击启动会自动复用并只打开浏览器，
无需重复启动；若被其它程序占用，换端口 `-Port 8001`，或结束占用该端口的进程。

**权重自动下载失败**：多半是 Release 尚未上传或网络受限。手动下载后放到
`configs.yaml` 中 `model_path` 指向的位置（默认 `./best.pt`）即可，页面会自动识别。

**任务报 CUDA out of memory**：把 `batch` 调小；或改用 `direct` 模式并降低 `imgsz`。

**输出视频拖动卡顿**：安装 ffmpeg 并加入 PATH（脚本自检会提示），输出会转成 H.264。
