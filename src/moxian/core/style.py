"""填充与描边样式。颜色用 #RRGGBB 字符串，透明度单独给。"""

from __future__ import annotations

from dataclasses import dataclass, replace


def parse_color(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


@dataclass(frozen=True)
class Style:
    fill: str | None = None
    fill_opacity: float = 1.0
    stroke: str | None = None
    stroke_width: float = 2.0  # 以 1080p 下的像素计
    stroke_opacity: float = 1.0
    opacity: float = 1.0  # 整体透明度，乘在 fill / stroke 上

    def with_(self, **changes) -> "Style":
        return replace(self, **changes)

    def visible(self) -> bool:
        return self.opacity > 0 and (
            (self.fill is not None and self.fill_opacity > 0)
            or (self.stroke is not None and self.stroke_opacity > 0 and self.stroke_width > 0)
        )
