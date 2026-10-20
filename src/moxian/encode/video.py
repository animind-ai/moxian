"""帧序列 → 视频：把 Skia 画出的像素直接喂给 ffmpeg 的标准输入，可选合入一条音轨。"""

from __future__ import annotations

import subprocess
from pathlib import Path as FsPath

import numpy as np
import skia

from ..core import Node
from ..render import SkiaRenderer


class VideoWriter:
    def __init__(self, out: str | FsPath, width: int = 1920, height: int = 1080, fps: int = 30,
                 audio: str | FsPath | None = None, crf: int = 20, preset: str = "veryfast"):
        self.out = FsPath(out)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.width, self.height, self.fps = width, height, fps
        self.frames = 0
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        ]
        if audio is not None:
            cmd += ["-i", str(audio)]
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
        if audio is not None:
            cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
        cmd.append(str(self.out))
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        # Skia 直接画进这块内存，明确指定 RGBA，和上面给 ffmpeg 的像素格式一致
        self.buffer = np.zeros((height, width, 4), dtype=np.uint8)
        info = skia.ImageInfo.Make(width, height, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        self.surface = skia.Surface.MakeRasterDirect(info, self.buffer, width * 4)
        if self.surface is None:
            raise RuntimeError("无法创建 Skia 内存画布")

    def write(self, renderer: SkiaRenderer, root: Node) -> None:
        with self.surface as canvas:
            renderer.draw(canvas, root)
        self.repeat()

    def repeat(self) -> None:
        """画面没变：把上一帧的像素原样再送一帧。"""
        assert self.proc.stdin is not None
        self.proc.stdin.write(self.buffer.tobytes())
        self.frames += 1

    def close(self) -> FsPath:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        code = self.proc.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg 退出码 {code}")
        return self.out

    def __enter__(self) -> VideoWriter:
        return self

    def __exit__(self, *exc) -> None:
        if exc[0] is None:
            self.close()
        else:
            self.proc.kill()


def _raster_signature(root: Node, t: float) -> tuple:
    """每个带 raster_key 的节点在时刻 t 的帧号。变了就得重画（片段在播，矢量可能没动）。"""
    keys = []
    for node, _, _ in root.walk():
        key_at = getattr(node, "raster_key", None)
        if key_at is not None:
            keys.append(key_at(t))
    return tuple(keys)


def _raster_until(root: Node) -> float:
    """片段播完一遍的最晚时刻。没有片段时是 0，不改变原来的成片长度。"""
    end = 0.0
    for node, _, _ in root.walk():
        until = getattr(node, "play_until", None)
        if until is not None:
            end = max(end, float(until()))
    return end


def render_video(root: Node, timeline, out: str | FsPath, renderer: SkiaRenderer, fps: int = 30,
                 audio: str | FsPath | None = None, until: float | None = None, log=print) -> FsPath:
    drawn = 0
    # 没指定 until、时间线也比片段短时，把成片拉到片段播完一遍（停在最后一帧，不额外加尾）
    frame_until = until
    if until is None:
        horizon = _raster_until(root)
        if horizon > timeline.end:
            frame_until = horizon
    with VideoWriter(out, renderer.width, renderer.height, fps, audio) as writer:
        first = True
        prev = None
        for t in timeline.frames(fps, frame_until):
            changed = timeline.seek(t)
            renderer.time = t
            signature = _raster_signature(root, t)
            if changed or first or signature != prev:
                writer.write(renderer, root)
                drawn += 1
                first = False
            else:
                writer.repeat()
            prev = signature
        log(f"{writer.frames} 帧（重画 {drawn} 帧）→ {out}")
    return FsPath(out)
