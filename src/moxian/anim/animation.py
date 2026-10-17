"""动画原语。

每个动画作用在一个节点上，有时长和缓动；时间线在 [开始, 开始 + 时长] 内反复调用
interpolate(alpha)，alpha 已经过缓动。begin() 记下起始状态，finish() 落到最终状态。
动画只改节点的 matrix、style 和（变形时的）path，不增删树节点；增删由调用方在合适的时刻做。
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..core import Group, Node, PathNode, Style
from ..core import transform as T
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

    def children(self) -> list[tuple[float, Animation]]:
        """组合动画的子动画和它们相对本动画开始的时刻；时间线靠它找到嵌套的参数补间。"""
        return []


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

    def children(self) -> list[tuple[float, Animation]]:
        return [(0.0, a) for a in self.anims]


together = Group_


# ---------- 书写与变形 ----------

def _leaves(node: Node, parent_matrix: np.ndarray | None = None) -> list[tuple[PathNode, np.ndarray, Style]]:
    """node 下所有路径叶子，连同它们的（相对 parent_matrix 所在坐标系的）矩阵和生效样式。"""
    return [(n, m, s) for n, m, s in node.walk(parent_matrix) if isinstance(n, PathNode) and not n.path.is_empty()]


class Write(Animation):
    """像手写一样出现：每个字形先沿轮廓描出来，再填色。字形按顺序错开开始（lag 越大越"一个接一个"）。"""

    DRAW = 0.6  # 每个字形前 60% 的时间描边，后 40% 填色

    def __init__(self, node: Node, duration: float = 1.0, lag: float = 0.6, stroke_width: float = 1.6,
                 ease: Easing = easing.linear):
        super().__init__(node, duration, ease)
        self.lag, self.stroke_width = lag, stroke_width

    def begin(self) -> None:
        super().begin()
        self.node.set_style(opacity=1.0)
        leaves = _leaves(self.node)
        self.items = []
        for leaf, _m, style in leaves:
            color = style.fill or style.stroke or "#000000"
            self.items.append((leaf, leaf.path, leaf.style, color, style.fill_opacity))
        self.interpolate(0.0)

    def interpolate(self, alpha: float) -> None:
        n = max(1, len(self.items))
        span = 1.0 - self.lag if n > 1 else 1.0
        for i, (leaf, full, _orig, color, fill_op) in enumerate(self.items):
            start = self.lag * i / max(1, n - 1) if n > 1 else 0.0
            local = min(1.0, max(0.0, (alpha - start) / span))
            if local < self.DRAW:
                leaf.path = partial(full, local / self.DRAW)
                leaf.style = Style(fill=color, fill_opacity=0.0, stroke=color, stroke_width=self.stroke_width)
            else:
                k = (local - self.DRAW) / (1 - self.DRAW)
                leaf.path = full
                leaf.style = Style(fill=color, fill_opacity=fill_op * k, stroke=color,
                                   stroke_width=self.stroke_width, stroke_opacity=1.0 - k)

    def finish(self) -> None:
        for leaf, full, orig, _c, _f in self.items:
            leaf.path, leaf.style = full, orig


class TransformCopy(Animation):
    """把一组源对象"复制一份"变形成目标：源保持不动，目标的每个字形从源里对应的字形变过来。

    字形按从左到右、从上到下的阅读顺序配对；数量不同时按比例对应（多出来的目标字形从最近的源字形长出来）。
    动画期间画的是一层临时覆盖（overlay），结束时去掉覆盖、显示真正的目标。overlay 必须挂在 root 下。
    """

    def __init__(self, sources: list[Node], target: Node, root: Node, duration: float = 1.0,
                 ease: Easing = easing.smooth):
        super().__init__(target, duration, ease)
        self.sources, self.root = sources, root

    def _world_leaves(self, node: Node):
        from ..core import parent_matrix_of

        return _leaves(node, parent_matrix_of(self.root, node))

    @staticmethod
    def _reading_order(items):
        """阅读顺序。单行公式只按 x 排（上标、下标不能被当成另一行）；多行时先按行聚类，再按 x。"""
        boxes = [item[0].path.transformed(item[1]).bbox() for item in items]
        if not boxes:
            return []
        heights = sorted(b[3] - b[1] for b in boxes)
        line = max(heights[len(heights) // 2] * 1.6, 0.25)  # 一行的高度：字形高度中位数的 1.6 倍
        top = max(b[3] for b in boxes)
        bottom = min(b[1] for b in boxes)
        single = top - bottom < 2 * line
        def key(pair):
            b = pair[1]
            cx = (b[0] + b[2]) / 2
            if single:
                return (0, cx)
            return (round((top - (b[1] + b[3]) / 2) / line), cx)
        return [item for item, _ in sorted(zip(items, boxes), key=key)]

    def begin(self) -> None:
        super().begin()
        src = self._reading_order([x for s in self.sources for x in self._world_leaves(s)])
        dst = self._reading_order(self._world_leaves(self.node))
        self.node.set_style(opacity=0.0)
        self.overlay = Group(name="transform-overlay")
        self.pairs = []
        for j, (leaf, m, style) in enumerate(dst):
            if src:
                i = round(j * (len(src) - 1) / max(1, len(dst) - 1)) if len(dst) > 1 else 0
                s_leaf, s_m, s_style = src[i]
                a, b = align(s_leaf.path.transformed(s_m), leaf.path.transformed(m))
                c0 = s_style.fill or "#000000"
            else:
                a, b = align(Path(), leaf.path.transformed(m))
                c0 = style.fill or "#000000"
            c1 = style.fill or c0
            shape = PathNode(path=a, style=Style(fill=c0))
            self.overlay.add(shape)
            self.pairs.append((shape, a, b, c0, c1))
        self.root.add(self.overlay)

    def interpolate(self, alpha: float) -> None:
        for shape, a, b, c0, c1 in self.pairs:
            shape.path = lerp(a, b, alpha)
            shape.style = Style(fill=_lerp_color(c0, c1, alpha))

    def finish(self) -> None:
        if self.overlay in self.root.children:
            self.root.children.remove(self.overlay)
        self.node.set_style(opacity=1.0)
