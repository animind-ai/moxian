"""镜头：整幅画面的放大与平移。

镜头不改对象树，只在渲染时多乘一个矩阵：世界坐标 → 镜头坐标（还是单位坐标，原点在画面中心）。
center 是画面中心对准的世界坐标点，zoom 是放大倍数（1 = 原样，绝对值，不累乘）。
节点设 fixed=True 就不跟镜头走（钉住的题卡、底部胶囊），连同它的子节点。
节点设 keep_size=True 就跟着镜头移动、但画面上大小不变（曲线上的点放大 60 倍后仍是个小圆点）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import transform as T
from .node import FRAME_HEIGHT, FRAME_WIDTH, BBox


@dataclass
class Camera:
    center: np.ndarray = field(default_factory=lambda: np.zeros(2))
    zoom: float = 1.0

    @property
    def matrix(self) -> np.ndarray:
        cx, cy = float(self.center[0]), float(self.center[1])
        return T.scale(self.zoom) @ T.translate(-cx, -cy)

    def is_identity(self) -> bool:
        return self.zoom == 1.0 and not np.any(self.center)

    def view_box(self) -> BBox:
        """镜头当前看到的世界范围。"""
        w, h = FRAME_WIDTH / 2 / self.zoom, FRAME_HEIGHT / 2 / self.zoom
        cx, cy = float(self.center[0]), float(self.center[1])
        return BBox(cx - w, cy - h, cx + w, cy + h)

    def to_screen(self, points) -> np.ndarray:
        """世界坐标 → 画面上的单位坐标（形状 (n, 2)）。"""
        return T.apply(self.matrix, np.asarray(points, dtype=float).reshape(-1, 2))


def fit(box: BBox, margin: float = 0.5) -> tuple[np.ndarray, float]:
    """让 box（四周各留 margin，单位是画面上的长度）刚好填满画面的 (center, zoom)。"""
    w = max(box.width, 1e-6)
    h = max(box.height, 1e-6)
    zoom = min((FRAME_WIDTH - 2 * margin) / w, (FRAME_HEIGHT - 2 * margin) / h)
    return box.center, max(zoom, 1e-6)
