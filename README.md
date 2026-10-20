# 墨线 moxian

[中文](#中文) | [English](#english)

## 中文

> 0.0.x：实验阶段（experimental），接口随时会变。墨线已经是 kit 的默认渲染后端，scene-spec 的示例都由它渲染（见下文「进展」）。

数学讲解视频的矢量动画引擎。名字取自木匠弹线用的墨斗线：专门画精准线条的工具。

墨线是 [scene-spec](https://github.com/animind-ai/scene-spec) 的渲染引擎，目标是取代 [kit](https://github.com/animind-ai/kit) 现在依赖的 Manim。它不是 Manim 的分叉；算法思路有参考，代码是重新写的，个别借用的片段会在文件头注明来源。

### 0.0.1 有什么

| 包 | 内容 |
|---|---|
| `moxian.core` | 对象树（`Node` / `PathNode` / `Group`）、仿射变换、精确包围盒（按贝塞尔曲线极值求）、摆放（`move_to`、`next_to`、`align_to`、`arrange`…）、样式；`Camera` 视图变换（几何缩放，固定层和保持大小的层） |
| `moxian.path` | 统一为三次贝塞尔的矢量路径；常用形状；SVG `d` 解析（含弧）和 dvisvgm 输出用到的那部分 SVG |
| `moxian.text` | 中文文字 → 字形轮廓（Skia 取轮廓，默认 Noto Sans CJK SC，可指定别的字体，支持粗体；标点挤压、中西文间距）；`Paragraph` 按宽度折行，标点不孤立在行首；公式 → 轮廓（latex + dvisvgm，按内容缓存） |
| `moxian.render` | Skia 光栅化后端，输出 PNG 或直接画进内存；Skia 路径按对象缓存、变换交给画布，可只重画脏区 |
| `moxian.anim` | 动画原语（淡入淡出、位移、缩放、长出、样式渐变、划线、变形、`Write` 先描边后填色、`TransformCopy` 字形变形、`CameraMove` 镜头移动）、缓动、时间线；参数驱动（`Param` 数值参数 + `ParamTween` 补间，`Dynamic` 按参数重建的节点、`updater` 按参数更新的回调），参数值是时间的纯函数 |
| `moxian.encode` | 帧序列喂给 ffmpeg 编成视频，可合入音轨；画面没变的帧直接复用上一帧像素 |

坐标系和 Manim 一致：画面高 8 个单位、宽 8×16/9，原点在中心，y 向上；字号和线宽以 1080p 下的像素计。路径统一为三次贝塞尔，变形前先把两条路径对齐成相同结构（补退化子路径、二分最长段）。

### 进展

scene-spec 的编译、布局求解、组件和版式检查在 [kit](https://github.com/animind-ai/kit) 里（`animind_kit/backends/moxian_backend.py`、`animind_kit/mx/`），墨线只负责对象树、动画和出图。下面按时间列出已经跑通的内容，都有提交或成片为证：

| 日期 | 内容 | 出处 |
|---|---|---|
| 2026-10-16 | 第一帧静态画面 | moxian `aa20307`，`examples/first_frame.py` |
| 2026-10-16 | `s67-p01`（scene-spec 第一个示例，高中数列例题第 01 支）的 Down 一段，1080p30 带旁白，27 秒 | moxian `fb1c0bc`，`examples/down_beat.py` |
| 2026-10-16 | kit 的墨线后端：把 scene-spec 编译成墨线对象树；`s67-p01` 整支（约 4.7 分钟）用墨线渲染；`animind-kit compare` 两个后端各渲染一遍、拼出每个 beat 的末帧对照 | kit `143d5d1`、`549b09a` |
| 2026-10-16 | 镜头动作和布局求解（在 kit 的墨线后端里）；`s67-p02` 整支也用墨线渲染 | kit `3656a7f`；`s67-p02` 截图基准 kit `a4ccc82` |
| 2026-10-16 – 17 | 洞察系列 ep09、ep11、ep18、ep21、ep22、ep25、ep30，以及 ep01–ep08、ep09-fractions；分段播放、软字幕、字形级版式检查 | kit `547f1c5`、`80212be`、`0cc49dc`、`69382fb`、`3bb2b9e`、`9ed9ba9` |
| 2026-10-17 – 18 | 新组件在墨线上：方块柱、立体（轴测图、剖分）、天平、概率（抛硬币、高尔顿板）、钱包；参数驱动动画 | kit `7b02584`、`5fe656d`、`32bd8ab`、`6b3f0e5`、`d6214e7`，moxian `b30a36d` |

截图回归：kit 的 `tests/baseline/linux` 有 19 支场景的基准图（s67-p01、s67-p02、ep01–ep09、ep09-fractions、ep11、ep18、ep21、ep22、ep25、ep30、numbers），CI 每次比对。

还没有：OpenGL 后端；墨线本身不读 scene-spec（编译在 kit 里）。

### 参数驱动

```python
from moxian.anim import Dynamic, Param, ParamTween, Timeline, easing

k = Param(1.0, "k")
slope_line = Dynamic(lambda: PathNode(path=line(-3, -3 * k.value, 3, 3 * k.value), style=...), k)
tl = Timeline()
tl.add(1.0, ParamTween(k, 2.0, duration=2.0, ease=easing.smooth))   # k: 1 → 2，直线跟着转
```

参数在时刻 t 的值只取决于 t（同一参数的后一个补间从前一个当时的值接管），所以逐帧 seek、跳着 seek、往回 seek 结果都一样；参数变了 `seek` 就返回 changed，静止帧复用不会漏帧。`Timeline.keyframes()` 给出补间起止时刻，供版式检查采样。

### 跑示例

```bash
uv sync
uv run python examples/first_frame.py   # → build/first_frame.png
uv run python examples/down_beat.py /path/to/p01/audio   # → build/down.mp4，1080p30，带旁白
uv run python examples/zoom_demo.py   # 镜头缩放示例
```

Down 一段 827 帧（1080p30）在 M 系列 Mac 上约 2 秒渲染完（含编码），其中只有 162 帧需要重画。

依赖：Python 3.11/3.12、skia-python、numpy；公式需要 `latex` 和 `dvisvgm`（TeX Live 自带）；中文需要系统装有 Noto Sans CJK SC。

### 开发

```bash
uv run pytest
```

### 作者与许可

作者：Boxi Yu（[@BoxiYu](https://github.com/BoxiYu)）

代码以 [MIT 许可](LICENSE)发布。引用方式见 [CITATION.cff](CITATION.cff)。

## English

> 0.0.x: experimental; the API may change at any time. moxian is now kit's default rendering backend and renders the scene-spec examples (see "Status" below).

A vector animation engine for math explainer videos. The name comes from the carpenter's ink line (墨斗线), a tool made for drawing precise lines.

moxian is the rendering engine for [scene-spec](https://github.com/animind-ai/scene-spec), and is meant to replace Manim, which [kit](https://github.com/animind-ai/kit) currently depends on. It is not a fork of Manim: some algorithmic ideas are borrowed, but the code is rewritten, and the few borrowed snippets note their source in the file header.

### What's in 0.0.1

| Package | Contents |
|---|---|
| `moxian.core` | Object tree (`Node` / `PathNode` / `Group`), affine transforms, exact bounding boxes (from Bézier extrema), placement (`move_to`, `next_to`, `align_to`, `arrange`…), styles; `Camera` view transform (geometric zoom, fixed and keep-size layers) |
| `moxian.path` | Vector paths unified as cubic Béziers; common shapes; SVG `d` parsing (including arcs) and the subset of SVG that dvisvgm output uses |
| `moxian.text` | Chinese text → glyph outlines (outlines via Skia, Noto Sans CJK SC by default, other families selectable, bold supported; punctuation squeeze and CJK–Latin spacing); `Paragraph` wraps by width and keeps punctuation from starting a line; formulas → outlines (latex + dvisvgm, cached by content) |
| `moxian.render` | Skia rasterization backend, outputs PNG or draws straight into memory; Skia paths are cached per object and transforms are left to the canvas, so only dirty regions need redrawing |
| `moxian.anim` | Animation primitives (fade in/out, shift, scale, grow, style tween, stroke drawing, morph, `Write` stroke-then-fill, `TransformCopy` glyph morph, `CameraMove`), easing, timeline; parameter-driven (`Param` numeric parameters + `ParamTween` tweens, `Dynamic` nodes rebuilt from parameters, `updater` callbacks updated from parameters); parameter values are pure functions of time |
| `moxian.encode` | Feeds the frame sequence to ffmpeg to encode a video, optionally muxing in an audio track; frames whose picture did not change reuse the previous frame's pixels |

The coordinate system matches Manim's: the frame is 8 units tall and 8×16/9 wide, the origin is at the center, and y points up; font sizes and stroke widths are in pixels at 1080p. All paths are cubic Béziers; before morphing, the two paths are aligned to the same structure (padding degenerate subpaths, bisecting the longest segment).

### Status

scene-spec compilation, layout solving, widgets and layout checks live in [kit](https://github.com/animind-ai/kit) (`animind_kit/backends/moxian_backend.py`, `animind_kit/mx/`); moxian itself provides the object tree, animation and rendering. What runs today, in date order, each backed by a commit or a rendered video:

| Date | What | Source |
|---|---|---|
| 2026-10-16 | First static frame | moxian `aa20307`, `examples/first_frame.py` |
| 2026-10-16 | The Down segment of `s67-p01` (scene-spec's first example, worked high-school sequence problem no. 01), 1080p30 with narration, 27 s | moxian `fb1c0bc`, `examples/down_beat.py` |
| 2026-10-16 | kit's moxian backend: compiles scene-spec into a moxian tree; the whole `s67-p01` (about 4.7 min) rendered with moxian; `animind-kit compare` renders both backends and stacks each beat's end frame | kit `143d5d1`, `549b09a` |
| 2026-10-16 | Camera action and layout solving (in kit's moxian backend); the whole `s67-p02` also rendered with moxian | kit `3656a7f`; `s67-p02` baselines kit `a4ccc82` |
| 2026-10-16 – 17 | Insight episodes ep09, ep11, ep18, ep21, ep22, ep25, ep30, plus ep01–ep08 and ep09-fractions; segmented playback, soft subtitles, glyph-level layout checks | kit `547f1c5`, `80212be`, `0cc49dc`, `69382fb`, `3bb2b9e`, `9ed9ba9` |
| 2026-10-17 – 18 | New widgets on moxian: block bars, solids (axonometric, dissection), balance, chance (coin flips, Galton board), wallet; parameter-driven animation | kit `7b02584`, `5fe656d`, `32bd8ab`, `6b3f0e5`, `d6214e7`; moxian `b30a36d` |

Screenshot regression: kit's `tests/baseline/linux` holds baselines for 19 scenes (s67-p01, s67-p02, ep01–ep09, ep09-fractions, ep11, ep18, ep21, ep22, ep25, ep30, numbers), checked on every CI run.

Not yet: an OpenGL backend; moxian itself does not read scene-spec (compilation is in kit).

### Parameter-driven animation

```python
from moxian.anim import Dynamic, Param, ParamTween, Timeline, easing

k = Param(1.0, "k")
slope_line = Dynamic(lambda: PathNode(path=line(-3, -3 * k.value, 3, 3 * k.value), style=...), k)
tl = Timeline()
tl.add(1.0, ParamTween(k, 2.0, duration=2.0, ease=easing.smooth))   # k: 1 → 2, the line rotates with it
```

A parameter's value at time t depends only on t (a later tween of the same parameter takes over from the value the earlier one had at that moment), so seeking frame by frame, skipping ahead, or seeking backwards all give the same result; when a parameter changes, `seek` returns changed, so static-frame reuse never drops a frame. `Timeline.keyframes()` gives the start and end times of tweens for layout checks to sample.

### Running the examples

```bash
uv sync
uv run python examples/first_frame.py   # → build/first_frame.png
uv run python examples/down_beat.py /path/to/p01/audio   # → build/down.mp4, 1080p30, with narration
uv run python examples/zoom_demo.py   # camera zoom demo
```

The Down segment is 827 frames (1080p30) and renders in about 2 seconds on an M-series Mac (encoding included); only 162 of those frames need redrawing.

Requirements: Python 3.11/3.12, skia-python, numpy; formulas need `latex` and `dvisvgm` (bundled with TeX Live); Chinese text needs Noto Sans CJK SC installed on the system.

### Development

```bash
uv run pytest
```

### Author and license

Author: Boxi Yu ([@BoxiYu](https://github.com/BoxiYu))

The code is released under the [MIT License](LICENSE). To cite, see [CITATION.cff](CITATION.cff).
