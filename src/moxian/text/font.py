"""文字 → 轮廓路径。用 Skia 取字形轮廓，不走 LaTeX。

字号 size 以 1080p 下的像素计（和 scene-spec / kit 的约定一致）。
生成的节点以基线左端为原点，y 向上。
"""

from __future__ import annotations

import skia

from ..core import PX, Group, Node, PathNode, Style, transform as T
from ..path import Path

DEFAULT_FONT = "Noto Sans CJK SC"
_typefaces: dict[str, skia.Typeface] = {}


def typeface(family: str) -> skia.Typeface:
    if family not in _typefaces:
        tf = skia.Typeface(family)
        if tf is None or tf.getFamilyName() != family:
            raise RuntimeError(f"系统里没有字体 {family!r}（找到的是 {tf.getFamilyName() if tf else None}）")
        _typefaces[family] = tf
    return _typefaces[family]


def skia_path_to_path(sk: skia.Path) -> Path:
    """把 Skia 路径转成我们的三次贝塞尔路径。Skia 的 y 向下，这里原样保留。"""
    out = Path()
    for verb, pts in sk:
        if verb == skia.Path.kMove_Verb:
            out.move_to(pts[0].x(), pts[0].y())
        elif verb == skia.Path.kLine_Verb:
            out.line_to(pts[1].x(), pts[1].y())
        elif verb == skia.Path.kQuad_Verb:
            out.quad_to(pts[1].x(), pts[1].y(), pts[2].x(), pts[2].y())
        elif verb == skia.Path.kConic_Verb:  # 极少见于字体；按二次曲线近似
            out.quad_to(pts[1].x(), pts[1].y(), pts[2].x(), pts[2].y())
        elif verb == skia.Path.kCubic_Verb:
            out.cubic_to(pts[1].x(), pts[1].y(), pts[2].x(), pts[2].y(), pts[3].x(), pts[3].y())
        elif verb == skia.Path.kClose_Verb:
            out.close()
    return out


class Text(Group):
    """一行文字，每个字一个子节点，便于逐字动画。"""

    def __init__(self, text: str, size: float = 36, color: str = "#000000", family: str = DEFAULT_FONT, weight: str = "normal"):
        super().__init__(name=text)
        self.text = text
        self.size = size
        self.family = family
        font = skia.Font(typeface(family), size)
        glyphs = font.textToGlyphs(text)
        xs = font.getXPos(glyphs)
        # 逐个取轮廓：getPaths 会漏掉空格这类没有轮廓的字形，让后面的字错位
        paths = [font.getPath(g) for g in glyphs]
        # 字形轮廓的单位是像素（字号 size 对应的像素），缩到画面单位并翻转 y
        to_frame = T.scale(PX, -PX)
        for ch, x, sk in zip(text, xs, paths):
            if sk is None or sk.isEmpty():
                continue
            p = skia_path_to_path(sk).transformed(T.translate(x, 0.0)).transformed(to_frame)
            self.add(PathNode(name=ch, path=p))
        self.advance = (font.getXPos(glyphs + [0])[-1] if glyphs else 0.0) * PX
        self.style = Style(fill=color)
        metrics = font.getMetrics()
        self.ascent = -metrics.fAscent * PX  # 基线以上
        self.descent = metrics.fDescent * PX  # 基线以下
        self.x_height = (metrics.fXHeight or size * 0.5) * PX

    def baseline_y(self) -> float:
        """当前世界坐标下基线的 y。"""
        return float(T.apply(self.matrix, [[0.0, 0.0]])[0][1])
