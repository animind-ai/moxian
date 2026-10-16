import math
import shutil

import numpy as np
import pytest

from moxian.core import DOWN, LEFT, RIGHT, Group, PathNode, Style, arrange
from moxian.core import transform as T
from moxian.path import circle, parse_d, parse_svg, parse_transform, rect, rounded_rect
from moxian.render import SkiaRenderer
from moxian.text import Text


def test_transform_compose_and_apply():
    m = T.translate(1, 2) @ T.scale(2)
    pts = T.apply(m, np.array([[1.0, 1.0]]))
    assert np.allclose(pts, [[3.0, 4.0]])
    r = T.rotate(math.pi / 2)
    assert np.allclose(T.apply(r, np.array([[1.0, 0.0]])), [[0.0, 1.0]])


def test_shapes_bbox():
    assert rect(2, 1).bbox() == (-1, -0.5, 1, 0.5)
    x0, y0, x1, y1 = circle(1).bbox()
    assert abs(x0 + 1) < 1e-9 and abs(x1 - 1) < 1e-9
    assert rounded_rect(3, 2, 0.3).bbox() == (-1.5, -1.0, 1.5, 1.0)


def test_parse_d_absolute_relative_and_arc():
    p = parse_d("M 0 0 L 10 0 l 0 10 H 0 Z")
    assert p.subpaths[0].closed and p.bbox() == (0, 0, 10, 10)
    q = parse_d("M0,0 C 1,2 3,4 5,6 S 9,10 11,12 Q 13,14 15,16 T 19,20")
    assert len(q.subpaths[0].segments) == 4
    a = parse_d("M 0 0 A 1 1 0 0 1 2 0")  # 半圆；SVG 的 y 向下，sweep=1 时弧在 y<0 一侧
    x0, y0, x1, y1 = a.bbox()
    assert abs(x1 - 2) < 1e-6 and y0 < -0.9 and abs(y1) < 1e-6


def test_parse_transform_and_use():
    m = parse_transform("translate(1 2) scale(3)")
    assert np.allclose(T.apply(m, np.array([[1.0, 1.0]])), [[4.0, 5.0]])
    svg = """<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'>
      <defs><path id='g' d='M0 0 L1 0 L1 1 Z'/></defs>
      <g transform='translate(10 0)'><use xlink:href='#g' x='5' y='0'/></g>
    </svg>"""
    paths = parse_svg(svg)
    assert len(paths) == 1 and paths[0][0].bbox() == (15, 0, 16, 1)


def test_node_placement():
    a = PathNode(path=rect(2, 1))
    b = PathNode(path=rect(1, 1))
    b.next_to(a, RIGHT, gap=0.5)
    assert abs(b.edge(LEFT)[0] - (a.edge(RIGHT)[0] + 0.5)) < 1e-9
    b.align_to(a, DOWN)
    assert abs(b.edge(DOWN)[1] - a.edge(DOWN)[1]) < 1e-9
    g = Group(a, b)
    g.scale_to_fit_width(7.0)
    assert abs(g.width - 7.0) < 1e-9
    g.move_to([0, 0])
    assert np.allclose(g.center(), [0, 0])
    c = PathNode(path=rect(1, 1))
    arrange([a, b, c], DOWN, gap=0.1, align=LEFT)
    assert abs(c.edge(LEFT)[0] - a.edge(LEFT)[0]) < 1e-9


def test_text_keeps_spaces_in_place():
    """空格没有轮廓，但后面的字不能因此错位。"""
    t = Text("a b", 30)
    names = [n.name for n in t.children]
    assert names == ["a", "b"]
    gap = t.children[1].bbox().x0 - t.children[0].bbox().x1
    assert gap > 0.04  # 中间空出一个空格的宽度（30px 字号下约 6.7px ≈ 0.05 单位）
    assert t.advance > t.width


def test_text_cjk_glyphs_and_metrics():
    t = Text("墨线", 36, color="#123456")
    assert len(t.children) == 2
    assert t.ascent > 0 and t.descent > 0
    assert t.style.fill == "#123456"
    assert t.children[1].bbox().x0 > t.children[0].bbox().x0


def test_render_png(tmp_path):
    root = Group(PathNode(path=rect(4, 2), style=Style(fill="#2563A8", stroke="#000000", stroke_width=4)))
    out = SkiaRenderer(192, 108, background="#FFFFFF").save_png(root, tmp_path / "f.png")
    assert out.exists() and out.stat().st_size > 200


@pytest.mark.skipif(shutil.which("latex") is None or shutil.which("dvisvgm") is None, reason="需要 latex 和 dvisvgm")
def test_tex_renders_paths(tmp_path, monkeypatch):
    from moxian.text import tex

    monkeypatch.setattr(tex, "CACHE", tmp_path / "tex")
    m = tex.math(r"b_n = A_{n+1} - A_n", 30)
    assert len(m.children) >= 8  # 每个字形一个路径
    box = m.bbox()
    assert abs(box.x0) < 1e-9 and abs(box.y0) < 1e-9  # 左下角在原点
    assert 0.15 < m.height < 0.4  # 30px 字号：主体约 7pt×3px，加下标


def test_bold_weight_and_wrap():
    from moxian.text import Paragraph, wrap

    bold = Text("墨线", 36, weight="bold")
    assert bold.width > Text("墨线", 36).width * 0.98  # 粗体至少不比常规窄
    lines = wrap("这是一段很长的中文，里面有逗号，还有句号。以及 English words 不拆开。", 30, 3.0)
    assert len(lines) >= 3
    assert all(not ln or ln[0] not in "，。" for ln in lines)  # 标点不在行首
    assert all("English" not in ln or "English" in ln for ln in lines)
    para = Paragraph("第一行\n第二行", 30, max_width=5.0)
    assert len(para.lines) == 2 and para.lines[1].center()[1] < para.lines[0].center()[1]
