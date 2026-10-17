# 墨线 moxian

> 0.0.x：实验阶段，接口随时会变；跑通的内容只有 scene-spec 的 §6.7 示例。

数学讲解视频的矢量动画引擎。名字取自木匠弹线用的墨斗线：专门画精准线条的工具。

墨线是 [scene-spec](https://github.com/animind-ai/scene-spec) 的渲染引擎，目标是取代 [kit](https://github.com/animind-ai/kit) 现在依赖的 Manim。它不是 Manim 的分叉；算法思路有参考，代码是重新写的，个别借用的片段会在文件头注明来源。

## 0.0.1 有什么

| 包 | 内容 |
|---|---|
| `moxian.core` | 对象树（`Node` / `PathNode` / `Group`）、仿射变换、包围盒、摆放（`move_to`、`next_to`、`align_to`、`arrange`…）、样式 |
| `moxian.path` | 统一为三次贝塞尔的矢量路径；常用形状；SVG `d` 解析（含弧）和 dvisvgm 输出用到的那部分 SVG |
| `moxian.text` | 中文文字 → 字形轮廓（Skia 取轮廓，默认 Noto Sans CJK SC，支持粗体）；`Paragraph` 按宽度折行，标点不孤立在行首；公式 → 轮廓（latex + dvisvgm，按内容缓存） |
| `moxian.render` | Skia 光栅化后端，输出 PNG 或直接画进内存；Skia 路径按对象缓存、变换交给画布，可只重画脏区 |
| `moxian.anim` | 动画原语（淡入淡出、位移、缩放、长出、样式渐变、划线、变形）、缓动、时间线；参数驱动（`Param` 数值参数 + `ParamTween` 补间，`Dynamic` 按参数重建的节点、`updater` 按参数更新的回调），参数值是时间的纯函数 |
| `moxian.encode` | 帧序列喂给 ffmpeg 编成视频，可合入音轨；画面没变的帧直接复用上一帧像素 |

坐标系和 Manim 一致：画面高 8 个单位、宽 8×16/9，原点在中心，y 向上；字号和线宽以 1080p 下的像素计。路径统一为三次贝塞尔，变形前先把两条路径对齐成相同结构（补退化子路径、二分最长段）。

还没有：布局求解、scene-spec 编译（现在的示例是手搭画面）、OpenGL 后端。第一个里程碑是用墨线渲染 scene-spec 的 §6.7 示例整支，和 kit 的 Manim 输出逐帧对比；`examples/down_beat.py` 已经做到了其中的 Down 一段。

## 参数驱动

```python
from moxian.anim import Dynamic, Param, ParamTween, Timeline, easing

k = Param(1.0, "k")
slope_line = Dynamic(lambda: PathNode(path=line(-3, -3 * k.value, 3, 3 * k.value), style=...), k)
tl = Timeline()
tl.add(1.0, ParamTween(k, 2.0, duration=2.0, ease=easing.smooth))   # k: 1 → 2，直线跟着转
```

参数在时刻 t 的值只取决于 t（同一参数的后一个补间从前一个当时的值接管），所以逐帧 seek、跳着 seek、往回 seek 结果都一样；参数变了 `seek` 就返回 changed，静止帧复用不会漏帧。`Timeline.keyframes()` 给出补间起止时刻，供版式检查采样。

## 跑示例

```bash
uv sync
uv run python examples/first_frame.py   # → build/first_frame.png
uv run python examples/down_beat.py /path/to/p01/audio   # → build/down.mp4，1080p30，带旁白
```

Down 一段 827 帧（1080p30）在 M 系列 Mac 上约 2 秒渲染完（含编码），其中只有 162 帧需要重画。

依赖：Python 3.11/3.12、skia-python、numpy；公式需要 `latex` 和 `dvisvgm`（TeX Live 自带）；中文需要系统装有 Noto Sans CJK SC。

## 开发

```bash
uv run pytest
```

## 作者与许可

作者：Boxi Yu（[@BoxiYu](https://github.com/BoxiYu)）

代码以 [MIT 许可](LICENSE)发布。
