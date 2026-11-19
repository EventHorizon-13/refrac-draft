from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from refracdraft.domain.models import (
    AnchorParameters,
    AnchorType,
    BoardFaceProfile,
    GeometryType,
    LayoutMode,
    OpeningMode,
    OutlineKind,
    Project,
)
from refracdraft.drawing.board_profiles import build_board_profile, machining_dimensions
from refracdraft.drawing.model import Dimension, DrawingDocument, ModuleDrawing, SheetPage, PlacedModule, ViewDrawing
from refracdraft.drawing.layout import (
    PAGE_CONTENT_WIDTH_MM,
    PAGE_LEFT_MM,
    PANEL_GAP_MM,
    geometry_width,
    module_required_width,
    panel_content_left,
)
from refracdraft.geometry.primitives import Polyline, equal_anchor_positions, module_front_outline, module_side_outline, parametric_outline, point_in_outline, rectangle, scale_template
from refracdraft.reference.library import ReferenceLibrary


ANCHOR_SYMBOL_ID = {
    AnchorType.M_SHAPE: "m-shaped",
    AnchorType.DIAMOND: "diamond",
}

INSERT_ANCHOR_TYPES = (AnchorType.SIDE_INSERT, AnchorType.QUICK_INSERT)

BOARD_ANCHOR_TOP_OFFSET_MM = {
    AnchorType.M_SHAPE: 35.4391501542,
    # The 60 mm reference board symbol starts at the board's top edge.
    AnchorType.SIDE_INSERT: 30.0,
    AnchorType.QUICK_INSERT: 30.0,
    AnchorType.WELDED_DIAMOND: 70.0,
}

def _anchor_x_positions(anchor: AnchorParameters, width: float) -> list[float]:
    if not anchor.exists or anchor.anchor_type == AnchorType.NONE or anchor.count == 0:
        return []
    if anchor.layout_mode == LayoutMode.EXPLICIT:
        return [p.x_mm for p in anchor.positions]
    if anchor.layout_mode == LayoutMode.EQUAL:
        return [p.x for p in equal_anchor_positions(width, 1.0, anchor.count, anchor.edge_offset_mm)]
    # Fixed-spacing mode is centered as a group; explicit coordinates remain the preferred
    # way to reproduce the segmented positioning dimensions in the supplied PDFs.
    spacing = anchor.spacing_mm or 0.0
    group_width = spacing * max(0, anchor.count - 1)
    start = anchor.edge_offset_mm
    if start + group_width > width:
        raise ValueError("锚固件端部留边与固定间距超出夹板面宽度")
    return [start + i * spacing for i in range(anchor.count)]


def _anchor_positions(
    anchor: AnchorParameters,
    width: float,
    height: float,
    board_face: bool = False,
):
    if board_face and anchor.layout_mode == LayoutMode.EXPLICIT and anchor.positions:
        return [(p.x_mm, p.y_mm) for p in anchor.positions]
    xs = _anchor_x_positions(anchor, width)
    if board_face:
        if anchor.anchor_type == AnchorType.DIAMOND and anchor.embedment_depth_mm:
            # The source diamond block defaults to a 70 mm insertion offset, but the
            # user-facing embedment depth is a real geometric parameter. The symbol is
            # extracted around its insertion point, so that point must coincide with
            # the dimension endpoint instead of keeping the block's stale default.
            return [(x, max(0.0, height - anchor.embedment_depth_mm)) for x in xs]
        offset = BOARD_ANCHOR_TOP_OFFSET_MM.get(anchor.anchor_type, 35.4391501542)
        y = max(0.0, height - offset)
    else:
        y = height / 2.0
    return [(x, y) for x in xs]


def _translate_symbol(symbol: tuple[Polyline, ...], x: float, y: float) -> tuple[Polyline, ...]:
    return tuple(line.transformed(tx=x, ty=y) for line in symbol)


def _small_head_contour_lines(width: float, overall_height: float, small_height: float) -> tuple[Polyline, ...]:
    if small_height <= 0 or small_height >= overall_height:
        return ()
    bottom = (overall_height - small_height) / 2.0
    top = (overall_height + small_height) / 2.0
    return (
        Polyline(((0.0, bottom), (width, bottom)), closed=False),
        Polyline(((0.0, top), (width, top)), closed=False),
    )


