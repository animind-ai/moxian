"""参数驱动：一个数随时间连续变化，依赖它的几何和读数每帧跟着重算。

Manim 里这件事靠 ValueTracker + always_redraw / add_updater；墨线的做法是：

- Param：一个有名字的数。不直接被"推着走"，它在时刻 t 的值由时间线上的补间算出来，
  是 t 的纯函数（seek 到任意时刻、跳着 seek 还是逐帧 seek，结果都一样，也可以往回 seek）。
- ParamTween：一个动画，把参数在 duration 内补间到目标值（带缓动）。和别的动画一样
  用 tl.add / then / with_prev 挂上时间线，也可以包在 together(...) 里。
- Dynamic：一个节点，子节点由 build() 按参数的当前值生成；依赖的参数一变就整棵重建。
- updater(node, fn, *params)：不重建，参数一变就调 fn(node) 改它（fn 要按参数值直接算出状态，
  不要做增量修改，否则跳着 seek 时结果会不一样）。

补间的叠加规则（时间线内）：同一个参数的补间按开始时刻排序（同时开始的按添加顺序），
时刻 t 由最后一个已经开始的补间决定，它从"它开始那一刻参数的值"出发补间到目标；
前一个补间还没播完就被后一个接管。这样参数值只取决于 t，不取决于 seek 的步长。

参数在时间线第一次 seek 时的值是这条时间线的起点（kit 每个 beat 一条时间线，参数跨 beat 保留）。
时间线每帧先更新参数、重建依赖它的节点，再播其他动画，所以同一帧开始的动画看到的是新几何。
参数的值变了，seek 就报告 changed=True，画面不会被当成静止帧复用。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..core import Node
from . import easing
from .animation import Animation, Easing


class Param:
    """一个随时间变化的数。value 是当前值；用 set() 手动改值会立即刷新依赖它的节点。"""

    def __init__(self, value: float = 0.0, name: str = ""):
        self.name = name
        self.value = float(value)
        self._dependents: list[_Dependent] = []

    def set(self, value: float) -> bool:
        """直接改值并刷新依赖它的节点；返回值是否真的变了。"""
        value = float(value)
        if value == self.value:
            return False
        self.value = value
        refresh([self])
        return True

    def __float__(self) -> float:
        return self.value

    def __repr__(self) -> str:
        return f"Param({self.name or '?'}={self.value:g})"


class _Dependent:
    """依赖若干参数的东西：参数变了就 update()。"""

    params: tuple[Param, ...] = ()

    def _register(self, params: Iterable[Param]) -> None:
        self.params = tuple(params)
        for p in self.params:
            if not isinstance(p, Param):
                raise TypeError(f"依赖必须是 Param，收到 {p!r}")
            p._dependents.append(self)
        self._key: tuple[float, ...] | None = None

    def refresh(self) -> bool:
        """参数值和上次不同才更新；返回这次有没有更新。"""
        key = tuple(p.value for p in self.params)
        if key == self._key:
            return False
        self._key = key
        self.update()
        return True

    def update(self) -> None:
        raise NotImplementedError


def refresh(params: Iterable[Param]) -> bool:
    """刷新依赖这些参数的节点（每个只刷新一次）；返回有没有节点被更新。"""
    seen: set[int] = set()
    changed = False
    for p in params:
        for dep in p._dependents:
            if id(dep) not in seen:
                seen.add(id(dep))
                changed |= dep.refresh()
    return changed


class Dynamic(Node, _Dependent):
    """子节点由 build() 生成、参数一变就重建的节点（相当于 Manim 的 always_redraw）。

    build() 返回一个节点或节点列表，成为这个节点的子节点；它应当只读参数的 value，
    每次都生成新的节点（渲染器按路径对象缓存，复用旧节点会画出旧形状）。
    这个节点自己的 matrix、style（淡入淡出、位移）不受重建影响，可以照常做动画。
    注意：Write / Draw 这类在 begin() 时记下子路径的动画，播放期间不要同时改参数。
    """

    def __init__(self, build: Callable[[], Node | list[Node]], *params: Param, name: str = ""):
        Node.__init__(self, name=name)
        self.build = build
        self._register(params)
        self.refresh()

    def update(self) -> None:
        built = self.build()
        self.children = list(built) if isinstance(built, (list, tuple)) else [built]


class _Updater(_Dependent):
    def __init__(self, node: Node, fn: Callable[[Node], None], params: tuple[Param, ...]):
        self.node, self.fn = node, fn
        self._register(params)

    def update(self) -> None:
        self.fn(self.node)


def updater(node: Node, fn: Callable[[Node], None], *params: Param) -> Node:
    """参数一变就调 fn(node)（相当于 Manim 的 add_updater，但只在参数变化时调用）。立即调用一次。"""
    _Updater(node, fn, params).refresh()
    return node


class ParamTween(Animation):
    """在 duration 内把 param 补间到 target。

    挂在时间线上时，参数值由时间线按 t 直接算出（见模块说明），begin / interpolate 不再改参数；
    单独使用（不经时间线）时就是普通动画：begin() 记下起点，interpolate 按 alpha 插值。
    """

    def __init__(self, param: Param, target: float, duration: float = 1.0, ease: Easing = easing.smooth):
        super().__init__(Node(name=f"tween:{param.name}"), duration, ease)
        self.param = param
        self.target = float(target)
        self.managed = False  # True：由时间线负责算值

    def begin(self) -> None:
        super().begin()
        if not self.managed:
            self.start = self.param.value

    def interpolate(self, alpha: float) -> None:
        if not self.managed:
            self.param.set(self.start + (self.target - self.start) * alpha)

    def finish(self) -> None:
        if not self.managed:
            self.param.set(self.target)

    def value(self, start: float, elapsed: float) -> float:
        """从 start 出发、开始 elapsed 秒后的值。"""
        alpha = min(1.0, max(0.0, elapsed / self.duration))
        return start + (self.target - start) * self.ease(alpha)


def tween(params: dict[Param, float], duration: float = 1.0, ease: Easing = easing.smooth) -> list[ParamTween]:
    """同时补间几个参数（同样的时长和缓动）。"""
    return [ParamTween(p, v, duration, ease) for p, v in params.items()]


class Schedule:
    """一条时间线上某个参数的全部补间：(开始时刻, 添加序号, 补间)。值是 t 的纯函数。"""

    def __init__(self, param: Param):
        self.param = param
        self.base: float | None = None  # 时间线第一次 seek 时的值
        self.items: list[tuple[float, int, ParamTween]] = []

    def add(self, start: float, tw: ParamTween) -> None:
        tw.managed = True
        self.items.append((start, len(self.items), tw))
        self.items.sort(key=lambda it: (it[0], it[1]))

    def at(self, t: float) -> float:
        v = self.param.value if self.base is None else self.base
        prev: tuple[float, ParamTween] | None = None
        for start, _n, tw in self.items:
            if start > t:
                break
            if prev is not None:
                v = prev[1].value(v, start - prev[0])  # 这个补间开始时，参数正处在上一个补间的这一刻
            prev = (start, tw)
        if prev is None:
            return v
        return prev[1].value(v, t - prev[0])

    @property
    def end(self) -> float:
        return max((s + tw.duration for s, _n, tw in self.items), default=0.0)
