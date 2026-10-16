"""SVG 读取：path 的 d 属性，以及 dvisvgm 输出用到的那一小部分 SVG（g / path / defs / use / transform）。

目标不是通用 SVG 解析器，只覆盖我们自己产生的 SVG（dvisvgm --no-fonts）和简单的手绘 SVG。
注意 SVG 的 y 轴向下，这里按原样读进来，由调用方决定翻转。
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import numpy as np

from ..core import transform as T
from .path import Path

_TOKEN = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_d(d: str) -> Path:
    tokens = _TOKEN.findall(d)
    path = Path()
    i = 0
    cmd = None
    cur = np.zeros(2)
    start = np.zeros(2)
    last_c2: np.ndarray | None = None  # 上一段三次曲线的第二个控制点（S 用）
    last_q: np.ndarray | None = None  # 上一段二次曲线的控制点（T 用）

    def num() -> float:
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        if re.match(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]
            i += 1
        if cmd is None:
            raise ValueError("path d 必须以命令开头")
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            path.move_to(x, y)
            cur = start = np.array([x, y])
            cmd = "l" if rel else "L"  # 后续坐标按 lineto
            last_c2 = last_q = None
        elif c == "Z":
            path.close()
            cur = start.copy()
            last_c2 = last_q = None
        elif c == "L":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            path.line_to(x, y)
            cur = np.array([x, y])
            last_c2 = last_q = None
        elif c == "H":
            x = num()
            x = cur[0] + x if rel else x
            path.line_to(x, cur[1])
            cur = np.array([x, cur[1]])
            last_c2 = last_q = None
        elif c == "V":
            y = num()
            y = cur[1] + y if rel else y
            path.line_to(cur[0], y)
            cur = np.array([cur[0], y])
            last_c2 = last_q = None
        elif c == "C":
            vals = [num() for _ in range(6)]
            if rel:
                vals = [v + cur[k % 2] for k, v in enumerate(vals)]
            path.cubic_to(*vals)
            last_c2 = np.array(vals[2:4])
            cur = np.array(vals[4:6])
            last_q = None
        elif c == "S":
            vals = [num() for _ in range(4)]
            if rel:
                vals = [v + cur[k % 2] for k, v in enumerate(vals)]
            c1 = 2 * cur - last_c2 if last_c2 is not None else cur
            path.cubic_to(c1[0], c1[1], *vals)
            last_c2 = np.array(vals[0:2])
            cur = np.array(vals[2:4])
            last_q = None
        elif c == "Q":
            vals = [num() for _ in range(4)]
            if rel:
                vals = [v + cur[k % 2] for k, v in enumerate(vals)]
            path.quad_to(*vals)
            last_q = np.array(vals[0:2])
            cur = np.array(vals[2:4])
            last_c2 = None
        elif c == "T":
            vals = [num() for _ in range(2)]
            if rel:
                vals = [v + cur[k % 2] for k, v in enumerate(vals)]
            q = 2 * cur - last_q if last_q is not None else cur
            path.quad_to(q[0], q[1], *vals)
            last_q = q
            cur = np.array(vals)
            last_c2 = None
        elif c == "A":
            rx, ry, rot, large, sweep, x, y = [num() for _ in range(7)]
            if rel:
                x, y = cur[0] + x, cur[1] + y
            _arc_to(path, cur, rx, ry, rot, bool(large), bool(sweep), np.array([x, y]))
            cur = np.array([x, y])
            last_c2 = last_q = None
    return path


def _arc_to(path: Path, p0: np.ndarray, rx: float, ry: float, rot_deg: float, large: bool, sweep: bool, p1: np.ndarray) -> None:
    """椭圆弧转成若干三次贝塞尔（SVG 实现注记里的标准算法）。"""
    if np.allclose(p0, p1):
        return
    if rx == 0 or ry == 0:
        path.line_to(*p1)
        return
    phi = math.radians(rot_deg)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    d = (p0 - p1) / 2
    x1p = cos_phi * d[0] + sin_phi * d[1]
    y1p = -sin_phi * d[0] + cos_phi * d[1]
    rx, ry = abs(rx), abs(ry)
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num_ = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    coef = math.sqrt(max(0.0, num_ / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    center = np.array([cos_phi * cxp - sin_phi * cyp, sin_phi * cxp + cos_phi * cyp]) + (p0 + p1) / 2

    def angle(u, v):
        a = math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])
        return a

    v1 = np.array([(x1p - cxp) / rx, (y1p - cyp) / ry])
    v2 = np.array([(-x1p - cxp) / rx, (-y1p - cyp) / ry])
    theta1 = angle(np.array([1.0, 0.0]), v1)
    dtheta = angle(v1, v2)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi
    n = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2))))
    step = dtheta / n
    t = theta1
    for _ in range(n):
        t2 = t + step
        k = 4 / 3 * math.tan((t2 - t) / 4)
        e1 = np.array([math.cos(t), math.sin(t)])
        e2 = np.array([math.cos(t2), math.sin(t2)])
        d1 = np.array([-math.sin(t), math.cos(t)])
        d2 = np.array([-math.sin(t2), math.cos(t2)])

        def to_xy(q):
            return center + np.array([cos_phi * rx * q[0] - sin_phi * ry * q[1], sin_phi * rx * q[0] + cos_phi * ry * q[1]])

        c1 = to_xy(e1 + k * d1)
        c2 = to_xy(e2 - k * d2)
        end = to_xy(e2)
        path.cubic_to(c1[0], c1[1], c2[0], c2[1], end[0], end[1])
        t = t2


_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate)\(([^)]*)\)")


def parse_transform(text: str | None) -> np.ndarray:
    m = T.identity()
    if not text:
        return m
    for kind, args in _TRANSFORM.findall(text):
        vals = [float(v) for v in re.split(r"[\s,]+", args.strip()) if v]
        if kind == "matrix":
            part = T.from_svg(*vals)
        elif kind == "translate":
            part = T.translate(vals[0], vals[1] if len(vals) > 1 else 0.0)
        elif kind == "scale":
            part = T.scale(vals[0], vals[1] if len(vals) > 1 else None)
        else:
            part = T.rotate(math.radians(vals[0]), (vals[1], vals[2]) if len(vals) > 2 else None)
        m = m @ part
    return m


def _strip(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def parse_svg(text: str) -> list[tuple[Path, dict]]:
    """返回 (路径, 属性) 列表，坐标已经乘上各层 transform，仍是 SVG 坐标系（y 向下）。"""
    root = ET.fromstring(text)
    defs: dict[str, ET.Element] = {}
    for el in root.iter():
        if "id" in el.attrib:
            defs[el.attrib["id"]] = el
    out: list[tuple[Path, dict]] = []

    def visit(el: ET.Element, m: np.ndarray, inherited: dict) -> None:
        tag = _strip(el.tag)
        if tag in ("defs", "title", "desc", "metadata", "style"):
            return
        attrs = {**inherited, **{k: v for k, v in el.attrib.items() if k in ("fill", "stroke", "stroke-width", "fill-opacity", "opacity")}}
        m = m @ parse_transform(el.attrib.get("transform"))
        if tag == "path" and "d" in el.attrib:
            out.append((parse_d(el.attrib["d"]).transformed(m), attrs))
        elif tag == "rect":
            x, y = float(el.attrib.get("x", 0)), float(el.attrib.get("y", 0))
            w, h = float(el.attrib["width"]), float(el.attrib["height"])
            p = Path().move_to(x, y).line_to(x + w, y).line_to(x + w, y + h).line_to(x, y + h).close()
            out.append((p.transformed(m), attrs))
        elif tag == "use":
            href = el.attrib.get("{http://www.w3.org/1999/xlink}href") or el.attrib.get("href") or ""
            target = defs.get(href.lstrip("#"))
            if target is not None:
                shift = T.translate(float(el.attrib.get("x", 0)), float(el.attrib.get("y", 0)))
                visit(target, m @ shift, attrs)
            return
        for child in el:
            visit(child, m, attrs)

    visit(root, T.identity(), {})
    return out
