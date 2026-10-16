"""第一帧：题卡 + 中文和公式混排 + 差分表的一角。颜色取 palette 的"草稿纸"主题。

运行：uv run python examples/first_frame.py  → build/first_frame.png
"""

from __future__ import annotations

from moxian.core import DOWN, LEFT, RIGHT, UP, Group, PathNode, Style, arrange
from moxian.path import line, rect, rounded_rect
from moxian.render import SkiaRenderer
from moxian.text import Text, math

# palette · paper
BG, FG, A, B, C, HL_INK, DIM, CARD, MARK = "#F7F3EA", "#1E2430", "#2563A8", "#2F7D5B", "#C2561F", "#B7860B", "#9AA0A8", "#EDE6D8", "#F1DDB5"


def inline(parts, gap=0.06):
    """把若干 Text / Tex 排成一行：公式按 x 高度对齐到文字。"""
    row = Group(*parts)
    for prev, node in zip(parts, parts[1:]):
        node.next_to(prev, RIGHT, gap)
    base = parts[0]
    for node in parts[1:]:
        if isinstance(node, Text):
            node.align_to(base, DOWN)
        else:  # 公式：竖直居中到文字的 x 高度中线
            target_y = base.edge(DOWN)[1] + base.x_height / 2 + 0.02
            node.shift([0.0, target_y - node.center()[1]])
    return row


def card_lines():
    l1 = inline([
        Text("定义：对数列 ", 30, FG), math(r"\{A_n\}", 30, FG), Text("，令 ", 30, FG),
        math(r"b_n = A_{n+1} - A_n", 30, B), Text("，则 ", 30, FG), math(r"\{b_n\}", 30, FG),
        Text(" 称为一阶差数列；", 30, FG),
    ])
    l2 = inline([
        Text("再令 ", 30, FG), math(r"c_n = b_{n+1} - b_n", 30, C), Text("，则 ", 30, FG),
        math(r"\{c_n\}", 30, FG), Text(" 称为二阶差数列．", 30, FG),
    ])
    l3 = inline([
        Text("已知 ", 30, FG), math(r"\{A_n\}", 30, FG), Text(" 为 ", 30, FG), math(r"2, 5, 11, 21, 36, \cdots", 30, A),
        Text("，且它的二阶差数列是等差数列，则 ", 30, FG), math(r"A_8 = ", 30, HL_INK), math(r"\underline{\hspace{3em}}", 30, FG),
    ])
    lines = [l1, l2, l3]
    arrange(lines, DOWN, gap=0.2, align=LEFT)
    return Group(*lines)


def problem_card():
    lines = card_lines()
    w, h = lines.width + 0.6, lines.height + 0.42
    bg = PathNode(path=rounded_rect(w, h, 0.14), style=Style(fill=CARD))
    bar = PathNode(path=rect(0.08, h - 0.24), style=Style(fill=HL_INK))
    card = Group(bg, bar, lines)
    bg.move_to(lines.center())
    bar.move_to([bg.edge(LEFT)[0] + 0.14, bg.center()[1]])
    return card


def diff_table():
    rows = [([2, 5, 11, 21, 36], A, r"A_n"), ([3, 6, 10, 15], B, r"b_n"), ([3, 4, 5], C, r"c_n")]
    col, rowh = 1.36, 1.17
    table = Group()
    cells = []
    for r, (values, color, label) in enumerate(rows):
        y = -r * rowh
        row = []
        for i, v in enumerate(values):
            m = math(str(v), 42, color).move_to([-3.0 + i * col + r * col / 2, y])
            row.append(m)
            table.add(m)
        cells.append(row)
        table.add(math(label, 34, color).move_to([-4.4, y]))
    for r in (1, 2):
        for i, child in enumerate(cells[r]):
            left, right = cells[r - 1][i], cells[r - 1][i + 1]
            top = child.center() + UP * 0.28
            for src in (left, right):
                start = src.center() + DOWN * 0.28
                table.add(PathNode(path=line(start[0], start[1], top[0], top[1]), style=Style(stroke=DIM, stroke_width=2, stroke_opacity=0.55)))
    # 新算出来的数垫淡金底
    for r in (1, 2):
        for cell in cells[r]:
            pad = PathNode(path=rounded_rect(max(cell.width, 0.3) + 0.3, cell.height + 0.2, 0.1), style=Style(fill=MARK), z=-1)
            pad.move_to(cell.center())
            table.add(pad)
    return table


def build():
    root = Group(name="frame")
    card = problem_card()
    card.scale_to_fit_width(12.4).to_edge(UP, margin=0.16)
    card.shift([-card.center()[0], 0.0])
    root.add(card)
    table = diff_table()
    table.move_to([-0.3, -0.9])
    root.add(table)
    caption = Text("墨线 moxian · 第一帧 · Skia 光栅化，中文走字体轮廓，公式走 LaTeX", 22, DIM)
    caption.to_edge(DOWN, margin=0.3).to_edge(LEFT, margin=0.4)
    root.add(caption)
    return root


if __name__ == "__main__":
    out = SkiaRenderer(1920, 1080, background=BG).save_png(build(), "build/first_frame.png")
    print("wrote", out)