def _section_intersections(outline: Polyline, station: float) -> tuple[float, ...]:
    """Return the contour intersections along the vertical section at station."""
    depths = set()
    for (x1, y1), (x2, y2) in zip(outline.points, outline.points[1:] + outline.points[:1]):
        if x1 == x2:
            if station == x1:
                depths.update((y1, y2))
        elif min(x1, x2) <= station <= max(x1, x2):
            depths.add(y1 + (y2 - y1) * (station - x1) / (x2 - x1))
    return tuple(sorted(depths))


def _add_board_projection(view: ViewDrawing, board: Polyline) -> ViewDrawing:
    """Project near-side corners as solid edges and far-side corners as hidden edges."""
    left, _, right, _ = view.outline.bounds
    board_left, _, board_right, _ = board.bounds
    corners: dict[float, list[float]] = {}
    for x, depth in board.points:
        if board_left < x < board_right:
            corners.setdefault(x, []).append(depth)
    visible = []
    hidden = []
    for station, depths in sorted(corners.items()):
        x = left + (station - board_left) * (right - left) / (board_right - board_left)
        section = _section_intersections(board, station)
        at_far_outline = view.view_type == "front" and min(depths) - section[0] < 1e-6
        lines = visible if section[-1] - max(depths) < 1e-6 or at_far_outline else hidden
        intersections = _section_intersections(view.outline, x)
        for bottom, top in zip(intersections, intersections[1:]):
            if top - bottom > 1e-6 and point_in_outline(view.outline, (x, (bottom + top) / 2)):
                lines.append(Polyline(((x, bottom), (x, top)), closed=False))
    return replace(view, internal_lines=view.internal_lines + tuple(visible), hidden_lines=tuple(hidden))


