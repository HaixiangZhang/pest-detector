# pest_detector — 4K 视频/图片<害虫>检测与计数

在 4K 无人机航拍视频中检测草地上的小目标害虫，通过跨帧关联去重，
输出"视频里一共有多少只虫"的唯一计数，并产出标注视频、检出帧快照与结构化数据。

---

## 快速开始

```powershell
# 1. 安装依赖（PyTorch CUDA 12.8，适配 RTX 50 系）
pip install -r requirements.txt

# 2. 视频找虫（切片检测；权重留空则取 best.pt / 最新登记权重）
python cli.py sahi --source videos/test0.mp4

#    整帧直推（快，但 4K 小目标召回更低）
python cli.py direct --source videos/test0.mp4
```

产物默认写到 `runs/<视频名>_<时间戳>/`：

| 文件 | 内容 |
| --- | --- |
| `tracked.mp4` | 推理后视频（检测框 + track ID + 轨迹尾迹 + 计数面板；默认转 H.264，见下） |
| `frames/` | 检出帧快照（每个判定有虫的帧一张带框标注的整帧） |
| `result.json` | 结构化数据（`counting.unique_count` 即最终计数） |

---

## 统一命令行入口

所有功能收敛到 `cli.py`，用子命令区分：

| 子命令 | 作用 | 底层实现 |
| --- | --- | --- |
| `sahi` | 切片检测 → 跨帧去重计数 → 视频/JSON | `pipeline.detect_main` |
| `direct` | 整帧直推 → 跨帧去重计数 → 视频/JSON | `pipeline.detect_main` |
| `roi` | 草地 ROI 遮罩调参预览 | `utils.roi.roi_main` |
| `weights` | 权重登记管理（pest{N} 版本链） | `utils.registry.weights_main` |

检测模式直接作为子命令，两者共用同一套视频流程（遮罩 → 检测 → 跨帧去重计数 → 产物），
不再有 `detect` 中间层；差异只在检测器本身（切片 / 整帧）。

`cli.py` 是统一推荐入口；`pipeline.py` 无独立入口（已移除自执行块），只作为库被 import。
`utils/sahi.py`、`utils/roi.py`、`utils/registry.py` 仍保留 `python -m utils.<mod>` 直调入口，便于单独调试；
其中 `python -m utils.sahi` 是**纯切片推理**（图片/目录/视频，只检测画框、不做遮罩/跟踪/计数），
与 `cli.py sahi`（完整视频流程）不是一回事。

```powershell
python cli.py --help              # 列出全部子命令
python cli.py sahi --help         # 查看某子命令的参数
```

---

## 目录结构

```
pest_detector/
├── cli.py                # 统一命令行入口（sahi / direct / roi / weights）
├── pipeline.py           # 视频检测工作流实现（sahi / direct 子命令的落点）
├── requirements.txt      # 依赖清单
├── configs.yaml          # 部署参数
├── best.pt               # 部署权重（YOLO11x-P2 单类别模型，Git LFS 管理）
├── README.md
├── .gitattributes        # Git LFS 规则（*.pt 等大文件）
│
├── docs/
│   └── yolo11x_p2.yaml   #   归档: YOLO11x-P2 训练用模型结构定义（部署链路不引用）
│
├── utils/                # 部署运行时支撑包
│   ├── paths.py          #   路径常量 / 时间戳
│   ├── imageio.py        #   图片读取（兼容非 ASCII 路径）
│   ├── config.py         #   configs.yaml 加载 + 字段级校验 → PIPELINE_CONFIG
│   ├── registry.py       #   权重登记（pest{N} 版本链，runs/registry.json）
│   ├── sahi.py           #   SAHI 切片推理 + WBF/NMS 融合
│   ├── roi.py            #   草地四边形 ROI 遮罩
│   ├── tracker.py        #   跨帧 IoU 关联 + 轨迹后处理三步清洗
│   ├── render.py         #   第二遍重绘（最终 ID 标注帧）+ 视频写出 + ffmpeg 转 H.264
│   └── snapshots.py      #   检出帧快照
│
├── videos/               # 待检测视频统一存放（0721.mp4、test0/2/3.mp4、show1.mp4）
└── runs/                 # 运行输出（含 registry.json 与每次运行的独立目录）
```

---

## 配置

所有部署参数集中在项目根的 **`configs.yaml`**，改参数只改该文件，无需动代码。
优先级链：**CLI 显式参数 > `configs.yaml` > 代码内置默认值**。

启动时会做**字段级校验**，缺字段、类型写错、取值越界、字段名拼错都会逐条报错并终止：
~
```~
[错误] 部署配置校验失败: configs.yaml
  - mode: 取值应为 sahi/direct 之一，实际 'turbo'
  - sahi.conf: 应 ≤ 1.0，实际 1.5
  - sahi.slice_sise: 未知字段（可用字段: slice_size, overla~p_ratio, ...）
```

`mask` / `tracker` / `snapshots` / `encode` 四节也必须写全，对应 `utils/roi.py`、
`utils/tracker.py`、`utils/snapshots.py`、`utils/render.py` 消费的参数。默认值只存在于
`configs.yaml` 一处（模块顶部不再自带 `*_DEFAULTS`），避免两处调参漂移。

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

# 整帧直推（更快，精度略低）
python cli.py direct --source videos/test0.mp4

# 调试：抽帧 + 只出数据、关闭草地遮罩、不存快照
python cli.py sahi --source videos/test0.mp4 --stride 2 --no-video
python cli.py sahi --source videos/test0.mp4 --no-mask
python cli.py sahi --source videos/test0.mp4 --no-snapshots

# 权重登记与查询
python cli.py weights --save best.pt --tag deploy
python cli.py weights --save best.pt --tag deploy --metrics mAP50=0.87
python cli.py weights --list

# 纯切片推理（调试用；图片 / 目录 / 视频，只检测画框，不做遮罩/跟踪/计数）
python -m utils.sahi --source 4k.jpg --weights best.pt --multi-scale
python -m utils.sahi --source videos/test0.mp4 --weights best.pt --stride 3

# ROI 调参预览（确认绿色分割是否贴合草地）
python cli.py roi --source videos/test0.mp4 --out runs/roi_preview.png
```

---

## 注意

- 输出目录 **按需创建**：只有真正要写文件（视频 / JSON / 快照）时才建
  `runs/<视频名>_<时间戳>/`。因此"输出全关"或"中途报错"的运行**不会留下空目录**。
- 视频上的标注文字一律用 **ASCII**：`cv2.putText` 不支持中文，写中文会渲染成乱码；
  中文说明只出现在终端输出与 `result.json` 里。
- `runs/` 为运行产物目录，已加入 `.gitignore`，不入库。
- 检测与绘制分两遍执行：第一遍只检测+关联，第二遍按后处理后的最终 ID 重绘，
  保证**画面中的框与 ID 和最终计数严格一致**。