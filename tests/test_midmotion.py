"""中途采样：Animation.sample_alphas 和 Timeline.samples()。"""

import pytest

from moxian.anim import (
    MIDMOTION,
    Animation,
    Param,
    ParamTween,
    Shift,
    Timeline,
    TransformCopy,
    Wait,
    easing,
    fade_in,
    together,
)
from moxian.core import Group, Node


def test_default_is_no_sampling():
    assert Animation(Node()).sample_alphas == ()
    assert Shift(Node(), [1, 0]).sample_alphas == ()
    assert fade_in(Node()).sample_alphas == ()
    assert Wait(1.0).sample_alphas == ()
    assert TransformCopy([Group()], Group(), Group()).sample_alphas == ()
    assert together(Shift(Node(), [1, 0])).sample_alphas == ()


def test_param_tween_is_sampled_by_default():
    tw = ParamTween(Param(0.0), 1.0)
    assert tw.sample_alphas == MIDMOTION == (0.25, 0.5, 0.75)


def test_marking_validates_sorts_and_dedupes():
    a = Shift(Node(), [1, 0])
    assert a.sampled() is a and a.sample_alphas == MIDMOTION
    a.sample_alphas = [0.5, 0.1, 0.5]
    assert a.sample_alphas == (0.1, 0.5)
    for bad in ([0.0], [1.0], [0.5, 1.2], [-0.1]):
        with pytest.raises(ValueError):
            a.sample_alphas = bad
    assert a.sample_alphas == (0.1, 0.5)  # 失败的赋值不改原值
    a.sample_alphas = ()
    assert a.sample_alphas == ()
    assert Shift(Node(), [1, 0]).sample_alphas == ()  # 不影响别的实例


def times(tl: Timeline) -> list[float]:
    return [round(s.time, 9) for s in tl.samples()]


def test_samples_sequential_use_timeline_time_not_eased_alpha():
    tl = Timeline()
    a = tl.add(1.0, Shift(Node(), [1, 0], duration=2.0, ease=easing.smooth).sampled())
    b = tl.then(Shift(Node(), [1, 0], duration=1.0).sampled((0.5,)))
    tl.add(0.0, Shift(Node(), [1, 0], duration=5.0))  # 没标：不采样
    out = tl.samples()
    assert times(tl) == [1.5, 2.0, 2.5, 3.5]
    assert [(s.alpha, s.anim) for s in out] == [(0.25, a), (0.5, a), (0.75, a), (0.5, b)]


def test_samples_overlapping_are_merged_at_equal_times():
    tl = Timeline()
    a = tl.add(0.0, Shift(Node(), [1, 0], duration=2.0).sampled())  # 0.5 1.0 1.5
    b = tl.add(0.5, Shift(Node(), [1, 0], duration=1.0).sampled((0.5,)))  # 1.0
    c = tl.add(0.0, Shift(Node(), [1, 0], duration=2.0).sampled((0.5,)))  # 1.0
    out = tl.samples()
    assert times(tl) == [0.5, 1.0, 1.5]
    assert out[1].sources == ((0.5, a), (0.5, b), (0.5, c))
    assert out[1].anim is a and out[1].alpha == 0.5


def test_samples_reach_into_together_with_child_durations():
    tl = Timeline()
    k = Param(0.0, "k")
    short = Shift(Node(), [1, 0], duration=0.4).sampled((0.5,))
    tw = ParamTween(k, 1.0, 2.0)
    tl.add(1.0, together(fade_in(Node()), short, tw))
    out = tl.samples()
    assert times(tl) == [1.2, 1.5, 2.0, 2.5]
    assert out[0].anim is short and {s.anim for s in out[1:]} == {tw}
    # 组合本身标了也算，按组合的时长
    tl2 = Timeline()
    tl2.add(0.0, together(Shift(Node(), [1, 0], duration=1.0)).sampled((0.5,)))
    assert times(tl2) == [0.5]


class _Seq(Animation):
    """测试用的组合动画：子动画按给定的相对开始时刻排开（together 的子动画都从 0 开始，测不到偏移）。"""

    def __init__(self, *timed: tuple[float, Animation]):
        super().__init__(Node(), max(o + a.duration for o, a in timed), easing.linear)
        self.timed = list(timed)

    def interpolate(self, alpha: float) -> None:
        pass

    def children(self) -> list[tuple[float, Animation]]:
        return self.timed


def test_samples_use_nonzero_child_offsets_in_nested_composites():
    inner = Shift(Node(), [1, 0], duration=1.0).sampled((0.5,))  # 内层偏移 0.5
    deep = Shift(Node(), [1, 0], duration=2.0).sampled((0.25,))  # 在 together 里，together 偏移 2
    tl = Timeline()
    tl.add(1.0, _Seq((0.0, fade_in(Node())),
                     (1.0, _Seq((0.5, inner))),
                     (2.0, together(Shift(Node(), [1, 0], duration=0.3), deep))))
    out = tl.samples()
    # inner：1 + 1 + 0.5 + 0.5×1 = 3.0；deep：1 + 2 + 0.25×2 = 3.5
    assert times(tl) == [3.0, 3.5]
    assert [s.anim for s in out] == [inner, deep]


def test_keyframes_unchanged_and_empty_timeline():
    assert Timeline().samples() == []
    k = Param(0.0, "k")
    tl = Timeline()
    tl.add(1.0, ParamTween(k, 1.0, 2.0))
    tl.add(0.0, Shift(Node(), [1, 0], duration=4.0).sampled())
    assert tl.keyframes() == [0.0, 1.0, 2.0, 3.0, 4.0]  # 只有参数补间的起中止 + 0 和结束
    assert times(tl) == [1.0, 1.5, 2.0, 2.5, 3.0]


def test_sampled_tween_still_seeks_the_same():
    k = Param(0.0, "k")
    tl = Timeline()
    tl.add(0.0, ParamTween(k, 4.0, 2.0, easing.linear))
    for s in tl.samples():
        tl.seek(s.time)
        assert k.value == pytest.approx(4.0 * s.alpha)
