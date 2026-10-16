"""镜头动画：放大、平移、复位。

放大倍数按对数插值（几何插值）：从 1 倍到 100 倍，每一帧放大的比例相同，看起来匀速推进；
线性插值会在开头一下子冲过去、到后面几乎不动。

中心点也不能线性插值：镜头放大时，中心离终点的一点残差会被放大很多倍，画面末尾会"甩"一下。
这里让终点（放大时）或起点（缩小时）在画面上的位置线性移动，两种情况都平稳。
"""

from __future__ import annotations

import numpy as np

from ..core import BBox, Node
from ..core.camera import Camera, fit
from . import easing
from .animation import Animation, Easing


class CameraMove(Animation):
    """把镜头移到 center、放大到 zoom（都可以不给：保持原值）。"""

    def __init__(self, camera: Camera, center=None, zoom: float | None = None, duration: float = 1.5,
                 ease: Easing = easing.smooth):
        super().__init__(Node(name="camera"), duration, ease)
        if zoom is not None and zoom <= 0:
            raise ValueError(f"zoom 必须大于 0，收到 {zoom}")
        self.camera = camera
        self.target_center = None if center is None else np.asarray(center, dtype=float)
        self.target_zoom = zoom

    def begin(self) -> None:
        super().begin()
        self.c0 = np.asarray(self.camera.center, dtype=float).copy()
        self.z0 = float(self.camera.zoom)
        self.c1 = self.c0.copy() if self.target_center is None else self.target_center.copy()
        self.z1 = self.z0 if self.target_zoom is None else float(self.target_zoom)

    def interpolate(self, alpha: float) -> None:
        z = self.z0 * (self.z1 / self.z0) ** alpha
        if self.z1 >= self.z0:
            # 放大：终点 c1 在画面上的位置从 (c1 - c0)·z0 线性移到画面中心
            c = self.c1 - (1 - alpha) * (self.c1 - self.c0) * self.z0 / z
        else:
            # 缩小：起点 c0 在画面上的位置从中心线性移到 (c0 - c1)·z1
            c = self.c0 - alpha * (self.c0 - self.c1) * self.z1 / z
        self.camera.center = c
        self.camera.zoom = z

    def finish(self) -> None:
        self.camera.center = self.c1.copy()
        self.camera.zoom = self.z1


def focus_on(camera: Camera, box: BBox, margin: float = 0.5, zoom: float | None = None,
             duration: float = 1.5, ease: Easing = easing.smooth) -> CameraMove:
    """对准 box：给了 zoom 就按这个倍数放大到 box 中心，否则放大到 box（留 margin）刚好填满画面。"""
    center, fitted = fit(box, margin)
    return CameraMove(camera, center, fitted if zoom is None else zoom, duration, ease)


def reset(camera: Camera, duration: float = 1.5, ease: Easing = easing.smooth) -> CameraMove:
    """回到原样：中心在原点，1 倍。"""
    return CameraMove(camera, np.zeros(2), 1.0, duration, ease)
