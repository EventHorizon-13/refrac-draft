from __future__ import annotations

from math import isfinite

from ezdxf.math import Vec2, intersection_line_line_2d, is_point_on_line_2d

from refracdraft.domain.models import BoardFaceFeature, BoardFaceProfile
from refracdraft.drawing.model import Dimension
from refracdraft.geometry.primitives import Polyline


Point = tuple[float, float]
Measure = tuple[Point, Point, float]
EPSILON = 1e-8


def _cut_path(
    width: float, height: float, feature: BoardFaceFeature
) -> tuple[tuple[Point, ...], tuple[Measure, ...]]:
    a, b, c, d = feature.a, feature.b, feature.c, feature.d
    if feature.type == 1:
        assert b is not None
        if a >= width or b >= height:
            raise ValueError("类型 1 要求 a < 长度、b < 厚度")
        return ((0, b), (a, b), (a, 0)), (
            ((0, b), (a, b), -b - 62), ((0, 0), (0, b), 25),
        )
    if feature.type == 2:
        assert b is not None and c is not None and d is not None
        if a + c >= height or b >= width or d > b:
            raise ValueError("类型 2 要求 a + c < 厚度、b < 长度、d ≤ b")
        upper = b - d
        notch_center_x = upper / 2 if upper >= 32 else -26
        shoulder_offset = height - (a + c) + 12
        return ((upper, height), (upper, a + c), (b, a + c), (b, a), (0, a)), (
            ((0, 0), (0, a), 26), ((0, a), (b, a), -a - 62),
            ((b, a), (b, a + c), b - notch_center_x),
            ((upper, a + c), (b, a + c), shoulder_offset),
        )
    if feature.type == 3:
        if a >= width:
            raise ValueError("类型 3 要求 a < 长度")
        return ((width - a, height), (0, 0)), (
            ((width - a, height), (width, height), 26),
        )
    assert b is not None and c is not None
    if a + b >= width or c >= height:
        raise ValueError("类型 4 要求 a + b < 长度、c < 厚度")
    return ((a, 0), (width - b, height - c), (width, height - c)), (
        ((0, 0), (a, 0), -62), ((width - b, height - c), (width, height - c), c - height - 62),
        ((width, height - c), (width, height), -26),
    )


def _oriented_cut(
    width: float, height: float, feature: BoardFaceFeature
) -> tuple[tuple[Point, ...], tuple[Dimension, ...]]:
    angle = feature.rotation_deg
    w, h = (height, width) if angle in (90, 270) else (width, height)
    cut, measures = _cut_path(w, h, feature)

    def transform(point: Point) -> Point:
        x, y = point
        if feature.mirror_x:
            x = w - x
        return {0: (x, y), 90: (h - y, x), 180: (w - x, h - y), 270: (y, w - x)}[angle]

    path = tuple(map(transform, reversed(cut) if feature.mirror_x else cut))
    dimensions = []
    for start, end, inset in measures:
        horizontal = start[1] == end[1]
        displaced = (start[0], start[1] + inset) if horizontal else (start[0] - inset, start[1])
        first, last, offset = transform(start), transform(end), transform(displaced)
        horizontal = first[1] == last[1]
        distance = abs(first[0] - last[0]) if horizontal else abs(first[1] - last[1])
        signed_offset = offset[1] - first[1] if horizontal else first[0] - offset[0]
        dimensions.append(Dimension(
            first, last, f"{distance:g}", "horizontal" if horizontal else "vertical", signed_offset,
        ))
    return path, tuple(dimensions)


def _perimeter_position(point: Point, width: float, height: float) -> float:
    x, y = point
    if y == 0:
        return x
    if x == width:
        return width + y
    if y == height:
        return 2 * width + height - x
    if x == 0:
        return 2 * (width + height) - y
    raise ValueError("异形端点不在夹板面外框上")


def _validate_simple(points: list[Point]) -> None:
    edges = list(zip(map(Vec2, points), map(Vec2, points[1:] + points[:1])))
    for index, edge in enumerate(edges):
        for other_index in range(index + 2, len(edges)):
            if index == 0 and other_index == len(edges) - 1:
                continue
            other = edges[other_index]
            if (
                intersection_line_line_2d(edge, other, virtual=False) is not None
                or any(is_point_on_line_2d(p, *edge, ray=False) for p in other)
                or any(is_point_on_line_2d(p, *other, ray=False) for p in edge)
            ):
                raise ValueError("夹板面的混合切口相交")


def build_board_profile(
    width: float, height: float, profile: BoardFaceProfile
) -> tuple[Polyline, tuple[Dimension, ...]]:
    """Replace disjoint stretches of the rectangular perimeter with shaped cuts."""
    if not all(isfinite(size) and size > 0 for size in (width, height)):
        raise ValueError("夹板面的长度和厚度必须是有限的正数")
    perimeter = 2 * (width + height)
    paths = [_oriented_cut(width, height, feature) for feature in profile.features]
    origin = _perimeter_position(paths[0][0][0], width, height)
    corners = sorted(
        (((s - origin) % perimeter), point)
        for s, point in zip(
            (0, width, width + height, 2 * width + height),
            ((0, 0), (width, 0), (width, height), (0, height)),
        )
    )
    cuts = []
    for path, _ in paths:
        first = _perimeter_position(path[0], width, height)
        last = _perimeter_position(path[-1], width, height)
        start = (first - origin) % perimeter
        cuts.append((start, start + (last - first) % perimeter, path))
    points: list[Point] = []
    position = 0.0
    for start, end, path in sorted(cuts, key=lambda cut: cut[0]):
        if start < position - EPSILON or end > perimeter + EPSILON:
            raise ValueError("夹板面的混合切口占用了同一段边缘")
        points.extend(point for s, point in corners if position + EPSILON < s < start - EPSILON)
        points.extend(path[1:] if points and points[-1] == path[0] else path)
        position = end
    points.extend(point for s, point in corners if position + EPSILON < s < perimeter - EPSILON)
    if len(points) > 1 and points[-1] == points[0]:
        points.pop()
    area2 = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))
    if len(points) < 3 or area2 <= EPSILON:
        raise ValueError("混合后夹板面没有有效面积")
    xs, ys = zip(*points)
    if min(xs) > EPSILON or max(xs) < width - EPSILON or min(ys) > EPSILON or max(ys) < height - EPSILON:
        raise ValueError("切口组合缩短了外轮廓，实际最大尺寸必须与表格的长度和厚度一致")
    _validate_simple(points)
    return Polyline(tuple(points)), tuple(dim for _, dims in paths for dim in dims)
