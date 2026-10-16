"""Skia 光栅化后端：把对象树画成一帧。

性能要点：
- 每个 Path 对象只转一次 skia.Path（按对象身份缓存），变换交给画布矩阵，不在 Python 里逐点算；
- 可以只重画一块矩形（脏区），其余像素保留上一帧。
"""

from __future__ import annotations

import weakref
from pathlib import Path as FsPath

import numpy as np
import skia

from ..core import FRAME_HEIGHT, BBox, Node, Style, transform as T
from ..core.style import parse_color
from ..path import Path


def to_skia_path(path: Path, m: np.ndarray | None = None) -> skia.Path:
    sk = skia.Path()
    for sp in path.subpaths:
        if not sp.segments:
            continue
        s = sp.start if m is None else T.apply(m, sp.start.reshape(1, 2))[0]
        sk.moveTo(float(s[0]), float(s[1]))
        for seg in sp.segments:
            q = seg if m is None else T.apply(m, seg)
            sk.cubicTo(*(float(v) for v in q.flatten()))
        if sp.closed:
            sk.close()
    return sk


def _skia_matrix(m: np.ndarray) -> skia.Matrix:
    return skia.Matrix.MakeAll(
        float(m[0, 0]), float(m[0, 1]), float(m[0, 2]),
        float(m[1, 0]), float(m[1, 1]), float(m[1, 2]),
        0.0, 0.0, 1.0,
    )


class SkiaRenderer:
    def __init__(self, width: int = 1920, height: int = 1080, background: str = "#FFFFFF"):
        self.width, self.height = width, height
        self.background = background
        self.scale = height / FRAME_HEIGHT  # 像素 / 单位
        # 单位坐标 → 像素：x 右移半个画面，y 翻转
        self.view = T.translate(width / 2, height / 2) @ T.scale(self.scale, -self.scale)
        self._paths: "weakref.WeakKeyDictionary[Path, skia.Path]" = weakref.WeakKeyDictionary()
        self._paints: dict[tuple, skia.Paint] = {}

    # ---- 缓存 ----

    def skia_path(self, path: Path) -> skia.Path:
        sk = self._paths.get(path)
        if sk is None:
            sk = to_skia_path(path)
            self._paths[path] = sk
        return sk

    def paint(self, color: str, opacity: float, stroke: float | None) -> skia.Paint:
        key = (color, round(opacity, 4), None if stroke is None else round(stroke, 3))
        p = self._paints.get(key)
        if p is None:
            r, g, b = parse_color(color)
            p = skia.Paint(AntiAlias=True, Color4f=skia.Color4f(r, g, b, max(0.0, min(1.0, opacity))))
            if stroke is not None:
                p.setStyle(skia.Paint.kStroke_Style)
                p.setStrokeWidth(stroke * self.height / 1080)
                p.setStrokeCap(skia.Paint.kRound_Cap)
                p.setStrokeJoin(skia.Paint.kRound_Join)
            if len(self._paints) < 4096:
                self._paints[key] = p
        return p

    # ---- 坐标 ----

    def to_pixels(self, box: BBox, pad: float = 4.0) -> skia.Rect:
        pts = T.apply(self.view, np.array([[box.x0, box.y0], [box.x1, box.y1]]))
        x0, x1 = sorted(pts[:, 0])
        y0, y1 = sorted(pts[:, 1])
        return skia.Rect.MakeLTRB(x0 - pad, y0 - pad, x1 + pad, y1 + pad)

    # ---- 绘制 ----

    def draw(self, canvas: skia.Canvas, root: Node, dirty: BBox | None = None) -> None:
        """画整棵树；给了 dirty（单位坐标）就只重画那一块。"""
        r, g, b = parse_color(self.background)
        canvas.save()
        if dirty is not None:
            canvas.clipRect(self.to_pixels(dirty))
        canvas.clear(skia.Color4f(r, g, b, 1.0))
        for node, world, style in root.walk():
            path = getattr(node, "path", None)
            if path is None or not style.visible() or path.is_empty():
                continue
            sk = self.skia_path(path)
            canvas.save()
            canvas.concat(_skia_matrix(self.view @ world))
            # 描边宽度不随对象缩放：把画布缩放除回去（用 y 方向的单位像素比）
            fill_a = style.fill_opacity * style.opacity
            if style.fill is not None and fill_a > 0:
                canvas.drawPath(sk, self.paint(style.fill, fill_a, None))
            stroke_a = style.stroke_opacity * style.opacity
            if style.stroke is not None and stroke_a > 0 and style.stroke_width > 0:
                local_scale = float(np.sqrt(abs(np.linalg.det((self.view @ world)[:2, :2]))))
                width_px = style.stroke_width * self.height / 1080
                canvas.drawPath(sk, self._stroke_paint(style.stroke, stroke_a, width_px / max(local_scale, 1e-9)))
            canvas.restore()
        canvas.restore()

    def _stroke_paint(self, color: str, opacity: float, width_local: float) -> skia.Paint:
        key = (color, round(opacity, 4), "s", round(width_local, 5))
        p = self._paints.get(key)
        if p is None:
            r, g, b = parse_color(color)
            p = skia.Paint(AntiAlias=True, Color4f=skia.Color4f(r, g, b, max(0.0, min(1.0, opacity))))
            p.setStyle(skia.Paint.kStroke_Style)
            p.setStrokeWidth(width_local)
            p.setStrokeCap(skia.Paint.kRound_Cap)
            p.setStrokeJoin(skia.Paint.kRound_Join)
            if len(self._paints) < 4096:
                self._paints[key] = p
        return p

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