def _anchor_chain_endpoints(
    board: Polyline, first: tuple[float, float], last: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Locate the dimension chain on the two outer edges around the anchors."""
    left, bottom, right, top = board.bounds
    section = Polyline(tuple((y, x) for x, y in board.points))
    top_edges = _section_intersections(section, top)
    top_left, top_right = top_edges[0], top_edges[-1]

    def datum(top_edge: float, outer_edge: float, anchor: tuple[float, float], is_left: bool):
        x, y = anchor
        if (is_left and top_edge > x) or (not is_left and top_edge < x):
            return (_section_intersections(section, y)[0 if is_left else -1], y)
        if top_edge == outer_edge:
            # A lower step can supply an actual extension-line origin without shifting the width datum.
            shoulder = max(
                (py for px, py in board.points if px == outer_edge and bottom < py < top),
                default=top,
            )
            return (outer_edge, shoulder)
        return (top_edge, top)

    return datum(top_left, left, first, True), datum(top_right, right, last, False)


def _details(module, board, anchor) -> tuple[str, ...]:
    name = module.custom_structure_label or module.name or module.structure_type.value
    display_name = name if module.module_id in name else f"{name}{module.module_id}"
    material = module.material.strip().removesuffix("材质").strip()
    lines = [f"1、名称：{display_name}", f"2、材质：{material or '未填写'}"]
    if not anchor.exists or anchor.anchor_type == AnchorType.NONE:
        lines.extend(("3、锚固件：无", "4、锚固件长度：无"))
    else:
        spec = anchor.thread_spec
        if anchor.diameter_mm:
            spec += f"φ{anchor.diameter_mm:g}"
        anchor_name = {
            AnchorType.M_SHAPE: "M型", AnchorType.DIAMOND: "菱形", AnchorType.SIDE_INSERT: "旁插",
            AnchorType.QUICK_INSERT: "快插", AnchorType.WELDED_DIAMOND: "焊接菱形",
            AnchorType.CUSTOM: anchor.custom_type_label or "自定义",
        }.get(anchor.anchor_type, "")
        material = anchor.material or "未填写材质"
        lines.extend((f"3、锚固件：{material}{anchor_name.removesuffix('锚固件')}{spec}",
                      f"4、锚固件长度：{anchor.length_mm:g}mm" if anchor.length_mm else "4、锚固件长度：未填写"))
    lines.append(f"5、数量：{module.production_quantity} Pcs")
    lines.append(f"6、容重：{module.density_kg_m3:g} kg/m³" if module.density_kg_m3 else "6、容重：未填写")
    hose = anchor.hose_spec if anchor.exists else "无胶管"
    board_text = board.material if board.exists else "无夹板"
    lines.append(f"7、{hose or '未填写胶管'}，{board_text}")
    notes = [module.source_note] if module.source_note else []
    if anchor.exists and anchor.anchor_type == AnchorType.SIDE_INSERT:
        instruction = "木板开口60*110 插针隔1层毯子插"
        if not any(instruction in note for note in notes):
            notes.append(instruction)
    if notes:
        lines.append(f"8、备注：{'；'.join(notes)}")
    return tuple(lines)


def _feature_dimensions(spec, width: float) -> tuple[Dimension, Dimension]:
    """Dimension the feature dimensions from the same values that make the contour."""
    fw, fh = spec.feature_width_mm, spec.feature_height_mm
    if spec.kind == OutlineKind.EDGE_NOTCH:
        left, right = spec.offset_mm, spec.offset_mm + fw
    else:
        left, right = width - fw, width
    if spec.mirror_x:
        left, right = width - right, width - left
    return (
        Dimension((left, fh), (right, fh), f"{fw:g}", "horizontal", -18),
        Dimension((left, 0), (left, fh), f"{fh:g}", "vertical", 18),
    )


class DrawingGenerator:
    def __init__(self, reference_library: ReferenceLibrary | None = None):
        self.reference_library = reference_library

    def build_module(self, project: Project, module) -> ModuleDrawing:
        board = project.board_for(module.module_id)
        anchor = project.anchor_for(module.module_id)
        warnings: list[str] = []
        for note in (module.source_note, board.source_note, anchor.source_note):
            if note:
                warnings.append(note)

        front = module_front_outline(module)
        if module.geometry_type == GeometryType.FRONT_TAPER:
            left_h = module.front_left_height_mm or module.front_height_mm
            right_h = module.front_right_height_mm or module.front_height_mm
            overall_h = max(left_h, right_h)
            left_bottom = (overall_h - left_h) / 2.0
            right_bottom = (overall_h - right_h) / 2.0
            top_left = left_bottom + left_h
            top_right = right_bottom + right_h
            front_dims = (
                Dimension((0, top_left), (module.front_width_mm, top_right), f"{module.front_width_mm:g}", "horizontal", 32),
                Dimension((0, left_bottom), (0, top_left), f"{left_h:g}", "vertical", 40),
                Dimension((module.front_width_mm, right_bottom), (module.front_width_mm, top_right), f"{right_h:g}", "vertical", -40),
            )
        else:
            front_dims = (
                Dimension((0, module.front_height_mm), (module.front_width_mm, module.front_height_mm),
                          f"{module.front_width_mm:g}", "horizontal", 32),
                Dimension((0, 0), (0, module.front_height_mm), f"{module.front_height_mm:g}", "vertical", 40),
            )
        if module.front_outline:
            front_dims += _feature_dimensions(module.front_outline, module.front_width_mm)
        front_symbols: list[Polyline] = []
        front_symbol_colors: list[int] = []
        front_symbol_lineweights: list[int] = []
        front_symbol_linetypes: list[str] = []
        front_internal_lines: list[Polyline] = []
        if module.geometry_type == GeometryType.SIDE_TAPER:
            small_head = min(
                module.side_left_height_mm or module.front_height_mm,
                module.side_right_height_mm or module.front_height_mm,
            )
            front_internal_lines.extend(
                _small_head_contour_lines(module.front_width_mm, module.front_height_mm, small_head)
            )
        positions = _anchor_positions(anchor, module.board_face_width_mm, module.board_face_height_mm)
        if module.front_outline:
            for x, _y in positions:
                front_point = (x * module.front_width_mm / module.board_face_width_mm,
                               module.front_height_mm / 2.0)
                if not point_in_outline(front, front_point):
                    raise ValueError(f"{module.module_id}: 锚固件正面投影位于模块轮廓之外")
        if positions and self.reference_library:
            try:
                profile = self.reference_library.front_anchor_symbol(anchor.anchor_type.value)
                profile_colors = profile.colors if len(profile.colors) == len(profile.polylines) else (7,) * len(profile.polylines)
                profile_lineweights = profile.lineweights if len(profile.lineweights) == len(profile.polylines) else (25,) * len(profile.polylines)
                profile_linetypes = profile.linetypes if len(profile.linetypes) == len(profile.polylines) else ("CONTINUOUS",) * len(profile.polylines)
                for x, _y in positions:
                    fx = x * module.front_width_mm / module.board_face_width_mm
                    front_symbols.extend(_translate_symbol(profile.polylines, fx, module.front_height_mm / 2.0))
                    front_symbol_colors.extend(profile_colors)
                    front_symbol_lineweights.extend(profile_lineweights)
                    front_symbol_linetypes.extend(profile_linetypes)
            except KeyError as exc:
                warnings.append(str(exc))
        if not positions and self.reference_library:
            front_internal_lines.extend(
                self.reference_library.stacked_front_lines(module.front_width_mm, module.front_height_mm)
            )
        front_internal = tuple(front_internal_lines)
        front_points = tuple((x * module.front_width_mm / module.board_face_width_mm,
                              module.front_height_mm / 2.0) for x, _y in positions) if positions else ()
        if front_symbols and anchor.anchor_type in INSERT_ANCHOR_TYPES:
            front_points = ()
        front_view = ViewDrawing(
            "front", "正面", front, front_dims, tuple(front_symbols), front_points,
            internal_lines=front_internal, anchor_symbol_colors=tuple(front_symbol_colors),
            anchor_symbol_lineweights=tuple(front_symbol_lineweights),
            anchor_symbol_linetypes=tuple(front_symbol_linetypes),
            anchor_marker_style="cross" if anchor.anchor_type == AnchorType.QUICK_INSERT else "target",
        )

        side_view = None
        side = module_side_outline(module)
        if side is not None:
            side_left_h = module.side_left_height_mm or 0
            side_right_h = module.side_right_height_mm or 0
            side_overall_h = max(side_left_h, side_right_h)
            side_left_bottom = (side_overall_h - side_left_h) / 2.0
            side_right_bottom = (side_overall_h - side_right_h) / 2.0
            side_top_left = side_left_bottom + side_left_h
            side_top_right = side_right_bottom + side_right_h
            side_dims = (
                Dimension((0, side_top_left),
                          (module.side_length_mm or 0, side_top_right),
                          f"{module.side_length_mm:g}", "horizontal", 32),
                Dimension((0, side_left_bottom), (0, side_top_left),
                          f"{side_left_h:g}", "vertical", 40),
                Dimension((module.side_length_mm or 0, side_right_bottom),
                          (module.side_length_mm or 0, side_top_right),
                          f"{side_right_h:g}", "vertical", -40),
            )
            side_symbols: list[Polyline] = []
            side_symbol_colors: list[int] = []
            side_symbol_lineweights: list[int] = []
            side_symbol_linetypes: list[str] = []
            side_internal: tuple[Polyline, ...] = ()
            if positions and self.reference_library:
                try:
                    side_profile = self.reference_library.side_anchor_symbol(anchor.anchor_type.value)
                    profile_colors = side_profile.colors if len(side_profile.colors) == len(side_profile.polylines) else (7,) * len(side_profile.polylines)
                    profile_lineweights = side_profile.lineweights if len(side_profile.lineweights) == len(side_profile.polylines) else (25,) * len(side_profile.polylines)
                    profile_linetypes = side_profile.linetypes if len(side_profile.linetypes) == len(side_profile.polylines) else ("CONTINUOUS",) * len(side_profile.polylines)
                    side_width = module.side_length_mm or module.board_face_width_mm
                    symbol_xs = [point[0] for line in side_profile.polylines for point in line.points]
                    min_x = min(symbol_xs) if symbol_xs else 0.0
                    max_x = max(symbol_xs) if symbol_xs else 0.0
                    left_edge = (
                        anchor.embedment_depth_mm or 50.0
                        if anchor.anchor_type == AnchorType.DIAMOND
                        else 0.0
                    )
                    if left_edge + (max_x - min_x) > side_width:
                        raise ValueError(f"{module.module_id}: 锚固件侧面符号超出侧面宽度")
                    sx = left_edge - min_x
                    side_symbols.extend(_translate_symbol(side_profile.polylines, sx, side_overall_h / 2.0))
                    side_symbol_colors.extend(profile_colors)
                    side_symbol_lineweights.extend(profile_lineweights)
                    side_symbol_linetypes.extend(profile_linetypes)
                except KeyError as exc:
                    warnings.append(str(exc))
            elif self.reference_library:
                side_internal = self.reference_library.side_expansion_lines(
                    module.side_length_mm or module.board_face_width_mm,
                    side_overall_h,
                    side_left_h,
                    side_right_h,
                )
            # The source side blocks contain their own center marks. A second target marker
            # would cover the actual profile and is not present in the reference drawing.
            side_view = ViewDrawing("side", "侧面", side, side_dims, tuple(side_symbols), (),
                                    anchor_symbol_colors=tuple(side_symbol_colors),
                                    anchor_symbol_lineweights=tuple(side_symbol_lineweights),
                                    anchor_symbol_linetypes=tuple(side_symbol_linetypes),
                                    internal_lines=side_internal)

        profile_dimensions = ()
        if isinstance(module.board_face_outline, BoardFaceProfile):
            try:
                board_outline, profile_dimensions = build_board_profile(
                    module.board_face_width_mm, module.board_face_height_mm, module.board_face_outline
                )
                profile_dimensions += machining_dimensions(board_outline, profile_dimensions)
            except ValueError as exc:
                raise ValueError(f"{module.module_id}: {exc}") from exc
        elif module.board_face_outline:
            board_outline = parametric_outline(module.board_face_width_mm, module.board_face_height_mm,
                                               module.board_face_outline)
            profile_dimensions = _feature_dimensions(module.board_face_outline, module.board_face_width_mm)
        elif module.board_face_template_id == "rectangular":
            board_outline = rectangle(module.board_face_width_mm, module.board_face_height_mm)
        elif self.reference_library:
            source_outline = self.reference_library.board_outline(module.board_face_template_id)
            board_outline = scale_template(source_outline.points, module.board_face_width_mm, module.board_face_height_mm)
        else:
            warnings.append(f"未加载参考 DXF，夹板面模板 {module.board_face_template_id} 暂以矩形代替")
            board_outline = rectangle(module.board_face_width_mm, module.board_face_height_mm)

        if module.board_face_outline is not None:
            front_view = _add_board_projection(front_view, board_outline)
            if side_view is not None:
                # First-angle projection places the left view to the right of the front view.
                side_board = Polyline(tuple((-y, -x) for x, y in board_outline.points))
                side_view = _add_board_projection(side_view, side_board)

        symbol_lines: list[Polyline] = []
        symbol_colors: list[int] = []
        symbol_lineweights: list[int] = []
        symbol_linetypes: list[str] = []
        symbol_id = ANCHOR_SYMBOL_ID.get(anchor.anchor_type) if anchor.exists else None
        symbol = None
        positions = _anchor_positions(
            anchor,
            module.board_face_width_mm,
            module.board_face_height_mm,
            board_face=True,
        )
        if positions and self.reference_library:
            if anchor.anchor_type in INSERT_ANCHOR_TYPES:
                symbol = self.reference_library.insert_anchor_board_symbol()
            elif symbol_id:
                symbol = self.reference_library.anchor_symbol(symbol_id)
        if symbol is not None and anchor.anchor_type == AnchorType.DIAMOND and anchor.embedment_depth_mm:
            symbol_ys = [point[1] for line in symbol.polylines for point in line.points]
            symbol_top = max(symbol_ys, default=0.0)
            positions = [
                (x, module.board_face_height_mm - anchor.embedment_depth_mm - symbol_top)
                for x, _y in positions
            ]
        for x, y in positions:
            if not point_in_outline(board_outline, (x, y)):
                raise ValueError(f"{module.module_id}: 锚固件坐标 ({x:g}, {y:g}) 位于夹板面轮廓之外")
        if positions and symbol is not None:
            profile_colors = symbol.colors if len(symbol.colors) == len(symbol.polylines) else (5,) * len(symbol.polylines)
            profile_lineweights = symbol.lineweights if len(symbol.lineweights) == len(symbol.polylines) else (13,) * len(symbol.polylines)
            profile_linetypes = symbol.linetypes if len(symbol.linetypes) == len(symbol.polylines) else ("CONTINUOUS",) * len(symbol.polylines)
            for x, y in positions:
                symbol_lines.extend(_translate_symbol(symbol.polylines, x, y))
                symbol_colors.extend(profile_colors)
                symbol_lineweights.extend(profile_lineweights)
                symbol_linetypes.extend(profile_linetypes)
        elif positions and anchor.anchor_type not in (AnchorType.NONE, AnchorType.CUSTOM):
            warnings.append(f"锚固件类型 {anchor.anchor_type.value} 的参考符号尚未加载")
        cutouts: list[Polyline] = []
        if board.exists and board.opening_mode == OpeningMode.CUSTOM and board.custom_opening:
            opening = Polyline(tuple((p.x, p.y) for p in board.custom_opening), closed=True)
            opening_positions = positions or [(module.board_face_width_mm / 2.0, module.board_face_height_mm / 2.0)]
            for x, y in opening_positions:
                cutouts.append(_translate_symbol((opening,), x, y)[0])
        elif board.exists and board.opening_mode == OpeningMode.STANDARD:
            warnings.append(f"尚未建立 {anchor.anchor_type.value} 锚固件的标准夹板开口模板。")

        left_cut_dim = min(
            (dim.line_position for dim in profile_dimensions if dim.orientation == "vertical"),
            default=0.0,
        )
        board_dims = [
            Dimension((0, 0), (module.board_face_width_mm, 0), f"{module.board_face_width_mm:g}",
                      "horizontal", -102 if profile_dimensions else -68),
            Dimension((0, 0), (0, module.board_face_height_mm), f"{module.board_face_height_mm:g}", "vertical",
                      max(70, -left_cut_dim + 44) if profile_dimensions else 40),
        ]
        board_dims.extend(profile_dimensions)
        if anchor.dimension_horizontal and positions:
            ordered = sorted(positions)
            top = module.board_face_height_mm
            cut_dim_top = max(
                (dim.line_position for dim in profile_dimensions if dim.orientation == "horizontal"),
                default=top,
            )
            chain_offset = max(35.0, cut_dim_top - top + 62) if cut_dim_top > top else 35.0
            left, right = _anchor_chain_endpoints(board_outline, ordered[0], ordered[-1])
            chain = [left, *((x, _section_intersections(board_outline, x)[-1]) for x, _ in ordered), right]
            for start, end in zip(chain, chain[1:]):
                distance = end[0] - start[0]
                if distance > 0.01:
                    offset = top + chain_offset - max(start[1], end[1])
                    board_dims.append(Dimension(start, end, f"{distance:g}", "horizontal", offset))
        if anchor.dimension_vertical:
            seen_offsets: set[float] = set()
            for x, y in positions:
                offset = round(module.board_face_height_mm - y, 3)
                if 0 < offset < module.board_face_height_mm and offset not in seen_offsets:
                    board_dims.append(Dimension((x, y), (x, module.board_face_height_mm),
                                                f"{offset:g}", "vertical", -50))
                    seen_offsets.add(offset)
        if anchor.anchor_type == AnchorType.DIAMOND and anchor.embedment_depth_mm and positions:
            embed_x = positions[0][0]
            depth = anchor.embedment_depth_mm
            if depth > module.board_face_height_mm:
                raise ValueError(f"{module.module_id}: 菱形锚固件嵌入深度不能大于夹板面厚度")
            board_dims.append(
                Dimension(
                    (embed_x, module.board_face_height_mm),
                    (embed_x, module.board_face_height_mm - depth),
                    f"{depth:g}",
                    "vertical",
                    80,
                )
            )
        board_note = ""
        if not board.exists:
            board_note = "无夹板"
        elif not anchor.exists or anchor.anchor_type == AnchorType.NONE or not anchor.count:
            board_note = "夹板"
        # The source board-face blocks already contain their own center marks and end marks.
        # Do not add a second marker at the insertion point (which sits on the board edge).
        board_view = ViewDrawing(
            "board-face", "夹板面", board_outline, tuple(board_dims),
            tuple(symbol_lines), (), board_note, tuple(cutouts),
            anchor_symbol_colors=tuple(symbol_colors),
            anchor_symbol_lineweights=tuple(symbol_lineweights),
            anchor_symbol_linetypes=tuple(symbol_linetypes),
        )
        return ModuleDrawing(
            module.module_id, module.name or module.structure_type.value,
            _details(module, board, anchor), front_view, side_view, board_view, tuple(warnings),
        )

    def generate(
        self,
        project: Project,
        *,
        on_module_drawn: Callable[[int], None] | None = None,
    ) -> DrawingDocument:
        drawings = []
        for count, module in enumerate(project.modules, start=1):
            drawings.append(self.build_module(project, module))
            if on_module_drawn is not None:
                on_module_drawn(count)
        required_widths = [module_required_width(drawing) for drawing in drawings]
        pages: list[SheetPage] = []
        groups = _balanced_page_groups(required_widths)

        for page_number, (start, end) in enumerate(groups, start=1):
            group = drawings[start:end]
            group_widths = required_widths[start:end]
            gaps = PANEL_GAP_MM * max(0, len(group) - 1)
            extra_width = max(0.0, PAGE_CONTENT_WIDTH_MM - gaps - sum(group_widths))
            extra_each = extra_width / len(group) if group else 0.0
            placed: list[PlacedModule] = []
            panel_x = PAGE_LEFT_MM
            for panel_index, (drawing, required) in enumerate(zip(group, group_widths)):
                panel_width = required + extra_each
                content_x = panel_x + panel_content_left(drawing, panel_width, geometry_width(drawing))
                placed.append(
                    PlacedModule(
                        drawing=drawing,
                        x_mm=panel_x,
                        panel_width_mm=panel_width,
                        panel_index=panel_index,
                        content_x_mm=content_x,
                    )
                )
                panel_x += panel_width + PANEL_GAP_MM
            pages.append(SheetPage(page_number, tuple(placed), len(group)))
        warnings = tuple(w for drawing in drawings for w in drawing.warnings)
        return DrawingDocument(project.metadata.project_name, tuple(pages), warnings)


def _balanced_page_groups(required_widths: list[float]) -> list[tuple[int, int]]:
    """Partition modules into the fewest pages, then balance the used width per page."""
    count = len(required_widths)
    if count == 0:
        return []
    # State: page count, highest fill ratio, squared unused capacity, page start.
    best: list[tuple[int, float, float, int] | None] = [None] * (count + 1)
    best[0] = (0, 0.0, 0.0, 0)
    prefix = [0.0]
    for width in required_widths:
        prefix.append(prefix[-1] + width)
    for end in range(1, count + 1):
        for start in range(end - 1, -1, -1):
            used = prefix[end] - prefix[start] + PANEL_GAP_MM * (end - start - 1)
            if used > PAGE_CONTENT_WIDTH_MM + 1e-6:
                break
            previous = best[start]
            if previous is None:
                continue
            fill = used / PAGE_CONTENT_WIDTH_MM
            candidate = (
                previous[0] + 1,
                max(previous[1], fill),
                previous[2] + (1.0 - fill) ** 2,
                start,
            )
            if best[end] is None or candidate < best[end]:
                best[end] = candidate

    groups = []
    end = count
    while end:
        page = best[end]
        if page is None:
            raise ValueError("模块宽度超出单页可用宽度")
        start = page[3]
        groups.append((start, end))
        end = start
    return list(reversed(groups))

