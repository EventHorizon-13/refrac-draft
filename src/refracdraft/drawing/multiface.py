from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ezdxf.math import Vec2, Vec3
from manifold3d import CrossSection, FillRule, Manifold, OpType

from refracdraft.domain.models import BoardFaceFeature, BoardFaceProfile, CutFace, GeometryType, ModuleParameters
from refracdraft.drawing.board_profiles import build_board_profile, profiles_by_face
from refracdraft.geometry.primitives import Polyline, module_front_outline, module_side_outline, point_in_outline, rectangle


TOLERANCE = 1e-5


def _section(outline: Polyline) -> CrossSection:
    return CrossSection([outline.points], FillRule.NonZero)


def _from_view(face: CutFace, length: float, thickness: float):
    if face == CutFace.FRONT:
        return ((1, 0, 0, 0), (0, 0, -1, thickness), (0, 1, 0, 0))
    return ((0, 0, -1, length), (-1, 0, 0, thickness), (0, 1, 0, 0))


def _to_view(solid: Manifold, face: CutFace, length: float, thickness: float) -> Manifold:
    if face == CutFace.BOARD:
        return solid
    if face == CutFace.FRONT:
        return solid.transform(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, thickness)))
    return solid.transform(((0, -1, 0, thickness), (0, 0, 1, 0), (-1, 0, 0, length)))


def _plate_plane(module: ModuleParameters, upper: bool) -> tuple[float, float, float]:
    front_taper = module.geometry_type == GeometryType.FRONT_TAPER
    side_taper = module.geometry_type == GeometryType.SIDE_TAPER
    if not (front_taper or side_taper):
        return 0.0, 0.0, module.front_height_mm if upper else 0.0
    left = module.front_left_height_mm if front_taper else module.side_left_height_mm
    right = module.front_right_height_mm if front_taper else module.side_right_height_mm
    assert left is not None and right is not None
    height = max(left, right)
    direction = 1.0 if upper else -1.0
    if front_taper:
        return direction * (right - left) / (2 * module.front_width_mm), 0.0, (height + direction * left) / 2
    return (0.0, direction * (left - right) / (2 * module.board_face_height_mm),
            (height + direction * right) / 2)


def is_through_cut(module: ModuleParameters, cut: BoardFaceFeature) -> bool:
    span = (module.maximum_view_height_mm if cut.face == CutFace.BOARD
            else module.cut_face_dimensions(cut.face)[2])
    return cut.cut_depth_mm is None or cut.cut_depth_mm >= span - TOLERANCE


def _cut_volume(module: ModuleParameters, cut: BoardFaceFeature) -> Manifold:
    length, thickness = module.board_face_width_mm, module.board_face_height_mm
    width, height, thickness_along_cut = module.cut_face_dimensions(cut.face)
    retained, _ = build_board_profile(width, height, BoardFaceProfile(features=[cut]))
    footprint = _section(rectangle(width, height)) - _section(retained)
    if is_through_cut(module, cut):
        distance = module.maximum_view_height_mm if cut.face == CutFace.BOARD else thickness_along_cut
        blank = footprint.extrude(distance)
        return blank if cut.face == CutFace.BOARD else blank.transform(_from_view(cut.face, length, thickness))
    depth = cut.cut_depth_mm
    assert depth is not None
    if cut.face == CutFace.BOARD:
        upper = cut.cut_start == cut.face.starts[1]
        sx, sy, start = _plate_plane(module, upper)
        return footprint.extrude(depth).transform(((1, 0, 0, 0), (0, 1, 0, 0),
                                                    (sx, sy, 1, start - depth if upper else start)))
    near = cut.cut_start == cut.face.starts[0]
    blank = footprint.extrude(depth)
    if near:
        blank = blank.translate((0, 0, thickness_along_cut - depth))
    return blank.transform(_from_view(cut.face, length, thickness))


