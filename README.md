# 墨线 moxian

数学讲解视频的矢量动画引擎。名字取自木匠弹线用的墨斗线：专门画精准线条的工具。

墨线是 [scene-spec](https://github.com/animind-ai/scene-spec) 的渲染引擎，目标是取代 [kit](https://github.com/animind-ai/kit) 现在依赖的 Manim。它不是 Manim 的分叉；算法思路有参考，代码是重新写的，个别借用的片段会在文件头注明来源。

## 0.0.1 有什么

| 包 | 内容 |
|---|---|
| `moxian.core` | 对象树（`Node` / `PathNode` / `Group`）、仿射变换、包围盒、摆放（`move_to`、`next_to`、`align_to`、`arrange`…）、样式 |
| `moxian.path` | 统一为三次贝塞尔的矢量路径；常用形状；SVG `d` 解析（含弧）和 dvisvgm 输出用到的那部分 SVG |
| `moxian.text` | 中文文字 → 字形轮廓（Skia 取轮廓，默认 Noto Sans CJK SC）；公式 → 轮廓（latex + dvisvgm，按内容缓存） |
| `moxian.render` | Skia 光栅化后端，输出 PNG |

坐标系和 Manim 一致：画面高 8 个单位、宽 8×16/9，原点在中心，y 向上；字号和线宽以 1080p 下的像素计。

还没有：动画与时间线、布局求解、视频编码、OpenGL 后端。它们按 [ROADMAP](../../ROADMAP.md) 的顺序来，第一个里程碑是用墨线渲染 scene-spec 的 §6.7 示例，和 kit 的 Manim 输出逐帧对比。

## 跑第一帧

```bash
uv sync
uv run python examples/first_frame.py   # → build/first_frame.png
```

依赖：Python 3.11/3.12、skia-python、numpy；公式需要 `latex` 和 `dvisvgm`（TeX Live 自带）；中文需要系统装有 Noto Sans CJK SC。

## 开发

```bash
uv run pytest
```

## 作者与许可

作者：Boxi Yu（[@BoxiYu](https://github.com/BoxiYu)）

代码以 [MIT 许可](LICENSE)发布。
