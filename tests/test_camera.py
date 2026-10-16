import shutil

import numpy as np
import pytest

from moxian.anim import CameraMove, Timeline, focus_on, reset
from moxian.core import FRAME_HEIGHT, FRAME_WIDTH, BBox, Camera, Group, PathNode, Style
from moxian.core.camera import fit
from moxian.path import line, rect
from moxian.render import SkiaRenderer

W, H = 320, 180


def pixels(renderer: SkiaRenderer, root) -> np.ndarray:
    return np.asarray(renderer.render(root).toarray())[:, :, :3].astype(int)


def dark(img: np.ndarray) -> np.ndarray:
    return img.sum(axis=2) < 300


def to_px(x: float, y: float) -> tuple[int, int]:
    s = H / FRAME_HEIGHT
    return int(round(W / 2 + x * s)), int(round(H / 2 - y * s))


def square_at(x: float, y: float, size: float = 0.3) -> PathNode:
    return PathNode(path=rect(size, size), style=Style(fill="#000000")).shift([x, y])


def test_identity_camera_is_pixel_identical():
    root = Group(square_at(1, 1), PathNode(path=line(-3, -2, 3, 2), style=Style(stroke="#2563A8", stroke_width=4)))
    plain = pixels(SkiaRenderer(W, H), root)
    with_cam = pixels(SkiaRenderer(W, H, camera=Camera()), root)
    assert np.array_equal(plain, with_cam)


def test_zoom_moves_and_enlarges_stage_but_not_fixed():
    stage = square_at(1.0, 0.5)
    pinned = square_at(-5.0, 3.0)
    pinned.fixed = True
    root = Group(stage, Group(pinned))
    cam = Camera(center=np.array([0.5, 0.0]), zoom=2.0)
    img = dark(pixels(SkiaRenderer(W, H, camera=cam), root))
    # 舞台上的方块：世界 (1, 0.5) → 画面 ((1-0.5)*2, 0.5*2) = (1, 1)
    x, y = to_px(1.0, 1.0)
    assert img[y, x]
    assert not img[to_px(1.0, 0.5)[::-1]]
    # 放大 2 倍：0.3 → 0.6 个单位宽
    cols = np.where(img[y])[0]
    cols = cols[np.abs(cols - x) < 30]
    assert abs(len(cols) - 0.6 * H / FRAME_HEIGHT) <= 2
    # 钉住的方块原地不动（fixed 由父节点继承也一样）
    px, py = to_px(-5.0, 3.0)
    assert img[py, px]


def test_fixed_layer_drawn_on_top_while_zoomed():
    card = PathNode(path=rect(2.0, 1.0), style=Style(fill="#FF0000"))
    card.fixed = True
    stage = PathNode(path=rect(1.0, 1.0), style=Style(fill="#000000"))
    root = Group(card, stage)  # 原本舞台后画、盖在题卡上
    x, y = to_px(0.0, 0.0)
    assert dark(pixels(SkiaRenderer(W, H, camera=Camera()), root))[y, x]
    img = pixels(SkiaRenderer(W, H, camera=Camera(zoom=1.5)), root)
    assert tuple(img[y, x]) == (255, 0, 0)


def test_fixed_flag_inherits_to_children():
    child = square_at(-5.0, 3.0)
    card = Group(child)
    card.fixed = True
    cam = Camera(center=np.array([2.0, 2.0]), zoom=5.0)
    img = dark(pixels(SkiaRenderer(W, H, camera=cam), Group(card)))
    px, py = to_px(-5.0, 3.0)
    assert img[py, px]


def test_keep_size_follows_camera_without_growing():
    dot = square_at(1.0, 0.5, size=0.2)
    dot.keep_size = True
    cam = Camera(center=np.array([1.0, 0.0]), zoom=10.0)
    img = dark(pixels(SkiaRenderer(W, H, camera=cam), Group(Group(dot))))
    # 位置跟镜头：世界 (1, 0.5) → 画面 (0, 5)，出画；换一个镜头中心
    assert not img.any()
    cam.center = np.array([1.0, 0.5])
    img = dark(pixels(SkiaRenderer(W, H, camera=cam), Group(Group(dot))))
    x, y = to_px(0.0, 0.0)
    assert img[y, x]
    assert abs(int(img[y].sum()) - 0.2 * H / FRAME_HEIGHT) <= 2  # 还是 0.2 个单位宽，没有放大 10 倍


