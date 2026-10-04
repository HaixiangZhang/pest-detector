"""utils — 部署运行时支撑包（供项目根 pipeline.py 的视频检测工作流复用）。

模块构成:
    paths      路径常量 / 时间戳
    imageio    图片读取（兼容非 ASCII 路径）
    config     部署配置（configs.yaml）加载 + 字段级校验 → PIPELINE_CONFIG
    tracker    跨帧 IoU 关联 + 轨迹后处理三步清洗
    sahi       SAHI 切片推理 + WBF/NMS 融合
    roi        草地四边形 ROI 遮罩
    render     第二遍重绘（最终 ID 标注帧）+ 视频写出
    snapshots  检出帧快照
    registry   权重登记（pest{N} 版本链，runs/registry.json）

约定: 各模块顶层保持轻量，ultralytics 一律惰性导入。
"""