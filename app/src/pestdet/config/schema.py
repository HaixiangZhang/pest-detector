"""schema — 部署配置的字段级模型（Pydantic v2）。

由原 utils/config.py 的 ``_PIPELINE_SCHEMA`` 逐字段翻译而来，校验能力保持一致:
类型 / 取值枚举 / 上下界 / 必填 / **未知字段拒绝**（``extra="forbid"``）。

与旧实现的差异:
    - 校验失败抛 ``ConfigError``（原为 ``SystemExit``），便于 Web 层转 422
    - 模型可导出 JSON Schema（``to_json_schema()``），供前端自动生成参数表单
    - ``sahi`` / ``direct`` 中原本"非必填"的少数字段在此带默认值（与 configs.yaml 取值一致），
      使模型可独立构造（测试 / 表单默认值）；其余字段一律必填，默认值只存在于 configs.yaml
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Preset = Literal["ultrafast", "superfast", "veryfast", "faster",
                 "fast", "medium", "slow", "slower", "veryslow"]
Quantize = Literal[None, 8, 16]


class _Strict(BaseModel):
    """所有配置模型共用: 禁止未知字段（拼错字段名立即报错，不静默失效）。"""

    model_config = ConfigDict(extra="forbid")


class SahiConfig(_Strict):
    """SAHI 切片检测参数。"""

    slice_size: int = Field(ge=32, description="切片边长")
    overlap_ratio: float = Field(ge=0.0, le=0.95, description="切片重叠率（0.15-0.25 推荐）")
    conf: float = Field(ge=0.0, le=1.0, description="检测置信度阈值")
    iou: float = Field(ge=0.0, le=1.0, description="融合 IoU 阈值")
    batch: int = Field(ge=1, description="切片批大小")
    device: int | str = Field(description="推理设备（0/1/cpu）")
    quantize: Quantize = Field(default=None, description="精度量化: null=FP32 | 16=FP16 | 8=INT8")
    fusion: Literal["wbf", "nms"] = Field(default="wbf", description="融合方式")
    min_coverage: float = Field(default=0.5, ge=0.0, le=1.0, description="边缘切片最小保留比例")
    multi_scale: bool = Field(default=False, description="多尺度切片（更准更慢）")
    scale_sizes: list[int] = Field(default=[640, 960, 1280], description="多尺度切片尺寸列表")


class DirectConfig(_Strict):
    """整帧直推检测参数。"""

    imgsz: int = Field(ge=32, description="推理输入边长")
    conf: float = Field(ge=0.0, le=1.0, description="检测置信度阈值")
    iou: float = Field(ge=0.0, le=1.0, description="NMS IoU 阈值")
    device: int | str = Field(description="推理设备（0/1/cpu）")
    quantize: Quantize = Field(default=None, description="精度量化: null=FP32 | 16=FP16 | 8=INT8")
    max_det: int = Field(default=300, ge=1, description="单帧最大检测数")
    batch: int = Field(ge=1, description="帧批大小（1=逐帧）")


class DrawConfig(_Strict):
    """视频绘制参数（文字一律 ASCII —— cv2.putText 不支持中文）。"""

    box: bool = Field(description="画检测框")
    track_id: bool = Field(description="画 track ID")
    score: bool = Field(description="画置信度")
    trail: bool = Field(description="画轨迹尾迹")
    panel: bool = Field(description="左上角计数面板")
    roi_outline: bool = Field(description="画草地四边形轮廓（调试用）")
    trail_len: int = Field(ge=1, description="尾迹保留点数")
    thickness: int = Field(ge=1, description="线宽")
    font_scale: float = Field(ge=0.1, description="字号比例")
    box_color: list[int] = Field(description="检测框颜色（BGR）")
    trail_color: list[int] = Field(description="尾迹颜色（BGR）")
    roi_color: list[int] = Field(description="ROI 轮廓颜色（BGR）")
    text_color: list[int] = Field(description="文字颜色（BGR）")


class EncodeConfig(_Strict):
    """输出视频编码（OpenCV 写 mp4v → ffmpeg 转 H.264）。"""

    h264: bool = Field(description="是否转码成 H.264")
    ffmpeg: str = Field(description="ffmpeg 可执行文件路径；留空 = 自动探测")
    crf: int = Field(ge=0, le=51, description="H.264 质量（越小越清晰）")
    preset: Preset = Field(description="x264 预设（越慢压得越小）")


class MaskConfig(_Strict):
    """草地四边形 ROI 遮罩参数。"""

    enabled: bool = Field(description="总开关")
    mode: Literal["auto", "manual"] = Field(description="auto=自动绿色分割 | manual=手填坐标")
    quad: list[list[int]] = Field(description="manual 模式: 4 个像素坐标点（TL→TR→BR→BL）")
    refresh_every: int = Field(ge=0, description="每 N 帧重拟合（1=逐帧；0=首帧拟合后固定）")
    max_area_jump: float = Field(ge=0.0, description="面积突变守卫阈值（0=关闭）")
    expand_ratio: float = Field(ge=0.0, description="四边形外扩比例")
    fill: int = Field(ge=0, le=255, description="区域外填充值")
    filter_outside: bool = Field(description="丢弃中心点在四边形外的检测框")
    detect_scale: float = Field(ge=0.0, le=1.0, description="分割降采样比例")
    hsv_lower: list[int] = Field(description="绿色 HSV 下界")
    hsv_upper: list[int] = Field(description="绿色 HSV 上界")
    morph_kernel: int = Field(ge=1, description="形态学核尺寸")
    min_area_ratio: float = Field(ge=0.0, le=1.0, description="绿色区域占比下限")
    max_area_ratio: float = Field(ge=0.0, le=1.0, description="绿色区域占比上限")
    approx_eps_ratio: float = Field(ge=0.0, description="approxPolyDP 精度系数")


class TrackerConfig(_Strict):
    """跨帧关联与轨迹后处理参数。"""

    high_thresh: float = Field(ge=0.0, le=1.0, description="高分框阈值（进第一轮匹配）")
    low_thresh: float = Field(ge=0.0, le=1.0, description="低分框阈值（进第二轮救回）")
    new_track_thresh: float = Field(ge=0.0, le=1.0, description="新建轨迹的最低置信度")
    match_thresh: float = Field(ge=0.0, le=1.0, description="第一轮匹配阈值")
    second_match_thresh: float = Field(ge=0.0, le=1.0, description="第二轮匹配阈值")
    boot_match_iou: float = Field(ge=0.0, le=1.0, description="起步期放宽阈值")
    match_dist_gate: float = Field(ge=0.0, description="距离门控系数")
    track_buffer: int = Field(ge=0, description="轨迹丢失保留帧数（须 < merge_gap_frames）")
    min_track_frames: int = Field(ge=0, description="短轨迹过滤阈值")
    merge_gap_frames: int = Field(ge=0, description="最大关联间隔（帧）")
    merge_dist_threshold: float = Field(ge=0.0, description="关联距离上限（px）")
    merge_speed_max: float = Field(ge=0.0, description="关联速度上限（px/帧）")
    spatial_overlap: float = Field(ge=0.0, le=1.0, description="空间去重 IoU 阈值")
    confirm_enabled: bool = Field(description="稳定确认门控总开关")
    confirm_window: int = Field(ge=0, description="观察窗口帧数（0=不启用窗口门控）")
    confirm_min_hits: int = Field(ge=0, description="窗口内最少命中帧数")


class SnapshotConfig(_Strict):
    """检出帧快照参数。"""

    enabled: bool = Field(description="总开关")
    mode: Literal["frame", "track"] = Field(
        description="frame=每个有虫帧一张 | track=每只虫一张代表图（取该虫置信度最高的帧）")
    dir_name: str = Field(description="输出子目录")
    prefix: str = Field(description="文件名前缀")
    fmt: Literal["jpg", "png"] = Field(description="图片格式")
    quality: int = Field(ge=1, le=100, description="JPEG 质量（png 忽略）")
    min_score: float = Field(ge=0.0, le=1.0, description="保存该帧/该虫的最低轨迹置信度")


class PipelineConfig(_Strict):
    """部署配置根模型（对应项目根 configs.yaml）。"""

    # ---- 表单字段（工作流输入）----
    model_path: str = Field(description="检测模型路径；留空=取最新登记权重；也接受 pest1")
    mode: Literal["sahi", "direct"] = Field(description="检测模式")
    output_root: str = Field(description="输出根目录（相对项目根）")

    # ---- 输出 ----
    save_json: bool = Field(description="是否写暂存数据 JSON")
    video_name: str = Field(description="推理视频文件名")
    json_name: str = Field(description="结果 JSON 文件名")
    save_track_path: bool = Field(description="JSON 是否带逐帧中心点（UI 画轨迹用）")
    progress_every: int = Field(ge=1, description="每处理多少帧刷新一次进度")

    # ---- 采样 ----
    frame_stride: int = Field(ge=1, description="抽帧步长（1=逐帧）")
    max_frames: int = Field(ge=0, description="最多处理帧数（0=全部）")

    # ---- 各功能节 ----
    sahi: SahiConfig
    direct: DirectConfig
    draw: DrawConfig
    encode: EncodeConfig
    mask: MaskConfig
    tracker: TrackerConfig
    snapshots: SnapshotConfig