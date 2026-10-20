"""片段：取帧（修剪、速率、帧率不一致、停住/循环）、贴合，以及一张用生成素材画出来的画面。"""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import skia

from moxian.anim import Timeline
from moxian.clip import ClipNode, frame_index
from moxian.clip.sample import place
from moxian.clip.source import collect_frames, infer_kind
from moxian.core import FRAME_HEIGHT, BBox, Camera, Group, PathNode, Style
from moxian.path import rect
from moxian.render import SkiaRenderer

RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)
WHITE = (255, 255, 255, 255)
COLORS = (RED, GREEN, BLUE, WHITE)


def _png(path: Path, width: int, height: int, paint) -> None:
    array = np.zeros((height, width, 4), np.uint8)
    paint(array)
    image = skia.Image.fromarray(
        array,
        colorType=skia.ColorType.kRGBA_8888_ColorType,
        alphaType=skia.AlphaType.kUnpremul_AlphaType,
    )
    image.save(str(path), skia.kPNG)


def _solid(path: Path, color, size: int = 16) -> None:
    _png(path, size, size, lambda array: array.__setitem__(slice(None), color))


def _frames(directory: Path, colors=COLORS, size: int = 16) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, color in enumerate(colors):
        path = directory / f"f{index:02d}.png"
        _solid(path, color, size)
        paths.append(path)
    return paths


def _video(directory: Path, fps: int = 10, colors=COLORS, ts_offset: float | None = None) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("需要 ffmpeg")
    _frames(directory, colors)
    pattern = str(directory / "f%02d.png")
    encoders = subprocess.check_output(["ffmpeg", "-hide_banner", "-encoders"], stderr=subprocess.DEVNULL, text=True)
    if "libx264rgb" in encoders:
        # 无损 rgb，黄金图可以逐像素对比
        out = directory / "clip.mp4"
        codec = ["-c:v", "libx264rgb", "-crf", "0", "-pix_fmt", "rgb24"]
    else:
        out = directory / "clip.mov"
        codec = ["-c:v", "png", "-pix_fmt", "rgba"]
    cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", str(fps), "-i", pattern, *codec]
    if ts_offset is not None:
        cmd += ["-output_ts_offset", str(ts_offset)]
    cmd.append(str(out))
    subprocess.check_call(cmd)
    return out


def _pixels(renderer: SkiaRenderer, root, time: float = 0.0) -> np.ndarray:
    renderer.time = time
    image = renderer.render(root).convert(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType)
    return np.asarray(image.toarray())[:, :, :3].astype(int)


def _at(image: np.ndarray, x: float, y: float) -> tuple[int, int, int]:
    height, width = image.shape[:2]
    scale = height / FRAME_HEIGHT
    px = int(round(width / 2 + x * scale))
    py = int(round(height / 2 - y * scale))
    return tuple(int(v) for v in image[py, px])


def _window(fps, n, **kw):
    base = dict(start=0.0, t_in=0.0, t_out=n / fps, rate=1.0, fps=fps, n_frames=n, end="hold")
    base.update(kw)
    return base


# ---------- 取帧 ----------

def test_frame_index_trim_rate_hold_and_loop():
    # 24fps、48 帧，源时长 2 秒
    assert frame_index(0.0, **_window(24, 48)) == 0
    assert frame_index(0.5, **_window(24, 48)) == 12
    assert frame_index(1 / 24, **_window(24, 48)) == 1
    # 速率：成片 0.5 秒、2 倍速，源走到 1.0 秒 → 第 24 帧
    assert frame_index(0.5, **_window(24, 48, rate=2)) == 24
    assert frame_index(1.0, **_window(24, 48, rate=0.5)) == 12
    # 播完停在最后一帧（下标 47）；循环则回到修剪区间的第一帧
    assert frame_index(2.0, **_window(24, 48, end="hold")) == 47
    assert frame_index(3.0, **_window(24, 48, end="hold")) == 47
    assert frame_index(2.0, **_window(24, 48, end="loop")) == 0
    assert frame_index(2.5, **_window(24, 48, end="loop")) == 12
    # 还没到 start 不画
    assert frame_index(0.5, **_window(24, 48, start=1.0)) is None
    assert frame_index(1.0, **_window(24, 48, start=1.0)) == 0
    # 修剪 [0.5, 1.0)：第一帧是 12，最后一帧是 23
    trimmed = _window(24, 48, t_in=0.5, t_out=1.0)
    assert frame_index(0.0, **trimmed) == 12
    assert frame_index(0.25, **trimmed) == 18
    assert frame_index(0.5, **trimmed) == 23
    assert frame_index(0.5, **_window(24, 48, t_in=0.5, t_out=1.0, end="loop")) == 12
    assert frame_index(0.75, **_window(24, 48, t_in=0.5, t_out=1.0, end="loop")) == 18
    assert frame_index(1.0, **_window(24, 48, t_in=0.5, t_out=1.0, end="loop")) == 12
    # 入点落在一帧中间：显示盖住该时刻的那一帧
    assert frame_index(0.0, **_window(10, 10, t_in=0.15, t_out=0.55)) == 1
    assert frame_index(0.4, **_window(10, 10, t_in=0.15, t_out=0.55, end="hold")) == 5


