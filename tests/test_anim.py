import shutil

import numpy as np
import pytest

from moxian.anim import Draw, Grow, Morph, Restyle, Shift, Timeline, easing, fade_in
from moxian.core import Group, PathNode, Style, parent_matrix_of
from moxian.path import align, circle, lerp, partial, rect, split_cubic, subdivide


def test_easing_endpoints():
    for f in (easing.linear, easing.smooth, easing.ease_in, easing.ease_out, easing.ease_in_out_sine):
        assert abs(f(0.0)) < 1e-9 and abs(f(1.0) - 1) < 1e-9
    assert easing.there_and_back(0.5) == 1.0


def test_split_cubic_keeps_endpoints():
    p0 = np.array([0.0, 0.0])
    seg = np.array([[1.0, 2.0], [3.0, 2.0], [4.0, 0.0]])
    a, b = split_cubic(p0, seg, 0.5)
    assert np.allclose(b[2], seg[2]) and np.allclose(a[2], b[0] - (b[0] - a[2]))  # 连续
    sp = subdivide(rect(2, 2).subpaths[0], 10)
    assert len(sp.segments) == 10 and np.allclose(sp.end(), sp.start)


def test_align_and_lerp():
    p, q = align(rect(2, 2), circle(1))
    assert len(p.subpaths) == len(q.subpaths) == 1
    assert len(p.subpaths[0].segments) == len(q.subpaths[0].segments)
    mid = lerp(p, q, 0.5)
    x0, y0, x1, y1 = mid.bbox()
    assert 0.9 < x1 - x0 < 2.1
    # 子路径数不同：少的一方补退化子路径
    two = rect(1, 1).extend(rect(1, 1).transformed(np.array([[1, 0, 3], [0, 1, 0], [0, 0, 1]], dtype=float)))
    a, b = align(two, circle(1))
    assert len(a.subpaths) == len(b.subpaths) == 2


def test_partial_path():
    full = rect(2, 2)
    half = partial(full, 0.5)
    assert sum(len(s.segments) for s in half.subpaths) == 2
    assert partial(full, 1.0).bbox() == full.bbox()
    assert partial(full, 0.0).is_empty()


def test_timeline_runs_animations_in_order():
    node = PathNode(path=rect(1, 1), style=Style(fill="#000000"))
    tl = Timeline()
    tl.add(1.0, fade_in(node, 1.0))
    tl.then(Shift(node, [2, 0], 1.0))
    assert tl.end == 3.0
    tl.seek(0.5)
    assert node.style.opacity == 1.0  # 还没开始，不动
    tl.seek(1.5)
    assert 0 < node.style.opacity < 1
    tl.seek(2.0)
    assert node.style.opacity == 1.0 and np.allclose(node.center(), [0, 0])
    tl.seek(3.5)
    assert np.allclose(node.center(), [2, 0])
    assert len(list(tl.frames(fps=10))) == 31


def test_grow_restyle_draw_morph():
    a = PathNode(path=rect(1, 1), style=Style(fill="#000000"))
    g = Grow(a, 1.0)
    g.begin()
    g.interpolate(0.5)
    assert abs(a.width - 0.5) < 1e-9 and a.style.opacity == 0.5
    g.finish()
    assert abs(a.width - 1.0) < 1e-9

    r = Restyle(a, 1.0, fill="#FFFFFF", stroke_width=10.0)
    r.begin()
    r.interpolate(0.5)
    assert a.style.fill == "#808080" and a.style.stroke_width == 6.0

    d = Draw(a, 1.0)
    d.begin()
    d.interpolate(0.25)
    assert sum(len(s.segments) for s in a.path.subpaths) == 1
    d.finish()
    assert sum(len(s.segments) for s in a.path.subpaths) == 4

    target = PathNode(path=circle(1), style=Style(fill="#FF0000"))
    m = Morph(a, target, 1.0)
    m.begin()
    m.finish()
    assert np.allclose(a.bbox().width, 2.0, atol=1e-6) and a.style.fill == "#FF0000"


def test_opacity_multiplies_down_the_tree_and_world_bbox():
    inner = PathNode(path=rect(1, 1), style=Style(fill="#000000", opacity=0.5))
    outer = Group(inner)
    outer.set_style(opacity=0.5)
    _, _, style = list(outer.walk())[1]
    assert style.opacity == 0.25 and style.fill == "#000000"
    root = Group(outer)
    outer.shift([3, 0])
    assert np.allclose(inner.world_bbox(root).center, [3, 0])
    assert np.allclose(parent_matrix_of(root, inner)[:2, 2], [3, 0])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")
def test_render_video(tmp_path):
    from moxian.encode import render_video
    from moxian.render import SkiaRenderer

    node = PathNode(path=rect(2, 2), style=Style(fill="#2563A8"))
    root = Group(node)
    tl = Timeline()
    tl.add(0.0, Shift(node, [2, 0], 0.5))
    out = render_video(root, tl, tmp_path / "v.mp4", SkiaRenderer(192, 108), fps=10, log=lambda *_: None)
    assert out.exists() and out.stat().st_size > 1000
