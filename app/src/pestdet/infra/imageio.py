"""imageio — 图片读取（兼容非 ASCII 路径）。

Windows 下 cv2.imread 遇到中文/非 ASCII 路径会静默返回 None，
统一改用 np.fromfile + cv2.imdecode，并把失败原因显式抛出。

用法:
    from pestdet.infra.imageio import imread
    img = imread("D:/数据/航拍/0001.jpg")
"""

import os

import cv2
import numpy as np


def imread(path: str) -> np.ndarray:
    """读取图片为 BGR 数组；文件不存在或无法解码时抛出明确错误。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"图片不存在: {path}")
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法解码图片（不是有效图片或格式不支持）: {path}")
    return img