def test_frame_index_fps_mismatch_is_absolute():
    """输出按 30fps 取样、源是 24fps：帧号由时刻决定，不靠上一帧加一。"""
    # t = k/30 时，源时间 * 24
    expect = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4}
    for k, index in expect.items():
        assert frame_index(k / 30, **_window(24, 48)) == index
    # 同一时刻问两次、打乱顺序问，结果不变
    times = [5 / 30, 0.0, 2 / 30, 5 / 30, 0.5]
    first = [frame_index(t, **_window(24, 48)) for t in times]
    second = [frame_index(t, **_window(24, 48)) for t in reversed(times)]
    assert first == [4, 0, 1, 4, 12]
    assert list(reversed(second)) == first


def test_loop_wraps_at_cycle_boundaries_and_non_integer_trims():
    # 0.2 不能用二进制写尽。秒上的 fmod(0.6, 0.2) 略小于 0.2，
    # 整圈边界会落到修剪区间的最后一帧（3）；应该回到这一段的第一帧（2）。
    trimmed = _window(10, 10, t_in=0.2, t_out=0.4, end="loop")
    for k in range(6):
        assert frame_index(0.2 * k, **trimmed) == 2
    assert frame_index(0.1, **trimmed) == 3  # 圈内：源时间 0.3
    assert frame_index(0.3, **trimmed) == 3
    assert frame_index(0.599, **trimmed) == 3  # 边界之前仍是上一圈的最后一帧
    assert frame_index(0.3, **_window(10, 10, t_in=0.2, t_out=0.4, end="loop", rate=2)) == 2

    # 入点、出点不落在帧边界：[0.15, 0.55)，盖住的第一帧是 1
    odd = _window(10, 20, t_in=0.15, t_out=0.55, end="loop")
    assert frame_index(0.0, **odd) == 1
    for k in range(1, 5):
        assert frame_index(0.4 * k, **odd) == 1
    assert frame_index(0.25, **odd) == 4
    assert frame_index(0.4 + 0.25, **odd) == 4
    assert frame_index(0.8 + 0.25, **odd) == 4


def test_fit_contain_cover_stretch():
    wide = BBox(0, 0, 4, 2)  # 宽高比 2
    # 方图放进宽区域：contain 上下顶满、左右留空；cover 左右裁
    contained = place(wide, 100, 100, "contain")
    assert contained.dest == pytest.approx((1, 0, 3, 2))
    assert contained.src == pytest.approx((0, 0, 100, 100))
    covered = place(wide, 100, 100, "cover")
    assert covered.dest == pytest.approx((0, 0, 4, 2))
    assert covered.src == pytest.approx((0, 25, 100, 50))
    stretched = place(wide, 100, 100, "stretch")
    assert stretched.dest == pytest.approx((0, 0, 4, 2))
    assert stretched.src == pytest.approx((0, 0, 100, 100))
    # 宽图放进方区域：contain 左右顶满；cover 裁掉左右
    square = BBox(-2, -2, 2, 2)
    assert place(square, 200, 100, "contain").dest == pytest.approx((-2, -1, 2, 1))
    assert place(square, 200, 100, "cover").src == pytest.approx((50, 0, 100, 100))
    with pytest.raises(ValueError):
        place(square, 10, 10, "tile")


