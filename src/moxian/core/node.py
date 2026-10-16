"""对象树。

坐标系：画面宽 FRAME_WIDTH、高 FRAME_HEIGHT 个单位，原点在中心，y 向上（和数学习惯一致）。
每个节点有自己的局部变换；路径坐标写在节点的局部坐标系里，渲染时沿树累乘。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

from ..path.path import Path
from . import transform as T
from .style import Style

FRAME_HEIGHT = 8.0
FRAME_WIDTH = 8.0 * 16 / 9
PX = FRAME_HEIGHT / 1080  # 1080p 下 1 像素对应的单位长度

UP = np.array([0.0, 1.0])
DOWN = np.array([0.0, -1.0])
LEFT = np.array([-1.0, 0.0])
RIGHT = np.array([1.0, 0.0])
ORIGIN = np.array([0.0, 0.0])


@dataclass
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self) -> np.ndarray:
        return np.array([(self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2])

    def point(self, direction: np.ndarray) -> np.ndarray:
        """direction 各分量取 -1 / 0 / 1：边缘或中心。"""
        c = self.center
        return np.array([c[0] + direction[0] * self.width / 2, c[1] + direction[1] * self.height / 2])

    def union(self, other: "BBox | None") -> "BBox":
        if other is None:
            return self
        return BBox(min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1))

    def overlaps(self, other: "BBox", tolerance: float = 0.0) -> bool:
        return (
            min(self.x1, other.x1) - max(self.x0, other.x0) > tolerance
            and min(self.y1, other.y1) - max(self.y0, other.y0) > tolerance
        )


@dataclass
class Node:
    name: str = ""
    children: list["Node"] = field(default_factory=list)
    matrix: np.ndarray = field(default_factory=T.identity)
    style: Style | None = None  # None 表示继承父节点
    z: float = 0.0  # 同级绘制顺序：小的先画

    # ---- 树 ----
    def add(self, *nodes: "Node") -> "Node":
        self.children.extend(nodes)
        return self

    def walk(self, parent_matrix: np.ndarray | None = None, parent_style: Style | None = None) -> Iterator[tuple["Node", np.ndarray, Style]]:
        """深度优先，产出 (节点, 世界矩阵, 生效样式)。"""
        m = self.matrix if parent_matrix is None else parent_matrix @ self.matrix
        style = self.style or parent_style or Style()
        if self.style is not None and parent_style is not None and self.style.opacity != 1.0:
            style = style
        yield self, m, style
        for child in sorted(self.children, key=lambda n: n.z):
            yield from child.walk(m, style)

    # ---- 几何 ----
    def local_bbox(self) -> BBox | None:
        """只看自己的几何，不含子节点，在自己的局部坐标系里。叶子类型覆盖它。"""
        return None

    def bbox(self, parent_matrix: np.ndarray | None = None) -> BBox | None:
        """含子节点，在 parent_matrix 所在坐标系里（默认世界坐标）。"""
        m = self.matrix if parent_matrix is None else parent_matrix @ self.matrix
        box = None
        own = self.local_bbox()
        if own is not None:
            pts = T.apply(m, np.array([[own.x0, own.y0], [own.x1, own.y0], [own.x1, own.y1], [own.x0, own.y1]]))
            box = BBox(pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
        for child in self.children:
            cb = child.bbox(m)
            if cb is not None:
                box = cb if box is None else box.union(cb)
        return box

    @property
    def width(self) -> float:
        b = self.bbox()
        return 0.0 if b is None else b.width

    @property
    def height(self) -> float:
        b = self.bbox()
        return 0.0 if b is None else b.height

    def center(self) -> np.ndarray:
        b = self.bbox()
        return ORIGIN.copy() if b is None else b.center

    def edge(self, direction: np.ndarray) -> np.ndarray:
        b = self.bbox()
        return ORIGIN.copy() if b is None else b.point(direction)

    # ---- 摆放（都是改 self.matrix，不碰路径数据）----
    def apply(self, m: np.ndarray) -> "Node":
        self.matrix = m @ self.matrix
        return self

    def shift(self, delta) -> "Node":
        return self.apply(T.translate(float(delta[0]), float(delta[1])))

    def move_to(self, point) -> "Node":
        return self.shift(np.asarray(point, dtype=float) - self.center())

    def scale(self, factor: float, about=None) -> "Node":
        about = self.center() if about is None else np.asarray(about, dtype=float)
        return self.apply(T.scale(factor, factor, (float(about[0]), float(about[1]))))

    def scale_to_fit_width(self, width: float) -> "Node":
        return self.scale(width / self.width) if self.width > 0 else self

    def scale_to_fit_height(self, height: float) -> "Node":
        return self.scale(height / self.height) if self.height > 0 else self

    def rotate(self, radians: float, about=None) -> "Node":
        about = self.center() if about is None else np.asarray(about, dtype=float)
        return self.apply(T.rotate(radians, (float(about[0]), float(about[1]))))

    def next_to(self, other: "Node | np.ndarray", direction: np.ndarray, gap: float = 0.25) -> "Node":
        anchor = other.edge(direction) if isinstance(other, Node) else np.asarray(other, dtype=float)
        mine = self.edge(-direction)
        return self.shift(anchor + direction * gap - mine)

    def align_to(self, other: "Node", direction: np.ndarray) -> "Node":
        """让自己在 direction 方向的边和 other 的对齐（例如 DOWN：底边对齐）。"""
        target = other.edge(direction)
        mine = self.edge(direction)
        delta = (target - mine) * np.abs(direction)
        return self.shift(delta)

    def to_edge(self, direction: np.ndarray, margin: float = 0.3) -> "Node":
        frame = BBox(-FRAME_WIDTH / 2 + margin, -FRAME_HEIGHT / 2 + margin, FRAME_WIDTH / 2 - margin, FRAME_HEIGHT / 2 - margin)
        delta = (frame.point(direction) - self.edge(direction)) * np.abs(direction)
        return self.shift(delta)

    def set_style(self, **changes) -> "Node":
        self.style = (self.style or Style()).with_(**changes)
        return self


@dataclass
class PathNode(Node):
    path: Path = field(default_factory=Path)

    def local_bbox(self) -> BBox | None:
        b = self.path.bbox()
        return None if b is None else BBox(*b)


class Group(Node):
    def __init__(self, *children: Node, name: str = ""):
        super().__init__(name=name, children=list(children))

    def __iter__(self):
        return iter(self.children)

    def __getitem__(self, i):
        return self.children[i]

    def __len__(self):
        return len(self.children)


def arrange(nodes: list[Node], direction: np.ndarray, gap: float = 0.25, align: np.ndarray | None = None) -> None:
    """把一组节点沿 direction 依次排开；align 给出对齐的边（例如 LEFT）。"""
    for prev, node in zip(nodes, nodes[1:]):
        node.next_to(prev, direction, gap)
    if align is not None and nodes:
        for node in nodes[1:]:
            node.align_to(nodes[0], align)
