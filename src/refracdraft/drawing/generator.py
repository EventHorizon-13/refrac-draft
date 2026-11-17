from __future__ import annotations

from refracdraft.domain.models import (
    AnchorParameters,
    AnchorType,
    GeometryType,
    LayoutMode,
    OpeningMode,
    OutlineKind,
    Project,
)
from refracdraft.drawing.model import Dimension, DrawingDocument, ModuleDrawing, SheetPage, PlacedModule, ViewDrawing
from refracdraft.drawing.layout import (
    PAGE_CONTENT_WIDTH_MM,
    PAGE_LEFT_MM,
    PANEL_GAP_MM,
    PANEL_INNER_MARGIN_MM,
    module_required_width,
)
from refracdraft.geometry.primitives import Polyline, equal_anchor_positions, module_front_outline, module_side_outline, parametric_outline, point_in_outline, rectangle, scale_template
from refracdraft.reference.library import ReferenceLibrary


ANCHOR_SYMBOL_ID = {
    AnchorType.M_SHAPE: "m-shaped",
    AnchorType.DIAMOND: "diamond",
}


BOARD_ANCHOR_TOP_OFFSET_MM = {
    AnchorType.M_SHAPE: 35.4391501542,
    AnchorType.DIAMOND: 70.0,
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


def _details(module, board, anchor) -> tuple[str, ...]:
    name = module.name or module.structure_type.value
    lines = [f"1、名称：{name}{module.module_id}", f"2、材质：{module.material or '未填写'}"]
    if not anchor.exists or anchor.anchor_type == AnchorType.NONE:
        lines.extend(("3、锚固件：无", "4、锚固件长度：无"))
    else:
        spec_parts = []
        if anchor.thread_spec:
            spec_parts.append(anchor.thread_spec)
        if anchor.diameter_mm:
            spec_parts.append(f"插针φ{anchor.diameter_mm:g}")
        spec = "，".join(spec_parts)
        anchor_name = {
            AnchorType.M_SHAPE: "M型", AnchorType.DIAMOND: "菱形", AnchorType.SIDE_INSERT: "旁插",
            AnchorType.QUICK_INSERT: "快插", AnchorType.WELDED_DIAMOND: "焊接菱形",
            AnchorType.CUSTOM: "自定义",
        }.get(anchor.anchor_type, "")
        embedment = (
            f"，嵌入深度 {anchor.embedment_depth_mm:g}mm"
            if anchor.anchor_type == AnchorType.DIAMOND and anchor.embedment_depth_mm
            else ""
        )
        material = anchor.material or "未填写材质"
        lines.extend((f"3、锚固件：{material}{anchor_name}锚固件{spec}{embedment}",
                      f"4、锚固件长度：{anchor.length_mm:g}mm" if anchor.length_mm else "4、锚固件长度：未填写"))
    lines.append(f"5、数量：{module.production_quantity} Pcs")
    lines.append(f"6、容重：{module.density_kg_m3:g} kg/m³" if module.density_kg_m3 else "6、容重：未填写")
    hose = anchor.hose_spec if anchor.exists else "无胶管"
    board_text = board.material if board.exists else "无夹板"
    lines.append(f"{hose or '未填写胶管'}，{board_text}")
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

        if module.board_face_outline:
            board_outline = parametric_outline(module.board_face_width_mm, module.board_face_height_mm,
                                               module.board_face_outline)
        elif module.board_face_template_id == "rectangular":
            board_outline = rectangle(module.board_face_width_mm, module.board_face_height_mm)
        elif self.reference_library:
            source_outline = self.reference_library.board_outline(module.board_face_template_id)
            board_outline = scale_template(source_outline.points, module.board_face_width_mm, module.board_face_height_mm)
        else:
            warnings.append(f"未加载参考 DXF，夹板面模板 {module.board_face_template_id} 暂以矩形代替")
            board_outline = rectangle(module.board_face_width_mm, module.board_face_height_mm)

        positions = _anchor_positions(
            anchor,
            module.board_face_width_mm,
            module.board_face_height_mm,
            board_face=True,
        )
        for x, y in positions:
            if not point_in_outline(board_outline, (x, y)):
                raise ValueError(f"{module.module_id}: 锚固件坐标 ({x:g}, {y:g}) 位于夹板面轮廓之外")
        symbol_lines: list[Polyline] = []
        symbol_colors: list[int] = []
        symbol_lineweights: list[int] = []
        symbol_linetypes: list[str] = []
        symbol_id = ANCHOR_SYMBOL_ID.get(anchor.anchor_type) if anchor.exists else None
        if positions and symbol_id and self.reference_library:
            symbol = self.reference_library.anchor_symbol(symbol_id)
            profile_colors = symbol.colors if len(symbol.colors) == len(symbol.polylines) else (5,) * len(symbol.polylines)
            profile_lineweights = symbol.lineweights if len(symbol.lineweights) == len(symbol.polylines) else (13,) * len(symbol.polylines)
            profile_linetypes = symbol.linetypes if len(symbol.linetypes) == len(symbol.polylines) else ("CONTINUOUS",) * len(symbol.polylines)
            for x, y in positions:
                symbol_lines.extend(_translate_symbol(symbol.polylines, x, y))
                symbol_colors.extend(profile_colors)
                symbol_lineweights.extend(profile_lineweights)
                symbol_linetypes.extend(profile_linetypes)
        elif positions and anchor.anchor_type not in (AnchorType.NONE, AnchorType.CUSTOM, AnchorType.QUICK_INSERT):
            warnings.append(f"锚固件类型 {anchor.anchor_type.value} 的参考符号尚未加载")
        cutouts: list[Polyline] = []
        if board.exists and board.opening_mode == OpeningMode.CUSTOM and board.custom_opening:
            opening = Polyline(tuple((p.x, p.y) for p in board.custom_opening), closed=True)
            opening_positions = positions or [(module.board_face_width_mm / 2.0, module.board_face_height_mm / 2.0)]
            for x, y in opening_positions:
                cutouts.append(_translate_symbol((opening,), x, y)[0])
        elif board.exists and anchor.anchor_type == AnchorType.QUICK_INSERT:
            try:
                standard = self.reference_library.standard_opening(anchor.anchor_type.value) if self.reference_library else ()
                if standard:
                    for x, y in positions:
                        cutouts.extend(_translate_symbol(standard, x, y))
                    warnings.append("快插标准开口采用B10参考图提取的候选轮廓，实际加工含义/尺寸仍需用户确认。")
                else:
                    warnings.append("未找到快插锚固件的标准夹板开口模板。")
            except (KeyError, FileNotFoundError) as exc:
                warnings.append(str(exc))
        elif board.exists and board.opening_mode == OpeningMode.STANDARD:
            warnings.append(f"尚未建立 {anchor.anchor_type.value} 锚固件的标准夹板开口模板。")

        board_dims = [
            Dimension((0, 0), (module.board_face_width_mm, 0), f"{module.board_face_width_mm:g}", "horizontal", -68),
            Dimension((0, 0), (0, module.board_face_height_mm), f"{module.board_face_height_mm:g}", "vertical", 40),
        ]
        if module.board_face_outline:
            board_dims.extend(_feature_dimensions(module.board_face_outline, module.board_face_width_mm))
        if anchor.dimension_horizontal:
            xs = sorted(p[0] for p in positions)
            chain = [0.0, *xs, module.board_face_width_mm]
            for start_x, end_x in zip(chain, chain[1:]):
                if end_x - start_x > 0.01:
                    board_dims.append(Dimension((start_x, module.board_face_height_mm),
                                                (end_x, module.board_face_height_mm),
                                                f"{end_x - start_x:g}", "horizontal", 35))
        if anchor.dimension_vertical:
            seen_offsets: set[float] = set()
            for x, y in positions:
                offset = round(module.board_face_height_mm - y, 3)
                if 0 < offset < module.board_face_height_mm and offset not in seen_offsets:
                    board_dims.append(Dimension((x, y), (x, module.board_face_height_mm),
                                                f"{offset:g}", "vertical", -50))
                    seen_offsets.add(offset)
        if anchor.anchor_type == AnchorType.DIAMOND and anchor.embedment_depth_mm and positions:
            embed_x, embed_y = positions[0]
            depth = anchor.embedment_depth_mm
            embed_end_y = embed_y + depth if embed_y + depth <= module.board_face_height_mm else embed_y - depth
            board_dims.append(
                Dimension((embed_x, embed_y), (embed_x, embed_end_y), f"嵌入深度 {depth:g}", "vertical", 80)
            )
        board_note = "无夹板" if not board.exists else ""
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

    def generate(self, project: Project) -> DrawingDocument:
        drawings = [self.build_module(project, module) for module in project.modules]
        pages: list[SheetPage] = []
        groups: list[list[ModuleDrawing]] = []
        current: list[ModuleDrawing] = []
        used_width = 0.0
        for drawing in drawings:
            required = module_required_width(drawing)
            candidate_width = used_width + (PANEL_GAP_MM if current else 0.0) + required
            if current and candidate_width > PAGE_CONTENT_WIDTH_MM:
                groups.append(current)
                current = [drawing]
                used_width = required
            else:
                current.append(drawing)
                used_width = candidate_width
        if current:
            groups.append(current)

        for page_number, group in enumerate(groups, start=1):
            required_widths = [module_required_width(drawing) for drawing in group]
            gaps = PANEL_GAP_MM * max(0, len(group) - 1)
            extra_width = max(0.0, PAGE_CONTENT_WIDTH_MM - gaps - sum(required_widths))
            extra_each = extra_width / len(group) if group else 0.0
            placed: list[PlacedModule] = []
            panel_x = PAGE_LEFT_MM
            for panel_index, (drawing, required) in enumerate(zip(group, required_widths)):
                panel_width = required + extra_each
                placed.append(
                    PlacedModule(
                        drawing=drawing,
                        x_mm=panel_x,
                        panel_width_mm=panel_width,
                        panel_index=panel_index,
                        content_x_mm=panel_x + PANEL_INNER_MARGIN_MM,
                    )
                )
                panel_x += panel_width + PANEL_GAP_MM
            pages.append(SheetPage(page_number, tuple(placed), len(group)))
        warnings = tuple(w for drawing in drawings for w in drawing.warnings)
        return DrawingDocument(project.metadata.project_name, tuple(pages), warnings)

