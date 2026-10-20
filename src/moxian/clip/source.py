"""片段的帧来源：视频文件按帧往外读，帧序列按需解码，都不把整段载入内存。

视频走 ffmpeg（成片本来就要它）。管道停在「下一帧」，顺着播就接着读；
往回跳或跳得远才重新 -ss 到那一帧。缓存只留最近几帧的像素。
"""

from __future__ import annotations

import glob
import json
import re
import subprocess
from collections import OrderedDict
from pathlib import Path

import numpy as np
import skia

_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mpg", ".mpeg"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
_NATURAL = re.compile(r"(\d+)")
# 往前跳不超过这么多帧就继续读，省掉一次进程启动；再远就重新 seek
_SKIP_AHEAD = 24


def infer_kind(src: str) -> str:
    """从路径判断是视频文件还是帧序列。判断不了时抛 FileNotFoundError。"""
    if any(ch in src for ch in "*?["):
        return "frames"
    path = Path(src)
    if path.is_dir():
        return "frames"
    ext = path.suffix.lower()
    if ext in _IMAGE_EXT:
        return "frames"
    if ext in _VIDEO_EXT:
        return "video"
    if path.is_file():
        return "video"
    raise FileNotFoundError(f"找不到片段 {src}")


def _natural_key(path: Path) -> tuple:
    """frame_2 排在 frame_10 前面。"""
    parts = _NATURAL.split(path.name)
    return tuple(int(part) if part.isdigit() else part.lower() for part in parts)


def collect_frames(src: str) -> list[Path]:
    """目录、glob 或单张图里的帧，按文件名自然排序。"""
    path = Path(src)
    if path.is_dir():
        files = [item for item in path.iterdir() if item.is_file() and item.suffix.lower() in _IMAGE_EXT]
    elif any(ch in src for ch in "*?["):
        files = [
            Path(match)
            for match in glob.glob(src, recursive=True)
            if Path(match).is_file() and Path(match).suffix.lower() in _IMAGE_EXT
        ]
    elif path.is_file() and path.suffix.lower() in _IMAGE_EXT:
        files = [path]
    else:
        raise FileNotFoundError(f"找不到帧序列 {src}")
    files.sort(key=_natural_key)
    if not files:
        raise FileNotFoundError(f"帧序列里没有 PNG/JPEG：{src}")
    return files


def _ratio(text: str) -> float:
    if not text or text == "0/0":
        raise ValueError(f"无效帧率 {text!r}")
    if "/" in text:
        num, den = text.split("/", 1)
        return float(num) / float(den)
    return float(text)


