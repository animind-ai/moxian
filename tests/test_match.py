"""TransformMatching（按配对平移 + 缩放、其余淡入淡出）和 arrow 路径。"""

import numpy as np
import pytest

from moxian.anim import Timeline, TransformMatching
from moxian.core import Group, PathNode, Style
from moxian.path import arrow, circle, rect


def piece(w: float, x: float, h: float = 1.0) -> PathNode:
    return PathNode(path=rect(w, h), style=Style(fill="#000000")).shift([x, 0])


def row(*pieces: PathNode, y: float = 0.0) -> Group:
    g = Group(*pieces)
    g.style = Style(fill="#000000")
    return g.shift([0, y])


def world_center(root, node):
    return node.world_bbox(root).center


def test_matched_parts_move_and_scale_smoothly_from_source_to_target():
    a0, b0, eq0 = piece(1, 0), piece(1, 2), piece(0.5, 4)
    src = row(a0, b0, eq0, y=2)
    a1, b1, c1 = piece(2, 0, 2), piece(2, 5, 2), piece(2, 9, 2)  # 同样的字放大一倍
    dst = row(a1, b1, c1, y=-2)
    dst.set_style(opacity=0.0)
    root = Group(src, dst)
    start_a, end_a = world_center(root, a0), world_center(root, a1)
    end_box = a1.world_bbox(root)
    t = TransformMatching(src, dst, [([a0], [a1], False), ([b0], [b1], False)], root, 1.0)
    t.begin()
    # 一开始：目标的 a 就在源 a 的位置、大小；源的 a 藏起来了；没配上的 c 完全透明
    assert np.allclose(world_center(root, a1), start_a)
    assert np.isclose(a1.world_bbox(root).width, a0.world_bbox(root).width)
    assert a0.style.opacity == 0.0 and c1.style.opacity == 0.0 and dst.style.opacity == 1.0
    t.interpolate(0.5)
    mid = world_center(root, a1)
    assert np.allclose(mid, (start_a + end_a) / 2)  # 中途：中心在起点和终点正中
    w_mid = a1.world_bbox(root).width
    assert 1.0 < w_mid < 2.0  # 大小也在两者之间
    assert np.isclose(c1.style.opacity, 0.5) and np.isclose(src.style.opacity, 0.5)
    t.finish()
    b = a1.world_bbox(root)
    assert np.allclose([b.x0, b.y0, b.x1, b.y1], [end_box.x0, end_box.y0, end_box.x1, end_box.y1])
    assert dst.style.opacity == 1.0 and src.style.opacity == 0.0
    assert a0.style.opacity == 1.0 and c1.style.opacity == 1.0  # 部件的样式都还原了（源整体藏着）


def test_unmatched_source_fades_and_keep_source_leaves_it_alone():
    a0, x0 = piece(1, 0), piece(1, 2)
    src = row(a0, x0, y=2)
    a1 = piece(1, 3)
    dst = row(a1)
    dst.set_style(opacity=0.0)
    root = Group(src, dst)
    t = TransformMatching(src, dst, [([a0], [a1], False)], root, 1.0, keep_source=True)
    t.begin()
    assert a0.style.opacity == 1.0 and src.style is not None and src.style.opacity == 1.0
    assert np.allclose(world_center(root, a1), world_center(root, a0))
    t.finish()
    assert src.style.opacity == 1.0 and dst.style.opacity == 1.0


def test_crossfade_pairs_move_both_ways_and_inherited_style_keeps_its_color():
    a0 = PathNode(path=circle(0.5))  # 没有自己的样式：继承父节点的颜色
    src = Group(a0)
    src.style = Style(fill="#FF0000")
    a1 = PathNode(path=rect(2, 2), style=Style(fill="#0000FF"))
    dst = Group(a1).shift([4, 0])
    dst.set_style(opacity=0.0)
    root = Group(src, dst)
    t = TransformMatching(src, dst, [([a0], [a1], True)], root, 1.0)
    t.begin()
    assert a0.style.fill == "#FF0000"  # 改透明度时没丢掉继承来的颜色
    assert np.isclose(a1.style.opacity, 0.0)
    t.interpolate(0.5)
    assert np.allclose(world_center(root, a0), world_center(root, a1))  # 两边在中途重合
    assert np.isclose(a1.style.opacity, 0.5)
    t.finish()
    assert a0.style is None  # 还原成继承
    assert np.allclose(world_center(root, a1), [4, 0])


def test_timeline_drives_matching_like_any_animation():
    a0 = piece(1, 0)
    src = row(a0)
    a1 = piece(1, 6)
    dst = row(a1)
    dst.set_style(opacity=0.0)
    root = Group(src, dst)
    tl = Timeline()
    tl.add(0.0, TransformMatching(src, dst, [([a0], [a1], False)], root, 1.0))
    tl.seek(0.5)
    assert 0.0 < world_center(root, a1)[0] < 6.0
    tl.seek(2.0)
    assert np.allclose(world_center(root, a1), [6, 0])


def test_arrow_tip_lands_on_the_end_point_and_shaft_stops_at_the_head():
    shaft, head = arrow(0, 0, 3, 4, head=0.5, half_width=0.2)
    assert head.subpaths[0].closed
    assert np.allclose(head.subpaths[0].start, [3, 4])
    end = shaft.subpaths[0].end()
    assert np.isclose(np.hypot(3 - end[0], 4 - end[1]), 0.5)
    short_shaft, short_head = arrow(0, 0, 0.2, 0, head=0.5)
    x0, _y0, x1, _y1 = short_head.bbox()
    assert np.isclose(x1 - x0, 0.1)  # 太短：尖缩到总长的一半
    with pytest.raises(ValueError):
        arrow(1, 1, 1, 1)
