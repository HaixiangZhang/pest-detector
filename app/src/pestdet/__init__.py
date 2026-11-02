"""pestdet — 4K 航拍视频害虫检测与跨帧去重计数。

分层（依赖单向，见 docs/PLAN_web_mvp.md 第 2.2 节）:

    api / cli  →  services  →  jobs  →  core
                     ↓          ↓
                  config      infra

- ``core``   纯领域逻辑: 检测 / 关联 / 计数 / 遮罩 / 绘制（无 I/O 副作用、无全局配置）
- ``config`` 配置模型与加载（Pydantic，无导入期副作用）
- ``infra``  基础设施: 路径 / 图片读写 / 权重登记 / 日志
- ``cli``    命令行入口
"""

__version__ = "0.1.0"