def test_stroke_width_constant_under_zoom():
    root = Group(PathNode(path=line(-10, 0, 10, 0), style=Style(stroke="#000000", stroke_width=6)))
    widths = []
    for zoom in (1.0, 10.0, 60.0):
        img = dark(pixels(SkiaRenderer(W, H, camera=Camera(zoom=zoom)), root))
        widths.append(int(img[:, W // 2].sum()))
    assert max(widths) - min(widths) <= 1


def test_camera_move_zoom_is_geometric_and_ends_exact():
    cam = Camera()
    move = CameraMove(cam, center=[2.0, 1.0], zoom=100.0, duration=1.0)
    move.begin()
    move.interpolate(0.5)
    assert cam.zoom == pytest.approx(10.0)
    # 放大时终点在画面上的位置线性移到中心
    p = np.array([2.0, 1.0])
    for a in (0.25, 0.5, 0.75):
        move.interpolate(a)
        assert np.allclose(cam.to_screen(p)[0], (1 - a) * p)
    move.finish()
    assert cam.zoom == 100.0 and np.allclose(cam.center, p)


def test_camera_move_back_is_smooth_and_exact():
    cam = Camera(center=np.array([2.0, 1.0]), zoom=60.0)
    move = reset(cam, duration=1.0)
    move.begin()
    prev = None
    for a in np.linspace(0, 1, 11):
        move.interpolate(float(a))
        # 缩小时起点在画面上的位置线性移动
        assert np.allclose(cam.to_screen([2.0, 1.0])[0], a * np.array([2.0, 1.0]))
        if prev is not None:
            assert cam.zoom < prev
        prev = cam.zoom
    move.finish()
    assert cam.is_identity()


def test_camera_move_keeps_unspecified_values():
    cam = Camera(center=np.array([1.0, 0.0]), zoom=3.0)
    move = CameraMove(cam, zoom=6.0)
    move.begin()
    move.finish()
    assert np.allclose(cam.center, [1.0, 0.0]) and cam.zoom == 6.0
    with pytest.raises(ValueError):
        CameraMove(cam, zoom=0.0)


def test_fit_and_focus_on():
    box = BBox(1.0, 1.0, 3.0, 2.0)
    center, zoom = fit(box, margin=0.0)
    assert np.allclose(center, [2.0, 1.5])
    assert zoom == pytest.approx(min(FRAME_WIDTH / 2, FRAME_HEIGHT / 1))
    cam = Camera()
    anim = focus_on(cam, box, margin=0.5)
    anim.begin()
    anim.finish()
    view = cam.view_box()
    assert view.x0 <= box.x0 and view.x1 >= box.x1 and view.y0 <= box.y0 and view.y1 >= box.y1
    anim = focus_on(cam, box, zoom=4.0)
    anim.begin()
    anim.finish()
    assert cam.zoom == 4.0


def test_timeline_reports_camera_changes():
    cam = Camera()
    tl = Timeline()
    tl.add(1.0, CameraMove(cam, zoom=2.0, duration=1.0))
    assert tl.seek(0.5) is False
    assert tl.seek(1.5) is True and 1.0 < cam.zoom < 2.0
    assert tl.seek(2.0) is True and cam.zoom == 2.0  # 落到终点那一帧也要重画
    assert tl.seek(2.5) is False


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")
def test_video_redraws_frames_while_camera_moves(tmp_path):
    from moxian.encode import render_video

    cam = Camera()
    root = Group(square_at(0.5, 0.5))
    tl = Timeline()
    tl.add(0.5, CameraMove(cam, center=[0.5, 0.5], zoom=4.0, duration=0.5))
    logs = []
    render_video(root, tl, tmp_path / "cam.mp4", SkiaRenderer(64, 36, camera=cam), fps=10, until=1.5, log=logs.append)
    # 第 0 帧 + 镜头在 0.5~1.0 秒的 6 帧；其余 9 帧复用
    assert "16 帧（重画 7 帧）" in logs[0]
