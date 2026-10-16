"""二维仿射变换：3×3 矩阵，作用在齐次坐标 (x, y, 1) 上。"""

from __future__ import annotations

import math

import numpy as np

Matrix = np.ndarray


def identity() -> Matrix:
    return np.eye(3)


def translate(dx: float, dy: float) -> Matrix:
    m = np.eye(3)
    m[0, 2], m[1, 2] = dx, dy
    return m


def scale(sx: float, sy: float | None = None, about: tuple[float, float] | None = None) -> Matrix:
    sy = sx if sy is None else sy
    m = np.diag([sx, sy, 1.0])
    if about is not None:
        ax, ay = about
        return translate(ax, ay) @ m @ translate(-ax, -ay)
    return m


def rotate(radians: float, about: tuple[float, float] | None = None) -> Matrix:
    c, s = math.cos(radians), math.sin(radians)
    m = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    if about is not None:
        ax, ay = about
        return translate(ax, ay) @ m @ translate(-ax, -ay)
    return m


def from_svg(a: float, b: float, c: float, d: float, e: float, f: float) -> Matrix:
    """SVG 的 matrix(a b c d e f)。"""
    return np.array([[a, c, e], [b, d, f], [0.0, 0.0, 1.0]])


def apply(m: Matrix, points: np.ndarray) -> np.ndarray:
    """points 形状 (n, 2)。"""
    if len(points) == 0:
        return points
    ones = np.ones((len(points), 1))
    out = (m @ np.hstack([points, ones]).T).T
    return out[:, :2]
