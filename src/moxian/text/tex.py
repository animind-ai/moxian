"""公式 → 轮廓路径：latex 出 dvi，dvisvgm 出无字体的 SVG，再读成路径。

和 Manim 的做法同源（这是 TeX 转矢量的标准路线），代码是自己写的。
结果按内容哈希缓存在 .moxian-cache/tex/ 里。
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path as FsPath

from ..core import PX, Group, PathNode, Style
from ..core import transform as T
from ..path import parse_svg

PREAMBLE = r"""\documentclass[preview,border=0.5pt]{standalone}
\usepackage{amsmath,amssymb}
"""

CACHE = FsPath(".moxian-cache") / "tex"


class TexError(RuntimeError):
    pass


def _compile(source: str) -> FsPath:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((PREAMBLE + source).encode("utf-8")).hexdigest()[:16]
    svg = CACHE / f"{key}.svg"
    if svg.exists():
        return svg
    tex = CACHE / f"{key}.tex"
    tex.write_text(PREAMBLE + "\\begin{document}\n" + source + "\n\\end{document}\n", encoding="utf-8")
    run = subprocess.run(
        ["latex", "-interaction=batchmode", "-halt-on-error", f"-output-directory={CACHE}", str(tex)],
        capture_output=True, text=True,
    )
    dvi = tex.with_suffix(".dvi")
    if run.returncode != 0 or not dvi.exists():
        log = tex.with_suffix(".log")
        tail = log.read_text(errors="replace")[-1500:] if log.exists() else run.stdout[-1500:]
        raise TexError(f"LaTeX 编译失败：{source!r}\n{tail}")
    run = subprocess.run(["dvisvgm", "--no-fonts", "--exact-bbox", "-o", str(svg), str(dvi)], capture_output=True, text=True)
    if run.returncode != 0 or not svg.exists():
        raise TexError(f"dvisvgm 失败：{run.stderr[-800:]}")
    for ext in (".aux", ".log", ".dvi"):
        tex.with_suffix(ext).unlink(missing_ok=True)
    return svg


class Tex(Group):
    """一段 LaTeX（可以是 $...$ 公式，也可以是文字）。每个路径一个子节点。

    size 以 1080p 像素计；LaTeX 默认 10pt 字号被缩放到 size 像素高的字。
    """

    def __init__(self, source: str, size: float = 36, color: str = "#000000"):
        super().__init__(name=source)
        self.source = source
        self.size = size
        svg = _compile(source)
        # dvisvgm 的单位是 pt；10pt 字对应 size 像素 → 每 pt 为 size/10 像素；再翻转 y
        k = size / 10 * PX
        to_frame = T.scale(k, -k)
        for path, _attrs in parse_svg(svg.read_text(encoding="utf-8")):
            self.add(PathNode(path=path.transformed(to_frame)))
        # 以左下角为原点
        box = self.bbox()
        if box is not None:
            self.shift([-box.x0, -box.y0])
            for child in self.children:
                child.matrix = self.matrix @ child.matrix
            self.matrix = T.identity()
        self.style = Style(fill=color)


def math(source: str, size: float = 36, color: str = "#000000") -> Tex:
    return Tex(f"${source}$", size, color)
