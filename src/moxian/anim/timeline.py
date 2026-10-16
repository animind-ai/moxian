"""时间线：把动画挂在绝对时刻上，按帧推进。

用法：
    tl = Timeline()
    tl.add(0.3, fade_in(title))
    tl.add(2.0, Shift(title, [0, 1]))
    for t in tl.frames(fps=30):
        tl.seek(t)        # 把所有节点推进到时刻 t
        renderer.render(root)

seek 只能向前。动画在开始时刻 begin()，结束时刻 finish()，之间按缓动插值。
同一时刻开始的多个动画互不影响；先加的先 begin。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .animation import Animation


@dataclass
class _Item:
    start: float
    anim: Animation
    state: str = "pending"  # pending | running | done

    @property
    def end(self) -> float:
        return self.start + self.anim.duration


@dataclass
class Timeline:
    items: list[_Item] = field(default_factory=list)
    cursor: float = 0.0  # 顺序追加时的"当前时刻"

    def add(self, start: float, anim: Animation) -> Animation:
        self.items.append(_Item(start, anim))
        self.cursor = max(self.cursor, start + anim.duration)
        return anim

    def then(self, anim: Animation) -> Animation:
        """接在目前最晚结束的动画后面。"""
        return self.add(self.cursor, anim)

    def with_prev(self, anim: Animation) -> Animation:
        """和上一个动画同时开始。"""
        start = self.items[-1].start if self.items else 0.0
        return self.add(start, anim)

    @property
    def end(self) -> float:
        return max((i.end for i in self.items), default=0.0)

    def seek(self, t: float) -> bool:
        """推进到时刻 t。返回这次有没有动画改变了画面（没有就可以复用上一帧）。"""
        changed = False
        for item in sorted(self.items, key=lambda i: (i.start, 0)):
            if item.state == "done":
                continue
            if t < item.start:
                continue
            if item.state == "pending":
                item.anim.begin()
                item.state = "running"
            alpha = (t - item.start) / item.anim.duration
            if alpha >= 1.0:
                item.anim.finish()
                item.state = "done"
            else:
                item.anim.interpolate(item.anim.ease(alpha))
            changed = True
        return changed

    def frames(self, fps: int = 30, until: float | None = None):
        total = self.end if until is None else max(until, self.end)
        n = int(round(total * fps)) + 1
        for k in range(n):
            yield k / fps
