"""ClipNode：把一段外部画面贴进场景，当作背景板。

文字、公式、图形仍然是矢量节点，画在它上面（片段默认 z=-100）。
片段的音轨不参与合成。

取哪一帧只取决于成片时刻 renderer.time（render_video 会把它设成当前帧的时刻），
所以同一帧重复渲染、跳着渲染，像素都一样。
"""

from __future__ import annotations

import skia

from ..core.node import FRAME_HEIGHT, FRAME_WIDTH, BBox, Node
from .sample import ENDS, FITS, frame_index, place
from .source import open_source

_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)


def _plate_box(width: float | None, height: float | None, region) -> BBox:
    if region is not None and (width is not None or height is not None):
        raise ValueError("region 和 width/height 只能给一个")
    if region is not None:
        if isinstance(region, BBox):
            box = BBox(float(region.x0), float(region.y0), float(region.x1), float(region.y1))
        else:
            if len(region) != 4:
                raise ValueError(f"region 需要 4 个数 (x0, y0, x1, y1)，收到 {region!r}")
            box = BBox(*(float(v) for v in region))
    elif width is None and height is None:
        box = BBox(-FRAME_WIDTH / 2, -FRAME_HEIGHT / 2, FRAME_WIDTH / 2, FRAME_HEIGHT / 2)
    else:
        if width is None or height is None:
            raise ValueError("width 和 height 要一起给（场景单位，矩形中心在节点原点）")
        width, height = float(width), float(height)
        box = BBox(-width / 2, -height / 2, width / 2, height / 2)
    if box.width <= 0 or box.height <= 0:
        raise ValueError(f"片段区域宽高必须为正，收到 {box.width:g}×{box.height:g}")
    return box


