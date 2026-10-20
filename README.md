# 墨线 moxian

[中文](#中文) | [English](#english)

## 中文

> 0.0.x：实验阶段，接口随时会变；跑通的内容只有 scene-spec 的 §6.7 示例。

数学讲解视频的矢量动画引擎。名字取自木匠弹线用的墨斗线：专门画精准线条的工具。

墨线是 [scene-spec](https://github.com/animind-ai/scene-spec) 的渲染引擎，目标是取代 [kit](https://github.com/animind-ai/kit) 现在依赖的 Manim。它不是 Manim 的分叉；算法思路有参考，代码是重新写的，个别借用的片段会在文件头注明来源。

### 0.0.1 有什么

| 包 | 内容 |
|---|---|
| `moxian.core` | 对象树（`Node` / `PathNode` / `Group`）、仿射变换、包围盒、摆放（`move_to`、`next_to`、`align_to`、`arrange`…）、样式 |
| `moxian.path` | 统一为三次贝塞尔的矢量路径；常用形状；SVG `d` 解析（含弧）和 dvisvgm 输出用到的那部分 SVG |
| `moxian.text` | 中文文字 → 字形轮廓（Skia 取轮廓，默认 Noto Sans CJK SC，支持粗体）；`Paragraph` 按宽度折行，标点不孤立在行首；公式 → 轮廓（latex + dvisvgm，按内容缓存） |
| `moxian.render` | Skia 光栅化后端，输出 PNG 或直接画进内存；Skia 路径按对象缓存、变换交给画布，可只重画脏区 |
| `moxian.anim` | 动画原语（淡入淡出、位移、缩放、长出、样式渐变、划线、变形）、缓动、时间线；参数驱动（`Param` 数值参数 + `ParamTween` 补间，`Dynamic` 按参数重建的节点、`updater` 按参数更新的回调），参数值是时间的纯函数 |
| `moxian.encode` | 帧序列喂给 ffmpeg 编成视频，可合入音轨；画面没变的帧直接复用上一帧像素 |
| `moxian.clip` | 外部画面（`ClipNode`）：mp4/mov 或 PNG/JPEG 帧序列按成片时刻贴进场景，矢量文字和公式画在上面 |

坐标系和 Manim 一致：画面高 8 个单位、宽 8×16/9，原点在中心，y 向上；字号和线宽以 1080p 下的像素计。路径统一为三次贝塞尔，变形前先把两条路径对齐成相同结构（补退化子路径、二分最长段）。

还没有：布局求解、scene-spec 编译（现在的示例是手搭画面）、OpenGL 后端。第一个里程碑是用墨线渲染 scene-spec 的 §6.7 示例整支，和 kit 的 Manim 输出逐帧对比；`examples/down_beat.py` 已经做到了其中的 Down 一段。

### 参数驱动

```python
from moxian.anim import Dynamic, Param, ParamTween, Timeline, easing

k = Param(1.0, "k")
slope_line = Dynamic(lambda: PathNode(path=line(-3, -3 * k.value, 3, 3 * k.value), style=...), k)
tl = Timeline()
tl.add(1.0, ParamTween(k, 2.0, duration=2.0, ease=easing.smooth))   # k: 1 → 2，直线跟着转
```

参数在时刻 t 的值只取决于 t（同一参数的后一个补间从前一个当时的值接管），所以逐帧 seek、跳着 seek、往回 seek 结果都一样；参数变了 `seek` 就返回 changed，静止帧复用不会漏帧。`Timeline.keyframes()` 给出补间起止时刻，供版式检查采样。

### 外部画面（ClipNode）

片段是背景板：实拍、钩子镜头、模拟出来的星系碰撞，都贴在矢量画面下面。文字和公式仍然是墨线的路径节点。片段的音轨不参与合成。

```python
from moxian.anim import Timeline
from moxian.clip import ClipNode
from moxian.core import DOWN, Group
from moxian.encode import render_video
from moxian.render import SkiaRenderer
from moxian.text import Text

plate = ClipNode(
    "footage/galaxy.mp4",
    t_in=1.5, t_out=6.0,   # 源时间轴上的入点、出点（秒），区间 [t_in, t_out)
    rate=1.0, fit="cover", # contain 留边、cover 裁满、stretch 拉满
    end="hold",            # 播完停在最后一帧；"loop" 则循环
    start=0.0,             # 成片里从这一秒开始播
)
# 不给 width/height 时铺满画面。给了就是以节点原点为中心的矩形，再用 move_to / to_edge 摆。
title = Text("星系碰撞", 64).to_edge(DOWN, margin=0.6)
root = Group(plate, title)   # plate.z 默认 -100，字在 z=0，画在上面

renderer = SkiaRenderer(1920, 1080)
renderer.time = 1.5           # 成片 1.5 秒那一帧；同一时刻永远取到同一源帧
renderer.save_png(root, "build/hook.png")
render_video(root, Timeline(), "build/hook.mp4", renderer, fps=30)
```

帧序列同样写，`fps` 必填（单张图可以省略，按一帧处理）：

```python
ClipNode("sim/frame_*.png", fps=24, t_in=0.5, t_out=3.0, rate=0.5, fit="contain", end="loop")
```

源帧 `i` 覆盖源时间 `[i/fps, (i+1)/fps)`。成片时刻 `t` 的源时间是 `t_in + (t - start) * rate`，帧号是 `floor(源时间 * fps)`，跟输出帧率无关，也不靠上一帧累加。输出 30fps、素材 24fps 时，有的成片帧会重复上一张源帧，画面没变就复用像素。早于 `start` 时这块板不画。

帧目录和 glob 按文件名自然排序：`frame_2.png` 在 `frame_10.png` 前面，不是字典序。

| 参数 | 含义 |
|---|---|
| `src` | 视频文件、帧目录，或 glob |
| `kind` | `"video"` 或 `"frames"`，可省略，按路径推断 |
| `t_in`, `t_out` | 修剪，秒。scene-spec 里建议写成 `in` / `out`（`in` 在 Python 里是关键字） |
| `rate` | 播放速率，默认 1 |
| `fps` | 帧序列的帧率；视频默认用容器帧率 |
| `fit` | `contain`（默认）/ `cover` / `stretch` |
| `width`, `height` | 场景单位，矩形中心在节点原点。和 `region` 二选一 |
| `region` | 局部坐标矩形 `(x0, y0, x1, y1)`，y 向上 |
| `opacity` | 片段自己的透明度，再乘上父节点的 opacity |
| `z` | 同级绘制顺序，默认 `-100` |
| `end` | `hold`（默认，停在最后一帧）或 `loop` |
| `start` | 成片时间轴上的开始时刻，秒。早于此时不画 |
| `muted` | 只能为 True；音轨不解码 |

墨线没有单独的静图节点。一张 PNG/JPEG 就是只有一帧的片段，摆放方式和别的节点一样（`local_bbox` 是这块板，`move_to` / `shift` / `scale` 改矩阵）。

### 跑示例

```bash
uv sync
uv run python examples/first_frame.py   # → build/first_frame.png
uv run python examples/down_beat.py /path/to/p01/audio   # → build/down.mp4，1080p30，带旁白
```

Down 一段 827 帧（1080p30）在 M 系列 Mac 上约 2 秒渲染完（含编码），其中只有 162 帧需要重画。

依赖：Python 3.11/3.12、skia-python、numpy；公式需要 `latex` 和 `dvisvgm`（TeX Live 自带）；中文需要系统装有 Noto Sans CJK SC。编码视频、以及 `ClipNode` 解码 mp4/mov，需要 `ffmpeg` 和 `ffprobe`。帧序列只解码图片，不再额外依赖。

### 开发

```bash
uv run pytest
```

### 作者与许可

作者：Boxi Yu（[@BoxiYu](https://github.com/BoxiYu)）

代码以 [MIT 许可](LICENSE)发布。引用方式见 [CITATION.cff](CITATION.cff)。

## English

> 0.0.x: experimental; the API may change at any time. The only content that renders end to end so far is the §6.7 example from scene-spec.

A vector animation engine for math explainer videos. The name comes from the carpenter's ink line (墨斗线), a tool made for drawing precise lines.

moxian is the rendering engine for [scene-spec](https://github.com/animind-ai/scene-spec), and is meant to replace Manim, which [kit](https://github.com/animind-ai/kit) currently depends on. It is not a fork of Manim: some algorithmic ideas are borrowed, but the code is rewritten, and the few borrowed snippets note their source in the file header.

### What's in 0.0.1

| Package | Contents |
|---|---|
| `moxian.core` | Object tree (`Node` / `PathNode` / `Group`), affine transforms, bounding boxes, placement (`move_to`, `next_to`, `align_to`, `arrange`…), styles |
| `moxian.path` | Vector paths unified as cubic Béziers; common shapes; SVG `d` parsing (including arcs) and the subset of SVG that dvisvgm output uses |
| `moxian.text` | Chinese text → glyph outlines (outlines via Skia, Noto Sans CJK SC by default, bold supported); `Paragraph` wraps by width and keeps punctuation from starting a line; formulas → outlines (latex + dvisvgm, cached by content) |
| `moxian.render` | Skia rasterization backend, outputs PNG or draws straight into memory; Skia paths are cached per object and transforms are left to the canvas, so only dirty regions need redrawing |
| `moxian.anim` | Animation primitives (fade in/out, shift, scale, grow, style tween, stroke drawing, morph), easing, timeline; parameter-driven (`Param` numeric parameters + `ParamTween` tweens, `Dynamic` nodes rebuilt from parameters, `updater` callbacks updated from parameters); parameter values are pure functions of time |
| `moxian.encode` | Feeds the frame sequence to ffmpeg to encode a video, optionally muxing in an audio track; frames whose picture did not change reuse the previous frame's pixels |
| `moxian.clip` | External plates (`ClipNode`): an mp4/mov or a PNG/JPEG frame sequence sampled at the scene time, with vector text and math drawn on top |

The coordinate system matches Manim's: the frame is 8 units tall and 8×16/9 wide, the origin is at the center, and y points up; font sizes and stroke widths are in pixels at 1080p. All paths are cubic Béziers; before morphing, the two paths are aligned to the same structure (padding degenerate subpaths, bisecting the longest segment).

Not yet: layout solving, scene-spec compilation (the current examples build frames by hand), an OpenGL backend. The first milestone is to render the whole §6.7 scene-spec example with moxian and compare it frame by frame with kit's Manim output; `examples/down_beat.py` already does the Down segment of it.

### Parameter-driven animation

```python
from moxian.anim import Dynamic, Param, ParamTween, Timeline, easing

k = Param(1.0, "k")
slope_line = Dynamic(lambda: PathNode(path=line(-3, -3 * k.value, 3, 3 * k.value), style=...), k)
tl = Timeline()
tl.add(1.0, ParamTween(k, 2.0, duration=2.0, ease=easing.smooth))   # k: 1 → 2, the line rotates with it
```

A parameter's value at time t depends only on t (a later tween of the same parameter takes over from the value the earlier one had at that moment), so seeking frame by frame, skipping ahead, or seeking backwards all give the same result; when a parameter changes, `seek` returns changed, so static-frame reuse never drops a frame. `Timeline.keyframes()` gives the start and end times of tweens for layout checks to sample.

### External plates (ClipNode)

A clip is a background plate: live footage, a hook shot, or a simulated galaxy collision, composited under the vector picture. Text and formulas stay moxian path nodes. Audio from the clip is never mixed.

```python
from moxian.anim import Timeline
from moxian.clip import ClipNode
from moxian.core import DOWN, Group
from moxian.encode import render_video
from moxian.render import SkiaRenderer
from moxian.text import Text

plate = ClipNode(
    "footage/galaxy.mp4",
    t_in=1.5, t_out=6.0,   # trim in/out on the source timeline, seconds; half-open [t_in, t_out)
    rate=1.0, fit="cover", # contain letterboxes, cover crops, stretch ignores aspect
    end="hold",            # hold the last frame; "loop" wraps
    start=0.0,             # when playback begins on the scene timeline
)
# Omit width/height to fill the frame. Otherwise the rectangle is centered on the node origin;
# place it with move_to / to_edge like any other node.
title = Text("星系碰撞", 64).to_edge(DOWN, margin=0.6)
root = Group(plate, title)   # plate.z defaults to -100, so z=0 text draws on top

renderer = SkiaRenderer(1920, 1080)
renderer.time = 1.5           # the frame at scene time 1.5s; the same time always samples the same source frame
renderer.save_png(root, "build/hook.png")
render_video(root, Timeline(), "build/hook.mp4", renderer, fps=30)
```

A frame sequence is the same call. `fps` is required (a single image may omit it and is treated as one frame):

```python
ClipNode("sim/frame_*.png", fps=24, t_in=0.5, t_out=3.0, rate=0.5, fit="contain", end="loop")
```

Source frame `i` covers source time `[i/fps, (i+1)/fps)`. At scene time `t` the source time is `t_in + (t - start) * rate`, and the frame index is `floor(source_time * fps)`. It does not depend on the output frame rate, and it is not accumulated from the previous frame. At 30fps output and 24fps footage, some output frames repeat a source frame; unchanged pictures reuse pixels. Before `start`, the plate is not drawn.

A directory or glob of frames is ordered by a natural sort of the filename: `frame_2.png` comes before `frame_10.png`.

| Parameter | Meaning |
|---|---|
| `src` | A video file, a directory of frames, or a glob |
| `kind` | `"video"` or `"frames"`; inferred from the path when omitted |
| `t_in`, `t_out` | Trim, in seconds. In scene-spec YAML, prefer `in` / `out` (`in` is a Python keyword) |
| `rate` | Playback rate, default 1 |
| `fps` | Frame-sequence rate; video defaults to the container rate |
| `fit` | `contain` (default) / `cover` / `stretch` |
| `width`, `height` | Scene units, rectangle centered on the node origin. Mutually exclusive with `region` |
| `region` | Local rectangle `(x0, y0, x1, y1)`, y up |
| `opacity` | The plate's own opacity, multiplied by ancestor opacity |
| `z` | Sibling draw order, default `-100` |
| `end` | `hold` (default; keep the last frame) or `loop` |
| `start` | Scene time when playback begins, in seconds. Nothing is drawn before it |
| `muted` | Must be true; the audio track is not decoded |

There is no separate still-image node. One PNG or JPEG is a one-frame clip, placed like any other node (`local_bbox` is the plate; `move_to` / `shift` / `scale` edit the matrix).

### Running the examples

```bash
uv sync
uv run python examples/first_frame.py   # → build/first_frame.png
uv run python examples/down_beat.py /path/to/p01/audio   # → build/down.mp4, 1080p30, with narration
```

The Down segment is 827 frames (1080p30) and renders in about 2 seconds on an M-series Mac (encoding included); only 162 of those frames need redrawing.

Requirements: Python 3.11/3.12, skia-python, numpy; formulas need `latex` and `dvisvgm` (bundled with TeX Live); Chinese text needs Noto Sans CJK SC installed on the system. Encoding a video, and decoding mp4/mov with `ClipNode`, needs `ffmpeg` and `ffprobe`. Frame sequences only decode images and add no further dependency.

### Development

```bash
uv run pytest
```

### Author and license

Author: Boxi Yu ([@BoxiYu](https://github.com/BoxiYu))

The code is released under the [MIT License](LICENSE). To cite, see [CITATION.cff](CITATION.cff).
