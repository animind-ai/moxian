"""路径插值：把两条路径对齐成相同结构，再按比例混合；以及按比例截取路径（画线动画用）。

对齐规则（思路与 Manim 的点数对齐相同，实现是自己的）：
1. 子路径数不同：短的一方补"退化子路径"（缩成一点，位于对方对应子路径的中心），这样会从一点长出来。
2. 每对子路径的段数不同：少的一方把最长的段反复二分，直到段数相同。
"""

from __future__ import annotations

import numpy as np

from .path import Path, Subpath


def split_cubic(p0: np.ndarray, seg: np.ndarray, t: float) -> tuple[np.ndarray, np.ndarray]:
    """de Casteljau：把以 p0 起、控制点 seg=(c1, c2, p3) 的三次段在 t 处一分为二。返回两段的 (c1, c2, p3)。"""
    c1, c2, p3 = seg
    a = p0 + (c1 - p0) * t
    b = c1 + (c2 - c1) * t
    c = c2 + (p3 - c2) * t
    d = a + (b - a) * t
    e = b + (c - b) * t
    m = d + (e - d) * t
    return np.array([a, d, m]), np.array([e, c, p3])


def _seg_length(p0: np.ndarray, seg: np.ndarray) -> float:
    pts = np.vstack([p0.reshape(1, 2), seg])
    return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))


def subdivide(sp: Subpath, count: int) -> Subpath:
    """把子路径细分到恰好 count 段（count ≥ 现有段数）。"""
    out = Subpath(sp.start.copy(), [s.copy() for s in sp.segments], sp.closed)
    if not out.segments:
        out.segments = [np.array([out.start, out.start, out.start])]
    while len(out.segments) < count:
        starts = [out.start] + [s[2] for s in out.segments[:-1]]
        lengths = [_seg_length(p0, s) for p0, s in zip(starts, out.segments)]
        i = int(np.argmax(lengths))
        first, second = split_cubic(starts[i], out.segments[i], 0.5)
        out.segments[i : i + 1] = [first, second]
    return out


def _degenerate(center: np.ndarray, count: int) -> Subpath:
    c = center.copy()
    return Subpath(c, [np.array([c, c, c]) for _ in range(count)], closed=True)


def _center(sp: Subpath) -> np.ndarray:
    return sp.points().mean(axis=0)


def align(p: Path, q: Path) -> tuple[Path, Path]:
    """返回结构完全相同的两条新路径。"""
    ps = [sp for sp in p.subpaths if sp.segments]
    qs = [sp for sp in q.subpaths if sp.segments]
    n = max(len(ps), len(qs), 1)
    out_p, out_q = Path(), Path()
    for i in range(n):
        a = ps[i] if i < len(ps) else None
        b = qs[i] if i < len(qs) else None
        if a is None and b is None:
            continue
        if a is None:
            a = _degenerate(_center(b), len(b.segments))
        if b is None:
            b = _degenerate(_center(a), len(a.segments))
        count = max(len(a.segments), len(b.segments))
        out_p.subpaths.append(subdivide(a, count))
        out_q.subpaths.append(subdivide(b, count))
    return out_p, out_q


def lerp(p: Path, q: Path, t: float) -> Path:
    """p、q 必须已经对齐。"""
    out = Path()
    for a, b in zip(p.subpaths, q.subpaths):
        sp = Subpath(a.start + (b.start - a.start) * t, closed=a.closed or b.closed)
        sp.segments = [sa + (sb - sa) * t for sa, sb in zip(a.segments, b.segments)]
        out.subpaths.append(sp)
    return out


def partial(p: Path, alpha: float) -> Path:
    """按段数比例截取路径的前 alpha 部分（最后一段用 de Casteljau 截断）。"""
    alpha = max(0.0, min(1.0, alpha))
    total = sum(len(sp.segments) for sp in p.subpaths)
    if total == 0 or alpha >= 1.0:
        return p.copy()
    budget = alpha * total
    out = Path()
    for sp in p.subpaths:
        if budget <= 0:
            break
        new = Subpath(sp.start.copy())
        p0 = sp.start
        for seg in sp.segments:
            if budget >= 1:
                new.segments.append(seg.copy())
                budget -= 1
            elif budget > 1e-6:
                first, _ = split_cubic(p0, seg, budget)
                new.segments.append(first)
                budget = 0
                break
            else:
                break
            p0 = seg[2]
        if new.segments:
            out.subpaths.append(new)
    return out
