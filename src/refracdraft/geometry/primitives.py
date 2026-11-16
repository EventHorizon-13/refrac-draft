from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable

from refracdraft.domain.models import GeometryType, ModuleParameters, Point2D


@dataclass(frozen=True)
class Polyline:
    points: tuple[tuple[float, float], ...]
    closed: bool = True

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)

    def transformed(self, sx: float = 1.0, sy: float = 1.0, tx: float = 0.0, ty: float = 0.0) -> "Polyline":
        return Polyline(tuple((x * sx + tx, y * sy + ty) for x, y in self.points), self.closed)


def rectangle(width: float, height: float) -> Polyline:
    return Polyline(((0.0, 0.0), (width, 0.0), (width, height), (0.0, height)))


def trapezoid(width: float, left_height: float, right_height: float) -> Polyline:
    """A front-facing taper: the two end heights differ across the width."""
    return Polyline(((0.0, 0.0), (width, 0.0), (width, right_height), (0.0, left_height)))


def module_front_outline(module: ModuleParameters) -> Polyline:
    if module.geometry_type == GeometryType.FRONT_TAPER:
        return trapezoid(module.front_width_mm, module.front_left_height_mm or module.front_height_mm,
                         module.front_right_height_mm or module.front_height_mm)
    return rectangle(module.front_width_mm, module.front_height_mm)


def module_side_outline(module: ModuleParameters) -> Polyline | None:
    if module.geometry_type != GeometryType.SIDE_TAPER:
        return None
    return trapezoid(
        module.side_length_mm or module.front_width_mm,
        module.side_left_height_mm or module.front_height_mm,
        module.side_right_height_mm or module.front_height_mm,
    )


def scale_template(points: Iterable[tuple[float, float]], width: float, height: float) -> Polyline:
    pts = tuple(points)
    if len(pts) < 3:
        raise ValueError("模板轮廓至少需要 3 个点")
    min_x = min(p[0] for p in pts)
    min_y = min(p[1] for p in pts)
    max_x = max(p[0] for p in pts)
    max_y = max(p[1] for p in pts)
    if max_x <= min_x or max_y <= min_y:
        raise ValueError("模板轮廓边界无效")
    sx, sy = width / (max_x - min_x), height / (max_y - min_y)
    return Polyline(tuple(((x - min_x) * sx, (y - min_y) * sy) for x, y in pts))


def equal_anchor_positions(width: float, height: float, count: int, edge_offset: float = 50.0) -> list[Point2D]:
    if count <= 0:
        return []
    if count == 1:
        return [Point2D(x=width / 2.0, y=height / 2.0)]
    usable = width - 2.0 * edge_offset
    if usable < 0:
        raise ValueError("锚固件两端留边之和大于夹板面宽度")
    step = usable / (count - 1)
    return [Point2D(x=edge_offset + i * step, y=height / 2.0) for i in range(count)]