def test_clip_placement_matches_other_nodes():
    clip = ClipNode("missing.mp4", width=4, height=2)
    assert clip.z == -100
    assert clip.local_bbox() == BBox(-2, -1, 2, 1)
    clip.move_to([3, 1])
    assert np.allclose(clip.center(), [3, 1])
    # 不给尺寸就铺满画面，中心在原点
    full = ClipNode("missing.mp4")
    assert abs(full.width - 8 * 16 / 9) < 1e-9 and abs(full.height - 8) < 1e-9
    assert np.allclose(full.center(), [0, 0])
    region = ClipNode("missing.mp4", region=(-1, -2, 3, 2))
    assert region.local_bbox() == BBox(-1, -2, 3, 2)
    with pytest.raises(ValueError):
        ClipNode("missing.mp4", fit="zoom")
    with pytest.raises(ValueError):
        ClipNode("missing.mp4", width=4, height=2, region=(0, 0, 1, 1))
    with pytest.raises(NotImplementedError):
        ClipNode("missing.mp4", muted=False)


def test_frame_names_sort_naturally_and_kind_is_inferred(tmp_path):
    """帧序列按文件名自然排序：1、2、10，不是字典序。"""
    for name in ("frame_10.png", "frame_2.png", "frame_1.png", "note.txt"):
        (tmp_path / name).write_bytes(b"")
    ordered = [path.name for path in collect_frames(str(tmp_path))]
    assert ordered == ["frame_1.png", "frame_2.png", "frame_10.png"]
    assert infer_kind(str(tmp_path)) == "frames"
    assert infer_kind(str(tmp_path / "frame_*.png")) == "frames"
    assert infer_kind("shot.mp4") == "video"
    assert infer_kind(str(tmp_path / "frame_1.png")) == "frames"


# ---------- 解码和绘制 ----------

def test_frame_sequence_samples_and_does_not_load_everything(tmp_path):
    _frames(tmp_path / "seq")
    renderer = SkiaRenderer(80, 45, background="#000000")
    with ClipNode(str(tmp_path / "seq"), fps=10, fit="stretch", cache_frames=2) as clip:
        root = Group(clip)
        # 建节点、算帧号都不解码
        assert clip.frame_index_at(0.25) == 2
        assert clip.source().decodes == 0
        assert _at(_pixels(renderer, root, 0.0), 0, 0) == (255, 0, 0)
        assert _at(_pixels(renderer, root, 0.15), 0, 0) == (0, 255, 0)
        assert _at(_pixels(renderer, root, 0.25), 0, 0) == (0, 0, 255)
        # 播完停住；再问早先的时刻还是原来的帧
        assert _at(_pixels(renderer, root, 1.0), 0, 0) == (255, 255, 255)
        assert _at(_pixels(renderer, root, 0.0), 0, 0) == (255, 0, 0)
        # 缓存只有 2 帧，再回到第 0 帧会重新解码，但不会把整段都留在内存里
        assert clip.source().decodes == 5
        assert len(clip.source().cache) <= 2
        # 修剪掉开头两帧，rate=2 时成片 0.05 秒已经走到源 0.1 秒之后
    with ClipNode(str(tmp_path / "seq"), fps=10, fit="stretch", t_in=0.2, rate=2) as clip:
        root = Group(clip)
        assert _at(_pixels(renderer, root, 0.0), 0, 0) == (0, 0, 255)
        assert _at(_pixels(renderer, root, 0.05), 0, 0) == (255, 255, 255)
    with ClipNode(str(tmp_path / "seq"), fps=10, fit="stretch", end="loop") as clip:
        assert _at(_pixels(renderer, Group(clip), 0.4), 0, 0) == (255, 0, 0)


def test_sequence_is_upright_and_vectors_stay_on_top(tmp_path):
    path = tmp_path / "bands.png"

    def paint(array):
        array[:8] = RED
        array[8:] = BLUE

    _png(path, 32, 16, paint)
    renderer = SkiaRenderer(80, 45, background="#000000")
    with ClipNode(str(path), fit="stretch") as clip:
        label = PathNode(path=rect(2, 2), style=Style(fill="#00FF00"))
        image = _pixels(renderer, Group(clip, label), 0)
    # 源的上半（红）在画面上方，下半（蓝）在画面下方
    assert _at(image, 0, 2) == (255, 0, 0)
    assert _at(image, 0, -2) == (0, 0, 255)
    # 矢量方块盖在片段上面
    assert _at(image, 0, 0) == (0, 255, 0)


