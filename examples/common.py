"""示例共用的画面零件：草稿纸配色、混排行、题卡、差分表、步骤胶囊。

这些以后会变成 kit 的组件（由 scene-spec 编译出来）；现在先手搭，用来验证引擎本身。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from moxian.core import DOWN, LEFT, RIGHT, UP, Group, Node, PathNode, Style, arrange
from moxian.path import line, rect, rounded_rect
from moxian.text import Text, math

# palette · paper
BG, FG, A, B, C, HL, HL_INK, DIM = "#F7F3EA", "#1E2430", "#2563A8", "#2F7D5B", "#C2561F", "#FFD84D", "#B7860B", "#9AA0A8"
CARD, MARK = "#EDE6D8", "#F1DDB5"


def inline(parts, gap=0.06) -> Group:
    """把若干 Text / Tex 排成一行：公式按 x 高度对齐到文字。"""
    row = Group(*parts)
    for prev, node in zip(parts, parts[1:]):
        node.next_to(prev, RIGHT, gap)
    base = next(p for p in parts if isinstance(p, Text))
    for node in parts:
        if node is base:
            continue
        if isinstance(node, Text):
            node.align_to(base, DOWN)
        else:
            target_y = base.edge(DOWN)[1] + base.x_height / 2 + 0.02
            node.shift([0.0, target_y - node.center()[1]])
    return row


@dataclass
class Card:
    node: Group
    spans: dict[str, Node] = field(default_factory=dict)


def problem_card() -> Card:
    key = Text("它的二阶差数列是等差数列", 30, FG)
    ask = math(r"A_8 = ", 30, HL_INK)
    blank = math(r"\underline{\hspace{3em}}", 30, FG)
    b_def = math(r"b_n = A_{n+1} - A_n", 30, B)
    c_def = math(r"c_n = b_{n+1} - b_n", 30, C)
    terms = math(r"2, 5, 11, 21, 36, \cdots", 30, A)
    l1 = inline([Text("定义：对数列 ", 30, FG), math(r"\{A_n\}", 30, FG), Text("，令 ", 30, FG), b_def,
                 Text("，则 ", 30, FG), math(r"\{b_n\}", 30, FG), Text(" 称为一阶差数列；", 30, FG)])
    l2 = inline([Text("再令 ", 30, FG), c_def, Text("，则 ", 30, FG), math(r"\{c_n\}", 30, FG), Text(" 称为二阶差数列．", 30, FG)])
    l3 = inline([Text("已知 ", 30, FG), math(r"\{A_n\}", 30, FG), Text(" 为 ", 30, FG), terms,
                 Text("，且", 30, FG), key, Text("，则 ", 30, FG), ask, blank])
    lines = [l1, l2, l3]
    arrange(lines, DOWN, gap=0.2, align=LEFT)
    body = Group(*lines)
    w, h = body.width + 0.6, body.height + 0.42
    bg = PathNode(path=rounded_rect(w, h, 0.14), style=Style(fill=CARD))
    bar = PathNode(path=rect(0.08, h - 0.24), style=Style(fill=HL_INK))
    card = Group(bg, bar, body)
    bg.move_to(body.center())
    bar.move_to([bg.edge(LEFT)[0] + 0.14, bg.center()[1]])
    return Card(card, {"b_def": b_def, "c_def": c_def, "terms": terms, "key": key, "ask": ask, "blank": blank})


def pin_top(node: Node, width: float = 12.4, max_height: float = 2.5) -> Node:
    node.scale_to_fit_width(width)
    if node.height > max_height:
        node.scale_to_fit_height(max_height)
    node.to_edge(UP, margin=0.16)
    return node.shift([-node.center()[0], 0.0])


@dataclass
class DiffTable:
    node: Group
    cells: list[list[Node]]  # 每行的数
    links: list[list[Group]]  # links[r-1][i]：第 r 行第 i 个数上方的两条连线
    pads: list[list[Node]]  # pads[r-1][i]：垫色


def diff_table(rows, known, col=1.36, rowh=1.17) -> DiffTable:
    """rows = [(values, color, label_tex), ...]；known = 每行一开始显示几个数，其余先隐藏。"""
    table = Group()
    cells: list[list[Node]] = []
    n = len(rows[0][0])
    for r, (values, color, label) in enumerate(rows):
        y = -r * rowh
        row = []
        for i, v in enumerate(values):
            m = math(str(v), 42, color).move_to([-(n - 1) / 2 * col + i * col + r * col / 2, y])
            if i >= known[r]:
                m.set_style(opacity=0.0)
            row.append(m)
        cells.append(row)
        table.add(math(label, 34, color).move_to([-(n - 1) / 2 * col - 1.25, y]))
    links: list[list[Group]] = []
    pads: list[list[Node]] = []
    for r in range(1, len(rows)):
        row_links, row_pads = [], []
        for i, child in enumerate(cells[r]):
            left, right = cells[r - 1][i], cells[r - 1][i + 1]
            top = child.center() + UP * 0.28
            pair = Group()
            for src, dx in ((left, 0.08), (right, -0.08)):
                start = src.center() + DOWN * 0.28 + RIGHT * dx
                pair.add(PathNode(path=line(start[0], start[1], top[0], top[1])))
            pair.style = Style(stroke=DIM, stroke_width=2, stroke_opacity=0.55, opacity=1.0 if i < known[r] else 0.0)
            pad = PathNode(path=rounded_rect(max(child.width, 0.3) + 0.3, child.height + 0.2, 0.1),
                           style=Style(fill=MARK, opacity=1.0 if i < known[r] else 0.0), z=-1)
            pad.move_to(child.center())
            row_links.append(pair)
            row_pads.append(pad)
            table.add(pair, pad)
        links.append(row_links)
        pads.append(row_pads)
    for row in cells:
        table.add(*row)
    return DiffTable(table, cells, links, pads)


@dataclass
class Chips:
    node: Group
    bgs: list[PathNode]
    labels: list[Text]


def chips(items, ink=A) -> Chips:
    bgs, labels, group = [], [], Group()
    for text in items:
        label = Text(text, 22, ink)
        bg = PathNode(path=rounded_rect(label.width + 0.4, 0.5, 0.25), style=Style(fill=CARD))
        bg.move_to(label.center())
        chip = Group(bg, label)
        bgs.append(bg)
        labels.append(label)
        group.add(chip)
    arrange(list(group), RIGHT, gap=0.3)
    return Chips(group, bgs, labels)


def surrounding(node: Node, root: Node, color=HL_INK, buff=0.08, radius=0.08, width=2.5) -> PathNode:
    """框住 node；返回的节点要加到 root 下（坐标按 root 算）。"""
    box = node.world_bbox(root)
    rect_node = PathNode(path=rounded_rect(box.width + 2 * buff, box.height + 2 * buff, radius),
                         style=Style(stroke=color, stroke_width=width))
    return rect_node.move_to(box.center)


def underline(node: Node, root: Node, color=HL_INK, width=4.0) -> PathNode:
    box = node.world_bbox(root)
    y = box.y0 - 0.06
    return PathNode(path=line(box.x0, y, box.x1, y), style=Style(stroke=color, stroke_width=width))
