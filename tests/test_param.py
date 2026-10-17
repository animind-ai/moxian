"""参数驱动：Param / ParamTween / Dynamic / updater 和时间线的 seek 语义。"""

import numpy as np
import pytest

from moxian.anim import Dynamic, Param, ParamTween, Shift, Timeline, easing, fade_in, together, tween, updater
from moxian.core import Group, PathNode, Style
from moxian.core import transform as T
from moxian.path import line, rect


def _line_for(k: Param) -> Dynamic:
    return Dynamic(lambda: PathNode(path=line(-1, -k.value, 1, k.value), style=Style(stroke="#000000")), k, name="ln")


def test_tween_is_a_pure_function_of_time():
    k = Param(1.0, "k")
    tl = Timeline()
    tl.add(1.0, ParamTween(k, 3.0, 2.0, easing.linear))
    tl.add(4.0, ParamTween(k, 0.0, 1.0, easing.linear))
    steps = {}
    for t in tl.frames(fps=10, until=6):
        tl.seek(t)
        steps[round(t, 3)] = k.value
    assert steps[0.0] == 1.0 and steps[2.0] == pytest.approx(2.0) and steps[3.5] == 3.0
    assert steps[4.5] == pytest.approx(1.5) and steps[6.0] == 0.0
    # 跳着 seek、往回 seek，同一时刻的值都一样
    k2 = Param(1.0, "k")
    tl2 = Timeline()
    tl2.add(1.0, ParamTween(k2, 3.0, 2.0, easing.linear))
    tl2.add(4.0, ParamTween(k2, 0.0, 1.0, easing.linear))
    for t in (5.5, 2.0, 4.5, 0.0, 3.5):
        tl2.seek(t)
        assert k2.value == pytest.approx(steps[t])


def test_later_tween_takes_over_from_where_the_param_is():
    k = Param(0.0)
    tl = Timeline()
    tl.add(0.0, ParamTween(k, 10.0, 2.0, easing.linear))
    tl.add(1.0, ParamTween(k, 0.0, 1.0, easing.linear))  # 第一个播到一半（值 5）就被接管
    tl.seek(1.0)
    assert k.value == pytest.approx(5.0)
    tl.seek(1.5)
    assert k.value == pytest.approx(2.5)
    tl.seek(3.0)
    assert k.value == 0.0
    # 逐帧和一步到位结果一样
    k2 = Param(0.0)
    tl2 = Timeline()
    tl2.add(0.0, ParamTween(k2, 10.0, 2.0, easing.linear))
    tl2.add(1.0, ParamTween(k2, 0.0, 1.0, easing.linear))
    tl2.seek(1.5)
    assert k2.value == pytest.approx(2.5)


def test_easing_and_base_value_carry_over():
    k = Param(2.0)
    tl = Timeline()
    tl.add(0.0, ParamTween(k, 4.0, 1.0, easing.smooth))
    tl.seek(0.25)
    assert k.value == pytest.approx(2.0 + 2.0 * easing.smooth(0.25))
    tl.seek(2.0)
    assert k.value == 4.0
    # 下一条时间线（下一个 beat）从 4 出发
    tl2 = Timeline()
    tl2.add(0.0, ParamTween(k, 5.0, 1.0, easing.linear))
    tl2.seek(0.5)
    assert k.value == pytest.approx(4.5)
    assert tl2.param_at(k, 0.0) == 4.0


def test_tweens_inside_together_are_found():
    k, b = Param(0.0), Param(0.0)
    node = PathNode(path=rect(1, 1), style=Style(fill="#000000"))
    tl = Timeline()
    tl.add(1.0, together(fade_in(node, 0.5), *tween({k: 1.0, b: -1.0}, 2.0, easing.linear)))
    tl.seek(2.0)
    assert k.value == pytest.approx(0.5) and b.value == pytest.approx(-0.5)
    assert tl.keyframes() == [0.0, 1.0, 2.0, 3.0]


def test_dynamic_rebuilds_only_when_params_change():
    k = Param(1.0)
    calls = []

    def build():
        calls.append(k.value)
        return PathNode(path=line(0, 0, 1, k.value), style=Style(stroke="#000000"))

    dyn = Dynamic(build, k)
    assert calls == [1.0] and dyn.bbox().y1 == pytest.approx(1.0)
    tl = Timeline()
    tl.add(1.0, ParamTween(k, 2.0, 1.0, easing.linear))
    assert tl.seek(0.5) is False  # 参数没动、没有动画在播：可以复用上一帧
    assert calls == [1.0]
    assert tl.seek(1.5) is True
    assert dyn.bbox().y1 == pytest.approx(1.5) and calls == [1.0, 1.5]
    tl.seek(2.5)
    assert dyn.bbox().y1 == pytest.approx(2.0)
    n = len(calls)
    assert tl.seek(3.0) is False and len(calls) == n


def test_dynamic_keeps_its_own_matrix_and_style():
    k = Param(1.0)
    dyn = _line_for(k)
    root = Group(dyn)
    tl = Timeline()
    tl.add(0.0, fade_in(dyn, 1.0))
    tl.add(0.0, Shift(dyn, [2.0, 0.0], 1.0))
    tl.add(0.0, ParamTween(k, 2.0, 1.0))
    tl.seek(1.0)
    box = dyn.world_bbox(root)
    assert box.x0 == pytest.approx(1.0) and box.y1 == pytest.approx(2.0)
    assert dyn.style.opacity == 1.0


def test_updater_and_manual_set():
    t = Param(0.0)
    dot = PathNode(path=rect(0.1, 0.1), style=Style(fill="#000000"))
    updater(dot, lambda n: setattr(n, "matrix", T.translate(t.value, t.value ** 2)), t)
    assert np.allclose(dot.center(), [0, 0])
    assert t.set(2.0) is True
    assert np.allclose(dot.center(), [2, 4])
    assert t.set(2.0) is False


def test_standalone_tween_without_timeline():
    k = Param(1.0)
    dyn = _line_for(k)
    tw = ParamTween(k, 3.0, 1.0, easing.linear)
    tw.begin()
    tw.interpolate(0.5)
    assert k.value == 2.0 and dyn.bbox().y1 == pytest.approx(2.0)
    tw.finish()
    assert k.value == 3.0


def test_easing_by_name():
    assert easing.by_name("linear")(0.3) == 0.3
    with pytest.raises(ValueError):
        easing.by_name("bounce")
    with pytest.raises(TypeError):
        Dynamic(lambda: PathNode(), 3.0)
