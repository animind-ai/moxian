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

参数补间（ParamTween，见 param.py）例外：时间线把它们按参数收集起来，参数在时刻 t 的值直接按 t 算，
和 seek 的步长无关，也可以往回 seek。每次 seek 先更新参数、重建依赖它们的节点，再播其他动画。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .animation import Animation
from .param import Param, ParamTween, Schedule, refresh


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
    schedules: dict[int, Schedule] = field(default_factory=dict)  # id(参数) → 它在这条时间线上的补间

    def add(self, start: float, anim: Animation) -> Animation:
        self.items.append(_Item(start, anim))
        self.cursor = max(self.cursor, start + anim.duration)
        for offset, sub in _flatten(anim):
            if isinstance(sub, ParamTween):
                sched = self.schedules.get(id(sub.param))
                if sched is None:
                    sched = self.schedules[id(sub.param)] = Schedule(sub.param)
                sched.add(start + offset, sub)
        return anim

    def params(self) -> list[Param]:
        return [s.param for s in self.schedules.values()]

    def param_at(self, param: Param, t: float) -> float:
        """参数在时刻 t 的值（不改参数本身）。"""
        sched = self.schedules.get(id(param))
        return param.value if sched is None else sched.at(t)

    def _seek_params(self, t: float) -> bool:
        moved: list[Param] = []
        for sched in self.schedules.values():
            if sched.base is None:
                sched.base = sched.param.value
            v = sched.at(t)
            if v != sched.param.value:
                sched.param.value = v
                moved.append(sched.param)
        if moved:
            refresh(moved)
        return bool(moved)

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

    def keyframes(self) -> list[float]:
        """参数补间的起止时刻（排好序、去重）：版式检查按这些时刻采样。"""
        times = {0.0, self.end}
        for sched in self.schedules.values():
            for start, _n, tw in sched.items:
                times |= {start, start + tw.duration / 2, start + tw.duration}
        return sorted(times)

    def seek(self, t: float) -> bool:
        """推进到时刻 t。返回这次有没有动画改变了画面（没有就可以复用上一帧）。"""
        changed = self._seek_params(t)
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


def _flatten(anim: Animation, offset: float = 0.0):
    """动画及其子动画（together 里的），连同相对开始时刻。"""
    yield offset, anim
    for sub_offset, sub in anim.children():
        yield from _flatten(sub, offset + sub_offset)
