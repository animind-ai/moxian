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

中途采样：标了 sample_alphas 的动画（参数补间默认标了）在 samples() 里给出它们播到一半之类的时刻，
版式检查可以在那里看一眼；keyframes() 还是只管参数补间的起点、中点、终点，和以前一样。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .animation import Animation
from .param import Param, ParamTween, Schedule, refresh


@dataclass
class MidSample:
    """Timeline.samples() 的一项：时刻 time，以及哪些动画在这一刻播到了自己的哪个采样点。"""

    time: float
    sources: tuple[tuple[float, Animation], ...]  # (alpha, 动画)，按加入时间线的顺序

    @property
    def alpha(self) -> float:
        return self.sources[0][0]

    @property
    def anim(self) -> Animation:
        return self.sources[0][1]


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

    def samples(self) -> list[MidSample]:
        """中途采样点：每个标了 sample_alphas 的动画在 开始 + alpha × 时长 处（时间线时刻，不是缓动后的 alpha）。

        组合动画（together 等通过 children() 暴露子动画的）展开到每个子动画，子动画按它自己的开始时刻和时长算；
        组合动画本身标了也算（按组合的时长）。没有暴露子动画的包装（例如 kit 的叠加层入场）看不到里面。
        同一时刻（差 1e-9 以内）只给一条，sources 记下所有落在这一刻的 (alpha, 动画)；按时刻排序。
        """
        found: list[tuple[float, float, Animation]] = []
        for item in self.items:
            for offset, sub in _flatten(item.anim):
                for a in sub.sample_alphas:
                    found.append((item.start + offset + a * sub.duration, a, sub))
        found.sort(key=lambda f: f[0])
        out: list[MidSample] = []
        for t, a, sub in found:
            if out and t - out[-1].time <= 1e-9:
                if not any(s is sub and x == a for x, s in out[-1].sources):
                    out[-1].sources += ((a, sub),)
                continue
            out.append(MidSample(t, ((a, sub),)))
        return out

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