def test_fit_shows_up_in_the_pixels(tmp_path):
    path = tmp_path / "wide.png"

    def paint(array):
        array[:, :10] = RED
        array[:, 10:30] = GREEN
        array[:, 30:] = BLUE

    _png(path, 40, 20, paint)
    renderer = SkiaRenderer(160, 90, background="#101010")
    # cover 裁掉左右，中间的绿铺满这块方板
    with ClipNode(str(path), width=4, height=4, fit="cover") as clip:
        image = _pixels(renderer, Group(clip))
    assert _at(image, 0, 0) == (0, 255, 0)
    assert _at(image, 0, 1.5) == (0, 255, 0)
    assert image[0, 0].tolist() == [16, 16, 16]  # 方板没盖住的角落是背景
    # contain 留上下边，边以外是背景
    with ClipNode(str(path), width=4, height=4, fit="contain") as clip:
        image = _pixels(renderer, Group(clip))
    assert _at(image, 0, 0) == (0, 255, 0)
    assert _at(image, 0, 1.5) == (16, 16, 16)


def test_jpeg_frame_is_a_one_frame_plate(tmp_path):
    array = np.zeros((16, 16, 4), np.uint8)
    array[:] = RED
    image = skia.Image.fromarray(
        array, colorType=skia.ColorType.kRGBA_8888_ColorType, alphaType=skia.AlphaType.kUnpremul_AlphaType,
    )
    path = tmp_path / "red.jpg"
    image.save(str(path), skia.kJPEG, 95)
    assert infer_kind(str(path)) == "frames"
    renderer = SkiaRenderer(40, 30, background="#000000")
    with ClipNode(str(path), fit="stretch") as clip:
        pixel = _at(_pixels(renderer, Group(clip)), 0, 0)
    assert pixel[0] > 240 and pixel[1] < 30 and pixel[2] < 30


def test_opacity_multiplies_with_the_parent(tmp_path):
    _solid(tmp_path / "red.png", RED)
    renderer = SkiaRenderer(40, 30, background="#FFFFFF")
    with ClipNode(str(tmp_path / "red.png"), fit="stretch", opacity=0.5) as clip:
        parent = Group(clip)
        parent.set_style(opacity=0.5)
        pixel = _at(_pixels(renderer, parent), 0, 0)
    # 0.5 * 0.5 = 0.25 的红，叠在白底上
    assert pixel[0] == 255
    assert abs(pixel[1] - 191) <= 2 and abs(pixel[2] - 191) <= 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="需要 ffmpeg")
def test_video_seek_is_frame_accurate_and_streams(tmp_path):
    path = _video(tmp_path / "media")
    from moxian.clip.source import VideoFrames

    source = VideoFrames(path, cache_frames=2)
    try:
        # 先要最后一帧：不能把前面的都解出来
        assert _rgb(source, 3) == (255, 255, 255)
        assert source.decodes == 1 and source.opens == 1
        assert _rgb(source, 0) == (255, 0, 0)
        assert _rgb(source, 1) == (0, 255, 0)
        assert _rgb(source, 2) == (0, 0, 255)
        assert _rgb(source, 1) == (0, 255, 0)  # 缓存命中或重新 seek，颜色不变
        assert len(source.cache) <= 2
        # 顺着读只开一次管道
        source.close()
        source = VideoFrames(path, cache_frames=4)
        for index in range(4):
            _rgb(source, index)
        assert source.opens == 1
    finally:
        source.close()


def _rgb(source, index) -> tuple[int, int, int]:
    image = source.frame(index).convert(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType)
    pixel = np.asarray(image.toarray())[0, 0, :3]
    return tuple(int(v) for v in pixel)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="需要 ffmpeg")