class ClipNode(Node):
    """一块外部画面。

    src 是视频文件（mp4/mov/...）、帧目录，或 glob（如 ``sim/frame_*.png``）。
    kind 省略时按路径推断。帧序列必须给 fps；单张图按 1fps 的一帧处理。

    t_in / t_out 是源时间轴上的入点、出点（秒），区间为 [t_in, t_out)。
    出点省略则播到结尾。start 是这段在成片时间轴上的开始时刻。
    rate 是播放速率。end 为 ``hold``（停在最后一帧）或 ``loop``。

    不给 width/height/region 时铺满整个画面。给了 width 和 height，
    矩形以节点原点为中心；之后用 move_to、shift、to_edge 这些和别的节点一样摆。
    region 是局部坐标里的矩形 (x0, y0, x1, y1)，y 向上。

    视频按容器的平均帧率当成恒定帧率，并且不应用旋转元数据（宽高和码流一致）。
    """

    def __init__(
        self,
        src: str,
        *,
        kind: str | None = None,
        t_in: float = 0.0,
        t_out: float | None = None,
        rate: float = 1.0,
        fps: float | None = None,
        fit: str = "contain",
        width: float | None = None,
        height: float | None = None,
        region: BBox | tuple[float, float, float, float] | None = None,
        opacity: float = 1.0,
        end: str = "hold",
        start: float = 0.0,
        z: float = -100.0,
        muted: bool = True,
        cache_frames: int = 4,
        name: str = "",
    ):
        super().__init__(name=name or "clip", z=float(z))
        if not muted:
            raise NotImplementedError("片段的音轨不参与合成（muted 只能为 True）")
        if kind is not None and kind not in ("video", "frames"):
            raise ValueError(f"kind 必须是 video 或 frames，收到 {kind!r}")
        if fit not in FITS:
            raise ValueError(f"fit 必须是 contain、cover 或 stretch，收到 {fit!r}")
        if end not in ENDS:
            raise ValueError(f"end 必须是 hold 或 loop，收到 {end!r}")
        if rate <= 0:
            raise ValueError(f"rate 必须为正，收到 {rate}")
        if cache_frames < 1:
            raise ValueError("cache_frames 至少为 1")
        if not 0.0 <= opacity <= 1.0:
            raise ValueError(f"opacity 要在 0 和 1 之间，收到 {opacity}")
        self.src = str(src)
        self.kind = kind
        self.t_in = float(t_in)
        self.t_out = None if t_out is None else float(t_out)
        self.rate = float(rate)
        self.fps = None if fps is None else float(fps)
        self.fit = fit
        self.plate = _plate_box(width, height, region)
        self.opacity = float(opacity)
        self.end = ENDS[end]
        self.start = float(start)
        self.cache_frames = int(cache_frames)
        self._source = None

    def local_bbox(self) -> BBox:
        return self.plate

    def source(self):
        """打开（或复用）解码器。只在第一次取帧时碰文件。"""
        if self._source is None:
            self._source = open_source(self.src, self.kind, self.fps, self.cache_frames)
        return self._source

    def close(self) -> None:
        if self._source is not None:
            self._source.close()
            self._source = None

    def __enter__(self) -> ClipNode:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _window(self) -> tuple[float, float, float, int]:
        src = self.source()
        fps = self.fps if self.fps is not None else src.fps
        if fps is None or fps <= 0:
            raise ValueError(f"帧序列需要 fps：{self.src}")
        duration = src.n_frames / fps
        t_in = self.t_in
        t_out = duration if self.t_out is None else self.t_out
        if t_in < 0:
            raise ValueError(f"t_in 不能为负，收到 {t_in:g}")
        if t_out > duration + 0.5 / fps:
            raise ValueError(f"t_out={t_out:g} 超过片段时长 {duration:g} 秒")
        t_out = min(t_out, duration)
        if t_out <= t_in:
            raise ValueError(f"t_out（{t_out:g}）必须大于 t_in（{t_in:g}）")
        return t_in, t_out, float(fps), src.n_frames

    def frame_index_at(self, t: float) -> int | None:
        """成片时刻 t 用哪一帧。还没开始是 None。纯函数，不解码像素。"""
        t_in, t_out, fps, n_frames = self._window()
        return frame_index(
            t, start=self.start, t_in=t_in, t_out=t_out, rate=self.rate,
            fps=fps, n_frames=n_frames, end=self.end,
        )

    def raster_key(self, t: float):
        """给编码器判断这一帧的画面变了没有。只含帧号，不含像素。"""
        if self.opacity <= 0:
            return None
        return self.frame_index_at(t)

    def play_until(self) -> float:
        """播完修剪区间一遍的成片时刻。循环的片段也只算一遍，避免成片无限长。"""
        t_in, t_out, _, _ = self._window()
        return self.start + (t_out - t_in) / self.rate

    def paint_raster(self, canvas: skia.Canvas, time: float, opacity: float) -> None:
        index = self.frame_index_at(time)
        if index is None:
            return
        alpha = float(opacity) * self.opacity
        if alpha <= 0:
            return
        image = self.source().frame(index)
        placed = place(self.plate, image.width(), image.height(), self.fit)
        x0, y0, x1, y1 = placed.dest
        sx, sy, sw, sh = placed.src
        if x1 - x0 <= 0 or y1 - y0 <= 0 or sw <= 0 or sh <= 0:
            return
        paint = skia.Paint(AntiAlias=True)
        paint.setAlphaf(max(0.0, min(1.0, alpha)))
        # 画布的 y 向上，Skia 画图像时 y 向下：绕目标矩形中心翻一下，画面才是正的
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        canvas.save()
        canvas.translate(cx, cy)
        canvas.scale(1, -1)
        canvas.translate(-cx, -cy)
        canvas.drawImageRect(
            image,
            skia.Rect.MakeXYWH(float(sx), float(sy), float(sw), float(sh)),
            skia.Rect.MakeLTRB(float(x0), float(y0), float(x1), float(y1)),
            _SAMPLING,
            paint,
        )
        canvas.restore()
