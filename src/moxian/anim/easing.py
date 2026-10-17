"""缓动函数：输入输出都在 [0, 1]。"""

from __future__ import annotations

import math


def linear(t: float) -> float:
    return t


def smooth(t: float) -> float:
    """两端都慢（smootherstep），默认缓动。"""
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (6 * t - 15) + 10)


def ease_in(t: float) -> float:
    return t * t


def ease_out(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def ease_in_out_sine(t: float) -> float:
    return -(math.cos(math.pi * t) - 1) / 2


def there_and_back(t: float) -> float:
    """0 → 1 → 0，用于强调一下再回来的动作。"""
    return smooth(2 * t) if t < 0.5 else smooth(2 * (1 - t))


BY_NAME = {
    "linear": linear, "smooth": smooth, "in": ease_in, "out": ease_out, "in_out": ease_in_out_sine,
}


def by_name(name: str):
    """按名字取缓动（linear / smooth / in / out / in_out），给场景文件这类只能写字符串的地方用。"""
    try:
        return BY_NAME[name]
    except KeyError:
        raise ValueError(f"没有缓动 {name!r}（可用：{'、'.join(BY_NAME)}）") from None
