"""外部画面：视频或帧序列，按成片时刻贴进场景。"""

from .node import ClipNode
from .sample import frame_index, place

__all__ = ["ClipNode", "frame_index", "place"]
