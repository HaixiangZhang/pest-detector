"""services 包 — 应用编排层（api / cli 与 core 之间的唯一粘合层）。"""

from pestdet.services.analyze import AnalyzeService

__all__ = ["AnalyzeService"]