def machined_module(module: ModuleParameters, profile: BoardFaceProfile) -> Manifold:
    length, thickness = module.board_face_width_mm, module.board_face_height_mm
    if abs(module.front_width_mm - length) > TOLERANCE or (
        module.side_length_mm is not None and abs(module.side_length_mm - thickness) > TOLERANCE
    ):
        raise ValueError("多面异形的长度和厚度须在各视图一致")
    for face, features in profiles_by_face(profile).items():
        width, height, _ = module.cut_face_dimensions(face)
        try:
            build_board_profile(width, height, features)
        except ValueError as exc:
            raise ValueError(f"{face}：{exc}") from exc

    front = _section(module_front_outline(module)).extrude(thickness).transform(
        _from_view(CutFace.FRONT, length, thickness)
    )
    side_outline = module_side_outline(module)
    if side_outline is not None:
        side = _section(side_outline).extrude(length).transform(_from_view(CutFace.SIDE, length, thickness))
        front = front ^ side

    cutters = []
    for index, feature in enumerate(profile.features, 1):
        cutter = _cut_volume(module, feature)
        if (front ^ cutter).volume() <= TOLERANCE:
            raise ValueError(f"{feature.face}切口 {index} 未碰到模块实体，请检查起切面、旋转或深度")
        cutters.append(cutter)
    solid = Manifold.batch_boolean([front, *cutters], OpType.Subtract).simplify(TOLERANCE)
    if solid.is_empty() or len(solid.decompose()) != 1:
        raise ValueError("剪切后模块须保留一块连续的实体，请检查切口和深度")
    return solid


def _polygon_area(points) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])) / 2


def _contours(section: CrossSection) -> tuple[Polyline, ...]:
    contours = []
    for polygon in section.simplify(TOLERANCE).to_polygons():
        points = tuple((round(float(x), 7), round(float(y), 7)) for x, y in polygon)
        if len(points) < 3 or abs(_polygon_area(points)) < TOLERANCE:
            continue
        first = min(range(len(points)), key=lambda index: (points[index][1], points[index][0]))
        contours.append(Polyline(points[first:] + points[:first]))
    return tuple(sorted(contours, key=lambda line: (-abs(_polygon_area(line.points)), line.points)))


def plate_contours(solid: Manifold, module: ModuleParameters, *, upper: bool) -> tuple[Polyline, ...]:
    """Find material at the corresponding original plate surface, even on a taper."""
    sx, sy, offset = _plate_plane(module, upper)
    mesh = solid.to_mesh64()
    polygons = []
    for row in mesh.tri_verts:
        vertices = [mesh.vert_properties[index][:3] for index in row]
        if all(abs(z - sx * x - sy * y - offset) <= TOLERANCE for x, y, z in vertices):
            points = tuple((x, y) for x, y, _ in vertices)
            polygons.append(points if _polygon_area(points) > 0 else points[::-1])
    return _contours(CrossSection(polygons, FillRule.Positive))


def mounting_sections(solid: Manifold, altitude: float) -> tuple[tuple[Polyline, ...], ...]:
    return tuple(contours for component in solid.slice(altitude).decompose()
                 if (contours := _contours(component)))


def _segment_stations(start: Vec2, end: Vec2, boundaries) -> list[float]:
    direction = end - start
    length_squared = direction.dot(direction)
    stations = {0.0, 1.0}
    for a, b in boundaries:
        other = b - a
        delta = a - start
        determinant = direction.det(other)
        if abs(determinant) > TOLERANCE:
            t = delta.det(other) / determinant
            u = delta.det(direction) / determinant
            if TOLERANCE < t < 1 - TOLERANCE and -TOLERANCE <= u <= 1 + TOLERANCE:
                stations.add(round(t, 9))
        elif abs(delta.det(direction)) <= TOLERANCE:
            for point in (a, b):
                t = (point - start).dot(direction) / length_squared
                if TOLERANCE < t < 1 - TOLERANCE:
                    stations.add(round(t, 9))
    return sorted(stations)


@dataclass(frozen=True)
class Projection:
    outline: Polyline
    holes: tuple[Polyline, ...]
    visible: tuple[Polyline, ...]
    hidden: tuple[Polyline, ...]


