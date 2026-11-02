"""core — 纯领域逻辑层。

约束（见 docs/PLAN_web_mvp.md 2.2 节）:
    - 不 import api / services / jobs
    - 不读全局配置单例（配置一律由调用方注入）
    - 不 print、不 sys.exit（进度用回调上报，告警走 logging）

模块:
    detector    检测器构建（SAHI 切片 / 整帧直推）
    pipeline    端到端视频工作流
    tracker     IoU 关联 + 轨迹后处理三步清洗
    roi         草地四边形 ROI 遮罩
    sahi        SAHI 切片推理引擎 + WBF/NMS 融合
    render      第二遍重绘 + 视频写出 + ffmpeg 转 H.264
    snapshots   检出帧快照
"""

from pestdet.core.errors import JobCancelled, PestDetectorError

__all__ = ["JobCancelled", "PestDetectorError"]