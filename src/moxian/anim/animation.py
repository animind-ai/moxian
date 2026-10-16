"""动画原语。

每个动画作用在一个节点上，有时长和缓动；时间线在 [开始, 开始 + 时长] 内反复调用
interpolate(alpha)，alpha 已经过缓动。begin() 记下起始状态，finish() 落到最终状态。
动画只改节点的 matrix、style 和（变形时的）path，不增删树节点；增删由调用方在合适的时刻做。
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from ..core import Node, PathNode, Style, transform as T
from ..core.style import parse_color
from ..path import Path, align, lerp, partial
from . import easing

Easing = Callable[[float], float]


class Animation:
    def __init__(self, node: Node, duration: float = 0.6, ease: Easing = easing.smooth):
        self.node = node
        self.duration = max(1e-6, duration)
        self.ease = ease
        self.begun = False

    def begin(self) -> None:
        self.begun = True

    def interpolate(self, alpha: float) -> None:
        raise NotImplementedError

    def finish(self) -> None:
        self.interpolate(1.0)


class Wait(Animation):
    def __init__(self, duration: float = 1.0):
        super().__init__(Node(), duration)

    def interpolate(self, alpha: float) -> None:
        pass


# ---------- 透明度 ----------

class Fade(Animation):
    def __init__(self, node: Node, start: float, end: float, duration: float = 0.6, shift=None, ease: Easing = easing.smooth):
        super().__init__(node, duration, ease)
        self.start, self.end = start, end
        self.shift_vec = None if shift is None else np.asarray(shift, dtype=float)

    def begin(self) -> None:
        super().begin()
        self.base = self.node.matrix.copy()

    def interpolate(self, alpha: float) -> None:
        self.node.set_style(opacity=self.start + (self.end - self.start) * alpha)
        if self.shift_vec is not None:
            d = self.shift_vec * (1 - alpha) if self.end > self.start else self.shift_vec * alpha
            self.node.matrix = T.translate(float(d[0]), float(d[1])) @ self.base


def fade_in(node: Node, duration: float = 0.6, shift=None) -> Fade:
    """shift 给出入场前的偏移（例如 (0, -0.1)：从下方 0.1 处滑入）。"""
    return Fade(node, 0.0, 1.0, duration, shift=None if shift is None else -np.asarray(shift, dtype=float))


def fade_out(node: Node, duration: float = 0.4, shift=None) -> Fade:
    return Fade(node, 1.0, 0.0, duration, shift=shift)


# ---------- 变换 ----------

class Shift(Animation):
    def __init__(self, node: Node, delta, duration: float = 0.8, ease: Easing = easing.smooth):
        super().__init__(node, duration, ease)
        self.delta = np.asarray(delta, dtype=float)

    def begin(self) -> None:
        super().begin()
        self.base = self.node.matrix.copy()

    def interpolate(self, alpha: float) -> None:
        d = self.delta * alpha
        self.node.matrix = T.translate(float(d[0]), float(d[1])) @ self.base


class MoveTo(Shift):
    def __init__(self, node: Node, point, duration: float = 0.8, ease: Easing = easing.smooth):
        super().__init__(node, [0.0, 0.0], duration, ease)
        self.point = np.asarray(point, dtype=float)

    def begin(self) -> None:
        self.delta = self.point - self.node.center()
        super().begin()


class Scale(Animation):
    def __init__(self, node: Node, factor: float, duration: float = 0.6, about=None, ease: Easing = easing.smooth):
        super().__init__(node, duration, ease)
        self.factor, self.about = factor, about

    def begin(self) -> None:
        super().begin()
        self.base = self.node.matrix.copy()
        c = self.node.center() if self.about is None else np.asarray(self.about, dtype=float)
        self.center = (float(c[0]), float(c[1]))

    def interpolate(self, alpha: float) -> None:
        f = 1 + (self.factor - 1) * alpha
        self.node.matrix = T.scale(f, f, self.center) @ self.base


class Grow(Animation):
    """从中心长出来：缩放 0 → 1 并淡入。"""

    def __init__(self, node: Node, duration: float = 0.5, ease: Easing = easing.smooth):
        super().__init__(node, duration, ease)

    def begin(self) -> None:
        super().begin()
        self.base = self.node.matrix.copy()
        c = self.node.center()
        self.center = (float(c[0]), float(c[1]))

    def interpolate(self, alpha: float) -> None:
        f = max(1e-3, alpha)
        self.node.matrix = T.scale(f, f, self.center) @ self.base
        self.node.set_style(opacity=alpha)


# ---------- 样式 ----------

def _lerp_color(a: str, b: str, t: float) -> str:
    ca, cb = parse_color(a), parse_color(b)
    return "#" + "".join(f"{round((x + (y - x) * t) * 255):02X}" for x, y in zip(ca, cb))


class Restyle(Animation):
    """把节点样式渐变到目标值（颜色按 RGB 插值，数值线性插值）。"""

    def __init__(self, node: Node, duration: float = 0.4, ease: Easing = easing.smooth, **target):
        super().__init__(node, duration, ease)
        self.target = target

    def begin(self) -> None:
        super().begin()
        self.base = self.node.style or Style()

    def interpolate(self, alpha: float) -> None:
        changes = {}
        for key, end in self.target.items():
            start = getattr(self.base, key)
            if isinstance(end, str):
                changes[key] = _lerp_color(start, end, alpha) if isinstance(start, str) else end
            elif start is None:
                changes[key] = end
            else:
                changes[key] = start + (end - start) * alpha
        self.node.style = self.base.with_(**changes)


# ---------- 路径 ----------

class Draw(Animation):
    """沿路径画出来（划线、描边出现）。"""

    def __init__(self, node: PathNode, duration: float = 0.5, ease: Easing = easing.smooth):
        super().__init__(node, duration, ease)

    def begin(self) -> None:
        super().begin()
        self.full = self.node.path.copy()
        self.node.set_style(opacity=1.0)

    def interpolate(self, alpha: float) -> None:
        self.node.path = partial(self.full, alpha)

    def finish(self) -> None:
        self.node.path = self.full


class Morph(Animation):
    """把一个路径节点变形成另一个的形状（和颜色）。

    两个节点需要在同一个父节点下（矩阵可比）。结束时 node 的几何就是 target 的几何。
    """

    def __init__(self, node: PathNode, target: PathNode, duration: float = 1.0, ease: Easing = easing.smooth):
        super().__init__(node, duration, ease)
        self.target = target

    def begin(self) -> None:
        super().begin()
        into_local = np.linalg.inv(self.node.matrix) @ self.target.matrix
        target_path = self.target.path.transformed(into_local)
        self.src, self.dst = align(self.node.path, target_path)
        self.src_style = self.node.style or Style()
        self.dst_style = self.target.style or self.src_style

    def interpolate(self, alpha: float) -> None:
        self.node.path = lerp(self.src, self.dst, alpha)
        if self.src_style.fill and self.dst_style.fill:
            self.node.style = self.src_style.with_(fill=_lerp_color(self.src_style.fill, self.dst_style.fill, alpha))


class Group_(Animation):
    """同时播放多个动画（时长取最长，各自按自己的缓动）。"""

    def __init__(self, *anims: Animation):
        super().__init__(Node(), max(a.duration for a in anims) if anims else 0.1, easing.linear)
        self.anims = list(anims)

    def begin(self) -> None:
        super().begin()
        for a in self.anims:
            a.begin()

    def interpolate(self, alpha: float) -> None:
        for a in self.anims:
            local = min(1.0, alpha * self.duration / a.duration)
            a.interpolate(a.ease(local))

    def finish(self) -> None:
        for a in self.anims:
            a.finish()


together = Group_
