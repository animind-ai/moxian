"""矢量路径：若干子路径，每条子路径是一串三次贝塞尔段。

所有段都统一成三次（直线和二次曲线提升为三次），这样插值、变形、点数对齐只需处理一种段。
坐标是 (n, 2) 的 numpy 数组。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Subpath:
    start: np.ndarray  # (2,)
    segments: list[np.ndarray] = field(default_factory=list)  # 每段 (3, 2)：两个控制点 + 终点
    closed: bool = False

    def points(self) -> np.ndarray:
        """起点 + 每段的三个点，形状 (1 + 3n, 2)。"""
        if not self.segments:
            return self.start.reshape(1, 2)
        return np.vstack([self.start.reshape(1, 2), *self.segments])

    def end(self) -> np.ndarray:
        return self.segments[-1][2] if self.segments else self.start


@dataclass(eq=False)  # 按身份比较和哈希：渲染器按 Path 对象缓存 Skia 路径
class Path:
    subpaths: list[Subpath] = field(default_factory=list)

    # ---- 构造 ----
    def move_to(self, x: float, y: float) -> "Path":
        self.subpaths.append(Subpath(np.array([x, y], dtype=float)))
        return self

    def _current(self) -> Subpath:
        if not self.subpaths:
            self.move_to(0.0, 0.0)
        return self.subpaths[-1]

    def line_to(self, x: float, y: float) -> "Path":
        sp = self._current()
        p0, p3 = sp.end(), np.array([x, y], dtype=float)
        sp.segments.append(np.array([p0 + (p3 - p0) / 3, p0 + 2 * (p3 - p0) / 3, p3]))
        return self

    def quad_to(self, cx: float, cy: float, x: float, y: float) -> "Path":
        sp = self._current()
        p0, c, p3 = sp.end(), np.array([cx, cy], dtype=float), np.array([x, y], dtype=float)
        sp.segments.append(np.array([p0 + 2 / 3 * (c - p0), p3 + 2 / 3 * (c - p3), p3]))
        return self

    def cubic_to(self, c1x: float, c1y: float, c2x: float, c2y: float, x: float, y: float) -> "Path":
        self._current().segments.append(np.array([[c1x, c1y], [c2x, c2y], [x, y]], dtype=float))
        return self

    def close(self) -> "Path":
        sp = self._current()
        if sp.segments and not np.allclose(sp.end(), sp.start):
            self.line_to(*sp.start)
        sp.closed = True
        return self

    # ---- 查询 ----
    def is_empty(self) -> bool:
        return not any(sp.segments for sp in self.subpaths)

    def all_points(self) -> np.ndarray:
        pts = [sp.points() for sp in self.subpaths if sp.segments]
        return np.vstack(pts) if pts else np.zeros((0, 2))

    def bbox(self) -> tuple[float, float, float, float] | None:
        """用控制点的包围盒（略大于精确包围盒，渲染和布局够用）。"""
        pts = self.all_points()
        if len(pts) == 0:
            return None
        return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())

    # ---- 变换 ----
    def transformed(self, m: np.ndarray) -> "Path":
        from ..core import transform as T

        out = Path()
        for sp in self.subpaths:
            new = Subpath(T.apply(m, sp.start.reshape(1, 2))[0], closed=sp.closed)
            new.segments = [T.apply(m, seg) for seg in sp.segments]
            out.subpaths.append(new)
        return out

    def copy(self) -> "Path":
        return self.transformed(np.eye(3))

    def extend(self, other: "Path") -> "Path":
        self.subpaths.extend(sp for sp in other.copy().subpaths)
        return self


# ---- 常用形状（都以原点为中心）----

def rect(width: float, height: float) -> Path:
    w, h = width / 2, height / 2
    return Path().move_to(-w, -h).line_to(w, -h).line_to(w, h).line_to(-w, h).close()


_K = 4 / 3 * (math.sqrt(2) - 1)  # 四段三次贝塞尔拟合圆的控制点系数


def rounded_rect(width: float, height: float, radius: float) -> Path:
    r = min(radius, width / 2, height / 2)
    w, h, k = width / 2, height / 2, _K * min(radius, width / 2, height / 2)
    p = Path().move_to(-w + r, -h)
    p.line_to(w - r, -h).cubic_to(w - r + k, -h, w, -h + r - k, w, -h + r)
    p.line_to(w, h - r).cubic_to(w, h - r + k, w - r + k, h, w - r, h)
    p.line_to(-w + r, h).cubic_to(-w + r - k, h, -w, h - r + k, -w, h - r)
    p.line_to(-w, -h + r).cubic_to(-w, -h + r - k, -w + r - k, -h, -w + r, -h)
    return p.close()


def circle(radius: float) -> Path:
    r, k = radius, _K * radius
    p = Path().move_to(r, 0)
    p.cubic_to(r, k, k, r, 0, r).cubic_to(-k, r, -r, k, -r, 0)
    p.cubic_to(-r, -k, -k, -r, 0, -r).cubic_to(k, -r, r, -k, r, 0)
    return p.close()


def line(x0: float, y0: float, x1: float, y1: float) -> Path:
    return Path().move_to(x0, y0).line_to(x1, y1)


def polygon(points: list[tuple[float, float]]) -> Path:
    p = Path().move_to(*points[0])
    for x, y in points[1:]:
        p.line_to(x, y)
    return p.close()