def clip_layer_marks(
    marks: tuple[Polyline, ...], outline: Polyline, holes: tuple[Polyline, ...],
) -> tuple[Polyline, ...]:
    """Keep layer marks on projected material, including surfaces exposed by blind cuts."""
    if not marks:
        return ()
    edges = tuple(
        (Vec2(a), Vec2(b))
        for path in (outline, *holes)
        for a, b in zip(path.points, path.points[1:] + path.points[:1])
    )
    visible = []
    for mark in marks:
        start, end = map(Vec2, mark.points)
        stations = _segment_stations(start, end, edges)
        for lo, hi in zip(stations, stations[1:]):
            mid = tuple(start.lerp(end, (lo + hi) / 2))
            if point_in_outline(outline, mid) and not any(
                point_in_outline(hole, mid) for hole in holes
            ):
                visible.append(mark if lo == 0 and hi == 1 else
                               Polyline((tuple(start.lerp(end, lo)), tuple(start.lerp(end, hi))), closed=False))
    return tuple(visible)


def _merge_lines(segments, visible: bool) -> tuple[Polyline, ...]:
    groups = defaultdict(list)
    for (p, q), is_visible in segments.items():
        if is_visible != visible:
            continue
        a, b = Vec2(p), Vec2(q)
        direction = (b - a).normalize()
        key = (round(direction.x, 6), round(direction.y, 6), round(direction.det(a), 5))
        groups[key].append((a.dot(direction), b.dot(direction), p, q))
    result = []
    for intervals in groups.values():
        intervals.sort()
        _, stop, start_point, end_point = intervals[0]
        for start, end, p, q in intervals[1:]:
            if start > stop + TOLERANCE:
                result.append(Polyline((start_point, end_point), False))
                start_point, end_point, stop = p, q, end
            elif end > stop:
                stop, end_point = end, q
        result.append(Polyline((start_point, end_point), False))
    return tuple(result)


def project_module(solid: Manifold, module: ModuleParameters, face: CutFace) -> Projection:
    view = _to_view(solid, face, module.board_face_width_mm, module.board_face_height_mm)
    outline, *holes = _contours(view.project())
    contour_edges = [
        (Vec2(a), Vec2(b))
        for path in (outline, *holes) for a, b in zip(path.points, path.points[1:] + path.points[:1])
    ]
    mesh = view.to_mesh64()
    points = [
        Vec3(tuple(round(float(value), 8) for value in point[:3]))
        for point in mesh.vert_properties
    ]
    edge_normals: dict[tuple[Vec3, Vec3], list[Vec3]] = defaultdict(list)
    for row in mesh.tri_verts:
        a, b, c = (points[i] for i in row)
        normal = (b - a).cross(c - a)
        if normal.magnitude <= TOLERANCE:
            continue
        for u, v in ((a, b), (b, c), (c, a)):
            edge = (u, v) if tuple(u) < tuple(v) else (v, u)
            edge_normals[edge].append(normal.normalize())

    boundaries = [(Vec2(a), Vec2(b)) for a, b in edge_normals] + contour_edges
    z_min, z_max = min(point.z for point in points), max(point.z for point in points)
    drawn = {}
    for (a, b), normals in edge_normals.items():
        if len(normals) == 2 and normals[0].dot(normals[1]) > 1 - TOLERANCE:
            continue
        start, end = Vec2(a), Vec2(b)
        if (end - start).magnitude < TOLERANCE:
            continue
        stations = _segment_stations(start, end, boundaries)
        for lo, hi in zip(stations, stations[1:]):
            p, q = start.lerp(end, lo), start.lerp(end, hi)
            if (q - p).magnitude < TOLERANCE:
                continue
            mid = p.lerp(q)
            if any(abs((v - u).det(mid - u)) <= TOLERANCE
                   and (mid - u).dot(mid - v) <= TOLERANCE for u, v in contour_edges):
                continue
            depth = a.z + (b.z - a.z) * (lo + hi) / 2
            hits = view.ray_cast((mid.x, mid.y, z_max + 1), (mid.x, mid.y, z_min - 1))
            visible = not hits or hits[0].position[2] <= depth + TOLERANCE
            endpoints = tuple(sorted((tuple(round(v, 7) for v in p), tuple(round(v, 7) for v in q))))
            drawn[endpoints] = visible or drawn.get(endpoints, False)
    return Projection(outline, tuple(holes), _merge_lines(drawn, True), _merge_lines(drawn, False))
