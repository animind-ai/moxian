"""片段取帧和贴合，都是时间与几何的纯函数。

同一组参数调用多少次、按什么顺序调用，结果都一样。渲染第 N 帧时用成片时刻
t = N / fps 来取，不靠「上一帧播到哪」累加，所以跳着 seek、往回 seek 都落到同一源帧。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.node import BBox

FITS = ("contain", "cover", "stretch")
# hold-last-frame 是文档里的名字；实现里记成 hold
ENDS = {"hold": "hold", "hold-last-frame": "hold", "loop": "loop"}


def frame_index(
    t: float,
    *,
    start: float,
    t_in: float,
    t_out: float,
    rate: float,
    fps: float,
    n_frames: int,
    end: str,
) -> int | None:
    """成片时刻 t 对应的源帧下标；还没到 start 时返回 None（这一帧不画）。

    修剪区间是源时间上的半开区间 [t_in, t_out)。源帧 i 覆盖 [i/fps, (i+1)/fps)。
    播完一遍之后，end="hold" 停在最后一帧，end="loop" 回到区间开头。
    rate 是播放速率：2 表示成片过 1 秒，源走 2 秒。
    """
    if n_frames <= 0:
        raise ValueError("片段没有帧")
    if fps <= 0:
        raise ValueError(f"fps 必须为正，收到 {fps}")
    if rate <= 0:
        raise ValueError(f"rate 必须为正，收到 {rate}")
    if t_out <= t_in:
        raise ValueError(f"t_out（{t_out:g}）必须大于 t_in（{t_in:g}）")
    mode = ENDS.get(end)
    if mode is None:
        raise ValueError(f"end 必须是 hold 或 loop，收到 {end!r}")
    if t < start:
        return None

    elapsed = (t - start) * rate
    span = t_out - t_in
    first, last = _trim_bounds(t_in, t_out, fps, n_frames)

    if mode == "hold" and elapsed >= span:
        return last
    # 循环在「帧」上取余，不在秒上取余。秒上的 fmod(0.6, 0.2) 会得到略小于 0.2 的数，
    # 整圈边界就被当成上一圈的最后一帧。
    if mode == "loop":
        offset_frames = _wrapped_frame_offset(elapsed, span, fps)
        idx = math.floor(t_in * fps + offset_frames + 1e-9)
    else:
        idx = math.floor((t_in + elapsed) * fps + 1e-9)
    return int(min(max(int(idx), first), last))


def _wrapped_frame_offset(elapsed: float, span: float, fps: float) -> float:
    """循环播放时，落在修剪区间内的位置，单位是帧。整圈边界（第 k 圈的起点）返回 0。"""
    span_frames = span * fps
    if span_frames <= 0:
        return 0.0
    cycles = (elapsed * fps) / span_frames
    nearest = round(cycles)
    # 容差跟圈数一起放大，只吃掉浮点误差，不会提前一整帧。
    if abs(cycles - nearest) <= 1e-9 * max(1.0, abs(cycles)):
        return 0.0
    phase = cycles - math.floor(cycles)
    if phase < 0.0:
        phase += 1.0
    if phase > 1.0 - 1e-9:
        return 0.0
    return phase * span_frames


def _trim_bounds(t_in: float, t_out: float, fps: float, n_frames: int) -> tuple[int, int]:
    """修剪区间 [t_in, t_out) 盖住的第一帧和最后一帧。"""
    first = int(math.floor(t_in * fps + 1e-9))
    # ceil(t_out*fps) - 1：起点恰好等于 t_out 的那一帧不算在区间里
    last = int(math.ceil(t_out * fps - 1e-9) - 1)
    first = min(max(first, 0), n_frames - 1)
    last = min(max(last, 0), n_frames - 1)
    if last < first:
        last = first
    return first, last


@dataclass(frozen=True)
class Placement:
    """dest 是局部坐标（y 向上）的目标矩形；src 是像素裁切（y 向下，左上为原点）。"""

    dest: tuple[float, float, float, float]
    src: tuple[float, float, float, float]


def place(region: BBox, src_w: float, src_h: float, fit: str) -> Placement:
    """把源画面贴进 region。

    contain：整幅源都看得见，比例不变，不够的地方留空。
    cover：盖满 region，比例不变，多出来的两边裁掉。
    stretch：拉满 region，不保留比例。
    """
    if fit not in FITS:
        raise ValueError(f"fit 必须是 contain、cover 或 stretch，收到 {fit!r}")
    rw, rh = region.width, region.height
    if rw <= 0 or rh <= 0:
        raise ValueError(f"区域宽高必须为正，收到 {rw:g}×{rh:g}")
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"源画面宽高必须为正，收到 {src_w:g}×{src_h:g}")

    full_dest = (region.x0, region.y0, region.x1, region.y1)
    full_src = (0.0, 0.0, float(src_w), float(src_h))
    if fit == "stretch":
        return Placement(full_dest, full_src)

    src_aspect = src_w / src_h
    region_aspect = rw / rh
    if fit == "contain":
        if src_aspect > region_aspect:
            dw, dh = rw, rw / src_aspect
        else:
            dh, dw = rh, rh * src_aspect
        x0 = region.x0 + (rw - dw) / 2
        y0 = region.y0 + (rh - dh) / 2
        return Placement((x0, y0, x0 + dw, y0 + dh), full_src)

    # cover：目标就是 region，从源中间裁掉多余的边
    if src_aspect > region_aspect:
        vis_w = src_h * region_aspect
        sx = (src_w - vis_w) / 2
        return Placement(full_dest, (sx, 0.0, vis_w, float(src_h)))
    vis_h = src_w / region_aspect
    sy = (src_h - vis_h) / 2
    return Placement(full_dest, (0.0, sy, float(src_w), vis_h))
