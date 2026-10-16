"""镜头演示：把抛物线 y = x² 在 P(1, 1) 处放大 60 倍，曲线看起来变成直线（导数的直观），再缩回来。

上方的题卡和底部的胶囊设了 fixed，不跟镜头走；P 点设了 keep_size，放大后仍是小圆点。

运行：uv run python examples/zoom_demo.py  → build/zoom.mp4
"""

from __future__ import annotations

import numpy as np
from common import BG, CARD, DIM, FG, HL_INK, MARK, A, C, chips, pin_top

from moxian.anim import CameraMove, Draw, Restyle, Timeline, Wait, fade_in, reset
from moxian.core import DOWN, Camera, Group, PathNode, Style
from moxian.core import transform as T
from moxian.encode import render_video
from moxian.path import Path, circle, line, rounded_rect
from moxian.render import SkiaRenderer
from moxian.text import Text

S = 1.4  # 数学坐标 → 画面单位
ORIGIN_Y = -2.6  # 抛物线顶点在画面里的高度
ZOOM = 60.0


def parabola(x0: float, x1: float, pieces: int = 24) -> Path:
    """y = x² 的精确贝塞尔表示：每段二次贝塞尔的控制点是两端切线的交点 ((a+b)/2, ab)。"""
    xs = [x0 + (x1 - x0) * k / pieces for k in range(pieces + 1)]
    p = Path().move_to(xs[0], xs[0] ** 2)
    for a, b in zip(xs, xs[1:]):
        p.quad_to((a + b) / 2, a * b, b, b * b)
    return p


def to_stage(x: float, y: float) -> tuple[float, float]:
    return S * x, S * y + ORIGIN_Y


def build():
    graph = Group(name="graph")
    graph.matrix = T.translate(0.0, ORIGIN_Y) @ T.scale(S)  # 子节点写数学坐标
    axes = PathNode(path=line(-4.8, 0, 4.8, 0).extend(line(0, -0.3, 0, 4.6)), style=Style(stroke=DIM, stroke_width=2))
    curve = PathNode(path=parabola(-1.9, 1.9), style=Style(stroke=A, stroke_width=5, opacity=0.0))
    tangent = PathNode(path=line(0.3, -0.4, 1.8, 2.6), style=Style(stroke=HL_INK, stroke_width=2.5, opacity=0.0), z=-1)
    graph.add(axes, tangent, curve)

    # 点和字母放进一个组、组的局部原点就是 P：keep_size 绕 P 缩回去，字母始终贴在点旁边
    dot = PathNode(path=circle(0.09), style=Style(fill=C))
    label = Text("P", 30, C)
    label.next_to(dot, np.array([1.0, -0.6]), 0.1)
    marker = Group(dot, label, name="P").set_style(opacity=0.0)
    marker.shift(to_stage(1.0, 1.0))
    marker.keep_size = True

    text = Text("把 y = x² 在 P 点附近不断放大，曲线会变成什么样？", 34, FG)
    bg = PathNode(path=rounded_rect(text.width + 0.8, text.height + 0.5, 0.15), style=Style(fill=CARD))
    bg.move_to(text.center())
    card = pin_top(Group(bg, text), width=11.0, max_height=1.0)
    card.fixed = True

    steps = chips(["原样", f"放大 {ZOOM:.0f} 倍", "缩回来"])
    steps.node.to_edge(DOWN, margin=0.35).shift([-steps.node.center()[0], 0.0])
    steps.node.fixed = True
    root = Group(graph, marker, card, steps.node, name="root")
    return root, curve, tangent, marker, steps


def main():
    root, curve, tangent, marker, steps = build()
    cam = Camera()
    tl = Timeline()
    tl.add(0.0, Draw(curve, 1.2))
    tl.add(0.0, fade_in(curve, 0.2))
    tl.add(1.0, fade_in(marker, 0.4))
    bgs = steps.bgs
    bgs[0].set_style(fill=MARK)  # 当前步骤的胶囊垫淡色
    p = to_stage(1.0, 1.0)
    tl.add(1.8, CameraMove(cam, center=p, zoom=ZOOM, duration=3.2))
    tl.add(1.8, Restyle(bgs[0], 0.4, fill=CARD))
    tl.add(1.8, Restyle(bgs[1], 0.4, fill=MARK))
    tl.add(5.2, fade_in(tangent, 0.6))  # 切线叠上去：放大后几乎和曲线重合
    tl.add(5.8, Wait(1.0))
    tl.add(6.8, reset(cam, duration=2.6))
    tl.add(6.8, Restyle(bgs[1], 0.4, fill=CARD))
    tl.add(6.8, Restyle(bgs[2], 0.4, fill=MARK))
    renderer = SkiaRenderer(1280, 720, background=BG, camera=cam)
    render_video(root, tl, "build/zoom.mp4", renderer, fps=30, until=tl.end + 0.8)


if __name__ == "__main__":
    main()
