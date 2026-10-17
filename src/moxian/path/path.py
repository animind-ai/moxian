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
    def move_to(self, x: float, y: float) -> Path:
        self.subpaths.append(Subpath(np.array([x, y], dtype=float)))
        return self

    def _current(self) -> Subpath:
        if not self.subpaths:
            self.move_to(0.0, 0.0)
        return self.subpaths[-1]

    def line_to(self, x: float, y: float) -> Path:
        sp = self._current()
        p0, p3 = sp.end(), np.array([x, y], dtype=float)
        sp.segments.append(np.array([p0 + (p3 - p0) / 3, p0 + 2 * (p3 - p0) / 3, p3]))
        return self

    def quad_to(self, cx: float, cy: float, x: float, y: float) -> Path:
        sp = self._current()
        p0, c, p3 = sp.end(), np.array([cx, cy], dtype=float), np.array([x, y], dtype=float)
        sp.segments.append(np.array([p0 + 2 / 3 * (c - p0), p3 + 2 / 3 * (c - p3), p3]))
        return self

    def cubic_to(self, c1x: float, c1y: float, c2x: float, c2y: float, x: float, y: float) -> Path:
        self._current().segments.append(np.array([[c1x, c1y], [c2x, c2y], [x, y]], dtype=float))
        return self

    def close(self) -> Path:
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

    def bbox(self, matrix: np.ndarray | None = None) -> tuple[float, float, float, float] | None:
        """曲线本身的精确包围盒（不是控制点的）；给了 matrix 就先变换再求，旋转后也不会变大。

        每段三次贝塞尔的极值在导数 a t² + b t + c 的根上，和端点一起取范围。
        """
        segs = [(sp.start if i == 0 else sp.segments[i - 1][2], *seg)
                for sp in self.subpaths for i, seg in enumerate(sp.segments)]
        if not segs:
            return None
        p = np.array(segs, dtype=float)  # (n, 4, 2)
        if matrix is not None:
            from ..core import transform as T

            p = T.apply(matrix, p.reshape(-1, 2)).reshape(p.shape)
        p0, p1, p2, p3 = p[:, 0], p[:, 1], p[:, 2], p[:, 3]
        a = -p0 + 3 * p1 - 3 * p2 + p3
        b = 2 * (p0 - 2 * p1 + p2)
        c = p1 - p0
        # 每段每个坐标最多两个根；不落在 (0, 1) 的记成 nan
        with np.errstate(divide="ignore", invalid="ignore"):
            disc = np.sqrt(np.maximum(b * b - 4 * a * c, 0.0))
            quad = np.abs(a) > 1e-12
            r1 = np.where(quad, (-b + disc) / (2 * a), -c / b)
            r2 = np.where(quad, (-b - disc) / (2 * a), np.nan)
            ts = np.stack([r1, r2], axis=1)  # (n, 2 根, 2 坐标)
        ts = np.where((ts > 0) & (ts < 1), ts, np.nan)
        u = 1 - ts
        coords = [p[:, None, 0], p[:, None, 3]]  # 端点
        for k in range(2):  # 第 k 个坐标在它自己的根上取值
            t, s = ts[..., k], u[..., k]
            coords.append(s**3 * p0[:, None, k] + 3 * s * s * t * p1[:, None, k]
                          + 3 * s * t * t * p2[:, None, k] + t**3 * p3[:, None, k])
        ends = np.concatenate(coords[:2], axis=1)  # (n, 2, 2)
        xs = np.concatenate([ends[..., 0].ravel(), coords[2].ravel()])
        ys = np.concatenate([ends[..., 1].ravel(), coords[3].ravel()])
        return float(np.nanmin(xs)), float(np.nanmin(ys)), float(np.nanmax(xs)), float(np.nanmax(ys))

    # ---- 变换 ----
    def transformed(self, m: np.ndarray) -> Path:
        from ..core import transform as T

        out = Path()
        for sp in self.subpaths:
            new = Subpath(T.apply(m, sp.start.reshape(1, 2))[0], closed=sp.closed)
            new.segments = [T.apply(m, seg) for seg in sp.segments]
            out.subpaths.append(new)
        return out

    def copy(self) -> Path:
        return self.transformed(np.eye(3))

    def extend(self, other: Path) -> Path:
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
