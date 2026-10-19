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

from ..core import FRAME_HEIGHT, BBox, Camera, ImageNode, Node
from ..core import transform as T
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


def _camera_exempt(root: Node) -> tuple[set[int], dict[int, np.ndarray]]:
    """镜头的两种例外：fixed 节点及其后代的 id；keep_size 节点及其后代 → 锚点（那个 keep_size 节点局部原点的世界坐标）。"""
    fixed: set[int] = set()
    anchors: dict[int, np.ndarray] = {}

    def visit(node: Node, parent: np.ndarray, pinned: bool, anchor: np.ndarray | None) -> None:
        m = parent @ node.matrix
        pinned = pinned or node.fixed
        if anchor is None and node.keep_size:
            anchor = m[:2, 2].copy()
        if pinned:
            fixed.add(id(node))
        elif anchor is not None:
            anchors[id(node)] = anchor
        for child in node.children:
            visit(child, m, pinned, anchor)

    visit(root, T.identity(), False, None)
    return fixed, anchors


class SkiaRenderer:
    def __init__(self, width: int = 1920, height: int = 1080, background: str = "#FFFFFF",
                 camera: Camera | None = None):
        self.width, self.height = width, height
        self.background = background
        self.camera = camera  # 可选镜头：叠在 view 之上；没有或是原样时和以前逐像素一致
        self.time = 0.0  # 成片时刻（秒）。ClipNode 靠它取帧；render_video 每帧会改
        self.scale = height / FRAME_HEIGHT  # 像素 / 单位
        # 单位坐标 → 像素：x 右移半个画面，y 翻转
        self.view = T.translate(width / 2, height / 2) @ T.scale(self.scale, -self.scale)
        self._paths: weakref.WeakKeyDictionary[Path, skia.Path] = weakref.WeakKeyDictionary()
        self._paints: dict[tuple, skia.Paint] = {}
        self._images: dict[str, skia.Image] = {}

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

    def camera_view(self) -> np.ndarray | None:
        """镜头生效时返回 view @ 镜头矩阵，否则 None。"""
        if self.camera is None or self.camera.is_identity():
            return None
        return self.view @ self.camera.matrix

    def to_pixels(self, box: BBox, pad: float = 4.0) -> skia.Rect:
        """box 是镜头里的世界坐标（跟镜头走的对象所在的坐标系）。"""
        cam_view = self.camera_view()
        view = self.view if cam_view is None else cam_view
        pts = T.apply(view, np.array([[box.x0, box.y0], [box.x1, box.y1]]))
        x0, x1 = sorted(pts[:, 0])
        y0, y1 = sorted(pts[:, 1])
        return skia.Rect.MakeLTRB(x0 - pad, y0 - pad, x1 + pad, y1 + pad)

    # ---- 绘制 ----

    def _placed_matrix(self, node: Node, world: np.ndarray, cam_view, fixed: set[int], anchors: dict[int, np.ndarray]) -> np.ndarray:
        """节点局部坐标 → 像素。镜头、fixed、keep_size 和路径节点走同一套。"""
        if cam_view is None or id(node) in fixed:
            return self.view @ world
        if id(node) in anchors:
            ax, ay = anchors[id(node)]
            return cam_view @ T.scale(1 / self.camera.zoom, about=(float(ax), float(ay))) @ world
        return cam_view @ world

    def draw(self, canvas: skia.Canvas, root: Node, dirty: BBox | None = None, time: float | None = None) -> None:
        """画整棵树；给了 dirty（单位坐标）就只重画那一块。time 会改成片时刻。"""
        if time is not None:
            self.time = time
        r, g, b = parse_color(self.background)
        canvas.save()
        if dirty is not None:
            canvas.clipRect(self.to_pixels(dirty))
        canvas.clear(skia.Color4f(r, g, b, 1.0))
        cam_view = self.camera_view()
        fixed, anchors = _camera_exempt(root) if cam_view is not None else (set(), {})
        items = root.walk()
        if fixed:
            # 镜头生效时不跟镜头走的一层（题卡、胶囊）整体画在最上面，放大的舞台不会盖住它
            items = list(items)
            items = [it for it in items if id(it[0]) not in fixed] + [it for it in items if id(it[0]) in fixed]
        for node, world, style in items:
            if isinstance(node, ImageNode):
                if style.opacity > 0:
                    self._draw_image(canvas, node, self._placed_matrix(node, world, cam_view, fixed, anchors), style.opacity)
                continue
            path = getattr(node, "path", None)
            paint_raster = getattr(node, "paint_raster", None)
            has_path = path is not None and style.visible() and not path.is_empty()
            if paint_raster is None and not has_path:
                continue
            full = self._placed_matrix(node, world, cam_view, fixed, anchors)
            canvas.save()
            canvas.concat(_skia_matrix(full))
            # 外部画面（片段）先画，同一节点上的路径盖在上面
            if paint_raster is not None:
                paint_raster(canvas, self.time, style.opacity)
            if not has_path:
                canvas.restore()
                continue
            sk = self.skia_path(path)
            # 描边宽度不随对象（和镜头）缩放：把画布缩放除回去（用 y 方向的单位像素比）
            fill_a = style.fill_opacity * style.opacity
            if style.fill is not None and fill_a > 0:
                canvas.drawPath(sk, self.paint(style.fill, fill_a, None))
            stroke_a = style.stroke_opacity * style.opacity
            if style.stroke is not None and stroke_a > 0 and style.stroke_width > 0:
                local_scale = float(np.sqrt(abs(np.linalg.det(full[:2, :2]))))
                width_px = style.stroke_width * self.height / 1080
                canvas.drawPath(sk, self._stroke_paint(style.stroke, stroke_a, width_px / max(local_scale, 1e-9)))
            canvas.restore()
        canvas.restore()

    def _draw_image(self, canvas: skia.Canvas, node: ImageNode, full: np.ndarray, opacity: float) -> None:
        img = self._images.get(node.src)
        if img is None:
            img = skia.Image.open(node.src)
            self._images[node.src] = img
        w, h = node.box_width, node.box_height
        canvas.save()
        canvas.concat(_skia_matrix(full))
        # 局部坐标 y 向上，位图 y 向下：先翻转再画进框里
        canvas.translate(-w / 2, h / 2)
        canvas.scale(1.0, -1.0)
        paint = skia.Paint(AntiAlias=True, Color4f=skia.Color4f(1.0, 1.0, 1.0, max(0.0, min(1.0, opacity))))
        canvas.drawImageRect(img, skia.Rect.MakeWH(w, h), skia.SamplingOptions(skia.FilterMode.kLinear,
                                                                              skia.MipmapMode.kLinear), paint)
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
