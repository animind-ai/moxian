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
