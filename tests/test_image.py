"""位图节点：按宽高比定框、画进框里（不上下颠倒）、跟着透明度淡入淡出。"""

import numpy as np
import skia

from moxian.core import FRAME_HEIGHT, Group, ImageNode
from moxian.render import SkiaRenderer

W, H = 320, 180


def pixels(renderer: SkiaRenderer, root) -> np.ndarray:
    image = renderer.render(root).convert(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType)
    return np.asarray(image.toarray())[:, :, :3].astype(int)


def two_tone(path) -> str:
    """上半红、下半蓝的 40×20 位图。"""
    surface = skia.Surface(40, 20)
    with surface as canvas:
        canvas.clear(skia.ColorBLUE)
        canvas.drawRect(skia.Rect.MakeWH(40, 10), skia.Paint(Color=skia.ColorRED))
    surface.makeImageSnapshot().save(str(path), skia.kPNG)
    return str(path)


def test_box_keeps_the_aspect_ratio(tmp_path):
    node = ImageNode.from_file(two_tone(tmp_path / "a.png"), width=4.0)
    b = node.bbox()
    assert (round(b.width, 6), round(b.height, 6)) == (4.0, 2.0)
    assert round(ImageNode.from_file(node.src, height=1.0).bbox().width, 6) == 2.0


def test_drawn_upright_in_its_box_and_fades(tmp_path):
    node = ImageNode.from_file(two_tone(tmp_path / "a.png"), width=4.0)
    r = SkiaRenderer(W, H, background="#FFFFFF")
    img = pixels(r, Group(node))
    s = H / FRAME_HEIGHT
    top, bottom = img[int(H / 2 - 0.5 * s), W // 2], img[int(H / 2 + 0.5 * s), W // 2]
    assert top[0] > 200 and top[2] < 60  # 上半是红的
    assert bottom[2] > 200 and bottom[0] < 60  # 下半是蓝的
    assert (img[5, 5] == 255).all()  # 框外是背景
    node.set_style(opacity=0.0)
    assert (pixels(r, Group(node)) == 255).all()