def probe_video(path: Path) -> tuple[int, int, float, int, float]:
    """返回 (宽, 高, 帧率, 帧数, 起始时间戳)。"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration,start_time",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError("解码视频需要 ffprobe（与 ffmpeg 一起安装）") from exc
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise RuntimeError(f"ffprobe 读不了 {path}：{err.strip()}") from exc
    data = json.loads(out)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError(f"{path} 里没有视频流")
    stream = streams[0]
    width, height = int(stream["width"]), int(stream["height"])
    fps = _ratio(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
    nb = stream.get("nb_frames")
    if nb and str(nb).isdigit() and int(nb) > 0:
        n_frames = int(nb)
    else:
        duration = stream.get("duration") or (data.get("format") or {}).get("duration")
        if not duration:
            raise RuntimeError(f"无法确定 {path} 有多少帧")
        n_frames = int(round(float(duration) * fps))
    start = float(stream.get("start_time") or 0.0)
    if width <= 0 or height <= 0 or fps <= 0 or n_frames <= 0:
        raise RuntimeError(f"无效的视频流：{path}")
    return width, height, fps, n_frames, start


def _rgba_image(array: np.ndarray) -> skia.Image:
    image = skia.Image.fromarray(
        array,
        colorType=skia.ColorType.kRGBA_8888_ColorType,
        alphaType=skia.AlphaType.kUnpremul_AlphaType,
        copy=True,
    )
    if image is None:
        raise RuntimeError("无法从像素建立图像")
    return image


class _Pipe:
    """从某一帧开始、按顺序吐 RGBA 的 ffmpeg 进程。"""

    def __init__(self, path: Path, start_time: float, fps: float, index: int, width: int, height: int):
        t = start_time + index / fps
        self.cmd = [
            "ffmpeg", "-v", "error", "-noautorotate",
            "-ss", f"{t:.12f}",
            "-i", str(path),
            "-map", "0:v:0",
            "-an",
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "pipe:1",
        ]
        try:
            self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as exc:
            raise RuntimeError("解码视频需要 ffmpeg") from exc
        self.next_index = index
        self.nbytes = width * height * 4
        self._closed = False

    def read(self) -> bytes:
        assert self.proc.stdout is not None
        buf = bytearray()
        while len(buf) < self.nbytes:
            chunk = self.proc.stdout.read(self.nbytes - len(buf))
            if not chunk:
                err = self._error_text()
                self.close()
                raise RuntimeError(f"ffmpeg 在第 {self.next_index} 帧之前结束{('：' + err) if err else ''}")
            buf += chunk
        self.next_index += 1
        return bytes(buf)

    def _error_text(self) -> str:
        if self.proc.stderr is None:
            return ""
        try:
            return self.proc.stderr.read().decode(errors="replace").strip()
        except Exception:
            return ""

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.proc.stdout is not None:
            self.proc.stdout.close()
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        if self.proc.stderr is not None:
            self.proc.stderr.close()


class _FrameCache:
    def __init__(self, limit: int):
        self.limit = limit
        self._data: OrderedDict[int, skia.Image] = OrderedDict()

    def get(self, index: int) -> skia.Image | None:
        image = self._data.get(index)
        if image is not None:
            self._data.move_to_end(index)
        return image

    def put(self, index: int, image: skia.Image) -> None:
        self._data[index] = image
        self._data.move_to_end(index)
        while len(self._data) > self.limit:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


class VideoFrames:
    """mp4/mov 等文件。frame(i) 只解码第 i 帧（或顺着上一帧往后读），音轨丢掉。"""

    def __init__(self, path: str | Path, cache_frames: int = 4):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"找不到视频 {self.path}")
        self.width, self.height, self.fps, self.n_frames, self.start_time = probe_video(self.path)
        self.cache = _FrameCache(cache_frames)
        self.decodes = 0
        self.opens = 0
        self._pipe: _Pipe | None = None

    def frame(self, index: int) -> skia.Image:
        index = int(index)
        if index < 0 or index >= self.n_frames:
            raise IndexError(f"帧 {index} 超出范围 0..{self.n_frames - 1}")
        cached = self.cache.get(index)
        if cached is not None:
            return cached
        raw = self._read(index)
        array = np.frombuffer(raw, dtype=np.uint8).reshape(self.height, self.width, 4)
        image = _rgba_image(array)
        self.decodes += 1
        self.cache.put(index, image)
        return image

    def _read(self, index: int) -> bytes:
        pipe = self._pipe
        if pipe is not None:
            nxt = pipe.next_index
            if nxt == index:
                return pipe.read()
            if nxt < index <= nxt + _SKIP_AHEAD:
                while pipe.next_index < index:
                    pipe.read()
                return pipe.read()
            pipe.close()
            self._pipe = None
        self._pipe = _Pipe(self.path, self.start_time, self.fps, index, self.width, self.height)
        self.opens += 1
        return self._pipe.read()

    def close(self) -> None:
        if self._pipe is not None:
            self._pipe.close()
            self._pipe = None
        self.cache.clear()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class FrameSequence:
    """目录、glob 或单张 PNG/JPEG。fps 由调用方给定，第 i 帧就是排序后的第 i 个文件。"""

    def __init__(self, src: str, fps: float | None, cache_frames: int = 4):
        self.paths = collect_frames(src)
        # 单张图没有时间轴，按 1fps 的一帧处理；真正的序列必须写明 fps
        if fps is None:
            if len(self.paths) == 1:
                fps = 1.0
            else:
                raise ValueError(f"帧序列需要 fps（每秒多少帧）：{src}")
        if fps <= 0:
            raise ValueError(f"fps 必须为正，收到 {fps}")
        self.fps = float(fps)
        self.n_frames = len(self.paths)
        self.cache = _FrameCache(cache_frames)
        self.decodes = 0

    def frame(self, index: int) -> skia.Image:
        index = int(index)
        if index < 0 or index >= self.n_frames:
            raise IndexError(f"帧 {index} 超出范围 0..{self.n_frames - 1}")
        cached = self.cache.get(index)
        if cached is not None:
            return cached
        # data 必须活到像素拷完：MakeFromEncoded 可能只引用这段 bytes，
        # 返回之后再画就会读到已经释放的内存（有时整幅是黑的）。
        data = self.paths[index].read_bytes()
        encoded = skia.Image.MakeFromEncoded(data)
        if encoded is None:
            raise RuntimeError(f"解码不了 {self.paths[index]}")
        image = encoded.makeRasterImage()
        if image is None:
            raise RuntimeError(f"解码不了 {self.paths[index]}")
        self.decodes += 1
        self.cache.put(index, image)
        return image

    def close(self) -> None:
        self.cache.clear()


def open_source(src: str, kind: str | None, fps: float | None, cache_frames: int):
    resolved = kind or infer_kind(src)
    if resolved == "video":
        return VideoFrames(src, cache_frames)
    if resolved == "frames":
        return FrameSequence(src, fps, cache_frames)
    raise ValueError(f"kind 必须是 video 或 frames，收到 {resolved!r}")
