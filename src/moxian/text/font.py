"""文字 → 轮廓路径。用 Skia 取字形轮廓，不走 LaTeX。

字号 size 以 1080p 下的像素计（和 scene-spec / kit 的约定一致）。
生成的节点以基线左端为原点，y 向上。
"""

from __future__ import annotations

import skia

from ..core import DOWN, LEFT, PX, Group, Node, PathNode, Style, arrange, transform as T
from ..path import Path

DEFAULT_FONT = "Noto Sans CJK SC"
WEIGHTS = {"normal": skia.FontStyle.Normal, "bold": skia.FontStyle.Bold}
_typefaces: dict[tuple[str, str], skia.Typeface] = {}

# 不能出现在行首的标点（挤到上一行末尾），和不能出现在行尾的标点
NO_LINE_START = set("，。、；：！？）》」』】〕〗〙〛’”…—")
NO_LINE_END = set("（《「『【〔〖〘〚‘“")


def typeface(family: str, weight: str = "normal") -> skia.Typeface:
    key = (family, weight)
    if key not in _typefaces:
        tf = skia.Typeface(family, WEIGHTS[weight]())
        if tf is None or tf.getFamilyName() != family:
            raise RuntimeError(f"系统里没有字体 {family!r}（找到的是 {tf.getFamilyName() if tf else None}）")
        _typefaces[key] = tf
    return _typefaces[key]


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


def measure(text: str, size: float, family: str = DEFAULT_FONT, weight: str = "normal") -> float:
    """一段文字的前进宽度（画面单位）。"""
    font = skia.Font(typeface(family, weight), size)
    return font.measureText(text) * PX


class Text(Group):
    """一行文字，每个字一个子节点，便于逐字动画。"""

    def __init__(self, text: str, size: float = 36, color: str = "#000000", family: str = DEFAULT_FONT, weight: str = "normal"):
        super().__init__(name=text)
        self.text = text
        self.size = size
        self.family = family
        self.weight = weight
        font = skia.Font(typeface(family, weight), size)
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


def wrap(text: str, size: float, max_width: float, family: str = DEFAULT_FONT, weight: str = "normal") -> list[str]:
    """按宽度折行（画面单位）。中文逐字折；英文单词不拆；标点不孤立在行首，开引号不留在行尾。"""
    font = skia.Font(typeface(family, weight), size)
    lines: list[str] = []
    current = ""
    width = 0.0
    tokens = _tokens(text)
    for tok in tokens:
        if tok == "\n":
            lines.append(current)
            current, width = "", 0.0
            continue
        w = font.measureText(tok) * PX
        if current and width + w > max_width and tok not in NO_LINE_START:
            # 行尾是开引号时把它带到下一行
            carry = ""
            if current and current[-1] in NO_LINE_END:
                carry, current = current[-1], current[:-1]
            lines.append(current.rstrip())
            current, width = carry, font.measureText(carry) * PX if carry else 0.0
            if tok == " ":
                continue
        current += tok
        width += w
    if current:
        lines.append(current.rstrip())
    return [ln for ln in lines] or [""]


def _tokens(text: str) -> list[str]:
    """折行单位：英文单词和数字整块，其余逐字。"""
    out: list[str] = []
    word = ""
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in "'-"):
            word += ch
            continue
        if word:
            out.append(word)
            word = ""
        out.append(ch)
    if word:
        out.append(word)
    return out


class Paragraph(Group):
    """多行文字：按 max_width 自动折行，每行一个 Text。"""

    def __init__(self, text: str, size: float = 30, color: str = "#000000", max_width: float = 10.0,
                 line_gap: float = 0.35, family: str = DEFAULT_FONT, weight: str = "normal", align: str = "left"):
        super().__init__(name=text)
        self.lines = [Text(ln, size, color, family, weight) for ln in wrap(text, size, max_width, family, weight)]
        for i, line in enumerate(self.lines):
            line.shift([0.0, -i * (line.ascent + line.descent + line_gap)])
        if align == "center":
            widest = max(ln.advance for ln in self.lines)
            for line in self.lines:
                line.shift([(widest - line.advance) / 2, 0.0])
        self.add(*self.lines)
