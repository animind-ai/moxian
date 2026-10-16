"""Skia 光栅化后端：把对象树画成一帧。"""

from __future__ import annotations

from pathlib import Path as FsPath

import numpy as np
import skia

from ..core import FRAME_HEIGHT, FRAME_WIDTH, Node, Style, transform as T
from ..core.style import parse_color
from ..path import Path


def to_skia_path(path: Path, m: np.ndarray) -> skia.Path:
    sk = skia.Path()
    for sp in path.subpaths:
        if not sp.segments:
            continue
        s = T.apply(m, sp.start.reshape(1, 2))[0]
        sk.moveTo(float(s[0]), float(s[1]))
        for seg in sp.segments:
            q = T.apply(m, seg)
            sk.cubicTo(*(float(v) for v in q.flatten()))
        if sp.closed:
            sk.close()
    return sk


class SkiaRenderer:
    def __init__(self, width: int = 1920, height: int = 1080, background: str = "#FFFFFF"):
        self.width, self.height = width, height
        self.background = background
        self.scale = height / FRAME_HEIGHT  # 像素 / 单位
        # 单位坐标 → 像素：x 右移半个画面，y 翻转
        self.view = T.translate(width / 2, height / 2) @ T.scale(self.scale, -self.scale)

    def _paint(self, color: str, opacity: float, stroke: float | None) -> skia.Paint:
        r, g, b = parse_color(color)
        paint = skia.Paint(AntiAlias=True, Color4f=skia.Color4f(r, g, b, max(0.0, min(1.0, opacity))))
        if stroke is not None:
            paint.setStyle(skia.Paint.kStroke_Style)
            paint.setStrokeWidth(stroke * self.height / 1080)
            paint.setStrokeCap(skia.Paint.kRound_Cap)
            paint.setStrokeJoin(skia.Paint.kRound_Join)
        return paint

    def draw(self, canvas: skia.Canvas, root: Node) -> None:
        r, g, b = parse_color(self.background)
        canvas.clear(skia.Color4f(r, g, b, 1.0))
        for node, world, style in root.walk():
            path = getattr(node, "path", None)
            if path is None or path.is_empty() or not style.visible():
                continue
            sk = to_skia_path(path, self.view @ world)
            if style.fill is not None and style.fill_opacity * style.opacity > 0:
                canvas.drawPath(sk, self._paint(style.fill, style.fill_opacity * style.opacity, None))
            if style.stroke is not None and style.stroke_opacity * style.opacity > 0 and style.stroke_width > 0:
                canvas.drawPath(sk, self._paint(style.stroke, style.stroke_opacity * style.opacity, style.stroke_width))

    def render(self, root: Node) -> skia.Image:
        surface = skia.Surface(self.width, self.height)
        with surface as canvas:
            self.draw(canvas, root)
        return surface.makeImageSnapshot()

    def save_png(self, root: Node, out: str | FsPath) -> FsPath:
        out = FsPath(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.render(root).save(str(out), skia.kPNG)
        return out
