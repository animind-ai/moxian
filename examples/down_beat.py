"""用墨线渲染 scene-spec 示例 s67-p01 的 Down 一段（"往下做差"）。

旁白和书签照 animind/scene-spec/examples/s67-p01.scene.yaml 里的 Down beat；
时间来自 s67-p01（高中数列例题第 01 支）实际合成的 Down.timing.json；书签时刻按字符位置比例估算（和 kit 一样）。

运行：uv run python examples/down_beat.py <音频目录>  → build/down.mp4
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from common import BG, A, C, chips, diff_table, pin_top, problem_card, surrounding, underline

from moxian.anim import Draw, Grow, Restyle, Timeline, fade_in, together
from moxian.core import Group
from moxian.encode import render_video
from moxian.render import SkiaRenderer

if len(sys.argv) < 2:
    sys.exit("用法：uv run python examples/down_beat.py <音频目录>（目录里要有 animind-voice 生成的 Down.timing.json 和 Down.wav）")
AUDIO = Path(sys.argv[1])

SAY = [
    ("s1", "先往下做差。按定义，后一项减前一项：{@d0}五减二，得三。"),
    ("s2", "同样，{@d1}十一减五得六，{@d2}二十一减十一得十，{@d3}三十六减二十一得十五。"),
    ("s3", "一阶差数列再相邻相减：{@e}三、四、五。"),
    ("s4", "看，三、四、五，正好是公差为一的等差数列，{@k}和题目给的条件对上了。"),
]
_MARK = re.compile(r"\{@([A-Za-z_][A-Za-z0-9_]*)\}")


def timing():
    """返回 (句子起点 dict, 书签时刻 dict, 总时长)。"""
    data = json.loads((AUDIO / "Down.timing.json").read_text(encoding="utf-8"))
    starts, marks = {}, {}
    for (sid, text), cue in zip(SAY, data["cues"]):
        starts[sid] = cue["start"]
        plain = _MARK.sub("", text)
        for m in _MARK.finditer(text):
            frac = len(_MARK.sub("", text[: m.start()])) / max(1, len(plain))
            marks[m.group(1)] = cue["start"] + frac * (cue["end"] - cue["start"])
    return starts, marks, data["total"]


def build():
    root = Group(name="Down")
    card = problem_card()
    pin_top(card.node)
    root.add(card.node)

    table = diff_table(
        [([2, 5, 11, 21, 36, 57, 85, 121], A, r"A_n"), ([3, 6, 10, 15, 21, 28, 36], "#2F7D5B", r"b_n"), ([3, 4, 5, 6, 7, 8], C, r"c_n")],
        known=[5, 0, 0],
    )
    table.node.move_to([0.0, -0.75])
    root.add(table.node)

    plan = chips(["↓ 往下做差", "→ 在等差层补全", "↑ 逐层加回"])
    plan.node.move_to([0.0, -3.3])
    root.add(plan.node)
    return root, card, table, plan


def derive(table, r, i, duration=0.5):
    """第 r 行第 i 个数由做差得到：连线、垫色淡入，数字长出来。"""
    return together(
        fade_in(table.links[r - 1][i], duration),
        fade_in(table.pads[r - 1][i], duration),
        Grow(table.cells[r][i], duration),
    )


def main():
    root, card, table, plan = build()
    starts, marks, total = timing()
    tl = Timeline()

    # s1：聚焦第一个胶囊
    tl.add(starts["s1"], together(Restyle(plan.bgs[0], 0.4, fill=A), Restyle(plan.labels[0], 0.4, fill=BG)))
    # 一阶差：四个书签各出一个数
    for i, mark in enumerate(["d0", "d1", "d2", "d3"]):
        tl.add(marks[mark], derive(table, 1, i))
    # 二阶差：三个数撑到 s4 开始前
    span = max(0.9, starts["s4"] - marks["e"] - 0.1)
    for i in range(3):
        tl.add(marks["e"] + i * span / 3, derive(table, 2, i, duration=span / 3))
    # s4：框住三、四、五；书签 k 处给题目里的关键条件划线
    trio = Group(*table.cells[2][:3])
    table.node.add(trio)  # 挂到表下面，和数字同一坐标系
    box = surrounding(trio, root)
    box.set_style(opacity=0.0)
    root.add(box)
    tl.add(starts["s4"], fade_in(box, 0.4))
    key_line = underline(card.spans["key"], root)
    key_line.set_style(opacity=0.0)
    root.add(key_line)
    tl.add(marks["k"], Draw(key_line, 0.4))

    renderer = SkiaRenderer(1920, 1080, background=BG)
    out = render_video(root, tl, "build/down.mp4", renderer, fps=30, audio=AUDIO / "Down.wav", until=total + 0.5)
    print("wrote", out)


if __name__ == "__main__":
    main()