def test_seek_uses_frame_index_when_start_timestamp_is_nonzero(tmp_path):
    """-ss 在 -i 前是相对输入起点的。再加 start_time 会跳过片头。"""
    path = _video(tmp_path / "media", ts_offset=1.5)
    probed = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=start_time", "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    ).strip()
    assert float(probed) >= 1.0
    from moxian.clip.source import VideoFrames

    source = VideoFrames(path)
    try:
        assert _rgb(source, 0) == (255, 0, 0)
        assert _rgb(source, 2) == (0, 0, 255)
        assert _rgb(source, 3) == (255, 255, 255)
        assert _rgb(source, 1) == (0, 255, 0)  # 往回跳仍然是那一帧
    finally:
        source.close()


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="需要 ffmpeg")
def test_golden_video_plate_under_a_vector(tmp_path):
    path = _video(tmp_path / "media")
    renderer = SkiaRenderer(80, 45, background="#000000")
    with ClipNode(str(path), fit="stretch") as clip:
        root = Group(clip, PathNode(path=rect(2, 2), style=Style(fill="#112233")))
        # 四个源帧，以及停住、修剪、二倍速
        assert _at(_pixels(renderer, root, 0.00), 3, 0) == (255, 0, 0)
        assert _at(_pixels(renderer, root, 0.10), 3, 0) == (0, 255, 0)
        assert _at(_pixels(renderer, root, 0.15), 3, 0) == (0, 255, 0)  # 10fps 的一帧盖住 [0.1, 0.2)
        assert _at(_pixels(renderer, root, 0.20), 3, 0) == (0, 0, 255)
        assert _at(_pixels(renderer, root, 0.30), 3, 0) == (255, 255, 255)
        assert _at(_pixels(renderer, root, 1.00), 3, 0) == (255, 255, 255)  # hold
        # 中间的矢量盖住片段；再跳回早先的时刻，颜色还是那一帧
        assert _at(_pixels(renderer, root, 0.20), 0, 0) == (17, 34, 51)
        assert _at(_pixels(renderer, root, 0.00), 3, 0) == (255, 0, 0)
        # 还没开始：透出背景
        clip.start = 1.0
        assert _at(_pixels(renderer, root, 0.0), 3, 0) == (0, 0, 0)

    with ClipNode(str(path), fit="stretch", t_in=0.2, end="loop") as clip:
        root = Group(clip)
        assert _at(_pixels(renderer, root, 0.0), 0, 0) == (0, 0, 255)
        # 修剪后只剩 0.2 秒（蓝、白），循环回到蓝
        assert _at(_pixels(renderer, root, 0.2), 0, 0) == (0, 0, 255)

    with ClipNode(str(path), fit="stretch", rate=2) as clip:
        assert _at(_pixels(renderer, Group(clip), 0.1), 0, 0) == (0, 0, 255)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="需要 ffmpeg")
def test_render_video_redraws_only_when_the_plate_changes(tmp_path):
    from moxian.encode import render_video

    path = _video(tmp_path / "media")
    logs = []
    with ClipNode(str(path), fit="stretch") as clip:
        out = render_video(
            Group(clip), Timeline(), tmp_path / "out.mp4",
            SkiaRenderer(160, 90, background="#000000"), fps=10, log=logs.append,
        )
    assert out.exists() and out.stat().st_size > 500
    # 4 张不同的源帧，第 5 个输出帧停在最后一帧，不必重画
    assert "5 帧（重画 4 帧）" in logs[0]

    logs.clear()
    with ClipNode(str(path), fit="stretch", end="loop") as clip:
        render_video(
            Group(clip), Timeline(), tmp_path / "loop.mp4",
            SkiaRenderer(160, 90, background="#000000"), fps=10, log=logs.append,
        )
    assert "5 帧（重画 5 帧）" in logs[0]


def test_fixed_plate_ignores_the_camera(tmp_path):
    _solid(tmp_path / "red.png", RED)
    renderer = SkiaRenderer(80, 45, background="#000000", camera=Camera(center=np.array([3.0, 0.0])))
    with ClipNode(str(tmp_path / "red.png"), width=2, height=2, fit="stretch") as clip:
        moved = _at(_pixels(renderer, Group(clip)), 0, 0)
        clip.fixed = True
        pinned = _at(_pixels(renderer, Group(clip)), 0, 0)
    assert moved == (0, 0, 0)  # 镜头挪走了，原点上不再是这块板
    assert pinned == (255, 0, 0)
