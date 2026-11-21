from __future__ import annotations

from collections.abc import Callable

from dataclasses import dataclass, replace

from refracdraft.drawing.model import DrawingDocument, ModuleDrawing, PlacedModule, ViewDrawing


VIEW_SCALE = 0.0992
SIDE_VIEW_GAP_MM = 14.0
VIEW_CLEARANCE_MM = 10.0
MIN_VERTICAL_VIEW_CLEARANCE_MM = 4.0
COMPACT_DETAIL_WIDTH_FACTOR = 0.88
PAGE_WIDTH_MM = 297.0
PAGE_HEIGHT_MM = 210.0
PAGE_STRIDE_MM = 230.0
PAGE_LEFT_MM = 7.0
PAGE_CONTENT_WIDTH_MM = 283.0
PANEL_INNER_MARGIN_MM = 8.0
PANEL_GAP_MM = 6.0
SIDE_DETAIL_GAP_MM = 4.0
SIDE_DETAIL_RIGHT_MARGIN_MM = 1.0
SIDE_PANEL_GAP_MM = 2.0
PANEL_MIN_WIDTH_MM = 58.0
CENTERED_MODULE_MAX_LENGTH_MM = 350.0

# A 150 mm model-space inset is 15 mm on the 1:10 A4 sheet.
FRAME_INSET_MM = 7.0
TITLE_BLOCK_TOP_MM = 37.0
TITLE_BLOCK_LEFT_MM = 168.7
LEFT_FOOTER_FLOOR_MM = 25.0
FILENAME_LABEL_POSITION = (9.0, 19.0)
FILENAME_LABEL_HEIGHT_MM = 2.4
FILENAME_LABEL_WIDTH_MM = 154.0
SEPARATOR_MARGIN_MM = 15.0
SEPARATOR_TOP_MM = PAGE_HEIGHT_MM - FRAME_INSET_MM - SEPARATOR_MARGIN_MM
SEPARATOR_BOTTOM_MM = TITLE_BLOCK_TOP_MM + SEPARATOR_MARGIN_MM

DETAIL_TEXT_SIZE_MM = 4.5
DIMENSION_TEXT_SIZE_MM = 3.2
DIMENSION_ARROW_SIZE_MM = 1.3
DETAIL_LINE_SPACING = 0.76
DETAIL_LINE_HEIGHT_MM = DETAIL_TEXT_SIZE_MM * (5 / 3) * DETAIL_LINE_SPACING
DETAIL_TITLE_CLEARANCE_MM = 4.0
DETAIL_VIEW_CLEARANCE_MM = 2.0
DETAIL_WIDTH_CLEARANCE_MM = 2.0
ANNOTATION_CLEARANCE_MM = DIMENSION_TEXT_SIZE_MM + 1.6


@dataclass(frozen=True)
class ViewPlacement:
    top_y: float
    board_y: float
    side_x: float
    detail_y: float
    detail_on_side: bool


def page_model_origins(document: DrawingDocument) -> tuple[float, ...]:
    origins = []
    y = 0.0
    for index, page in enumerate(document.pages):
        if index:
            previous = document.pages[index - 1]
            y -= PAGE_HEIGHT_MM * page.scale_denominator + (PAGE_STRIDE_MM - PAGE_HEIGHT_MM) * previous.scale_denominator
        origins.append(y)
    return tuple(origins)


def annotation_factor(denominator: int) -> float:
    return 1.1 if denominator == 20 else 1.0


def leader_text_height(denominator: int) -> float:
    return 3.2 * annotation_factor(denominator)


def view_bounds(view: ViewDrawing, denominator: int = 10) -> tuple[float, float, float, float]:
    """Conservative paper-space bounds of the visible geometry and its dimensions."""
    annotation_scale = annotation_factor(denominator)
    geometry = (view.outline, *view.internal_lines, *view.hidden_lines, *view.anchor_symbols, *view.cutouts)
    boxes = [line.bounds for line in geometry]
    left = min(box[0] for box in boxes) / denominator
    bottom = min(box[1] for box in boxes) / denominator
    right = max(box[2] for box in boxes) / denominator
    top = max(box[3] for box in boxes) / denominator
    for x, y in view.anchor_points:
        left, right = min(left, x / denominator - 1.5), max(right, x / denominator + 1.5)
        bottom, top = min(bottom, y / denominator - 1.5), max(top, y / denominator + 1.5)
    for leader in view.leaders:
        x, y = (value / denominator for value in leader.tip)
        dx, dy = leader.offset_mm
        text_width = sum(0.9 if char.isascii() else 1.39 for char in leader.text) * leader_text_height(denominator)
        left = min(left, *(x + u for u, _ in leader.vertices_mm))
        right = max(right, x + dx + text_width, *(x + u for u, _ in leader.vertices_mm))
        bottom = min(bottom, *(y + v for _, v in leader.vertices_mm))
        top = max(top, y + dy + leader_text_height(denominator), *(y + v for _, v in leader.vertices_mm))
    for dim in view.dimensions:
        x1, y1 = (value / denominator for value in dim.start)
        x2, y2 = (value / denominator for value in dim.end)
        pad = max(1.6, len(dim.label) * DIMENSION_TEXT_SIZE_MM * 0.36 * annotation_scale)
        if dim.orientation == "horizontal":
            y = dim.line_position / denominator
            mid = (x1 + x2) / 2
            left, right = min(left, x1, x2, mid - pad), max(right, x1, x2, mid + pad)
            bottom, top = min(bottom, y1, y2, y - 1.2), max(top, y1, y2, y + ANNOTATION_CLEARANCE_MM * annotation_scale)
        else:
            x = dim.line_position / denominator
            mid = (y1 + y2) / 2
            left, right = min(left, x1, x2, x - ANNOTATION_CLEARANCE_MM * annotation_scale), max(right, x1, x2, x + ANNOTATION_CLEARANCE_MM * annotation_scale)
            bottom, top = min(bottom, y1, y2, mid - pad), max(top, y1, y2, mid + pad)
    return left, bottom, right, top


def place_bolt_note(view: ViewDrawing, denominator: int) -> ViewDrawing:
    """Put the callout outside the existing dimensions and route around them."""
    if not view.leaders:
        return view
    note, = view.leaders
    tip_x, tip_y = (value / denominator for value in note.tip)
    left, _, _, top = view_bounds(replace(view, leaders=()), denominator)
    bridge_x = left - 2.0
    bridge_y = tip_y + 0.7
    text_y = top + 1.5
    bridge_gaps = set()
    for dim in view.dimensions:
        if dim.orientation != "horizontal":
            continue
        dimension_y = dim.line_position / denominator
        for point_x, point_y in (dim.start, dim.end):
            line_x = point_x / denominator
            if bridge_x < line_x < tip_x:
                bridge_height = tip_y + (bridge_y - tip_y) * (line_x - tip_x) / (bridge_x - tip_x)
                start_y = point_y / denominator
                if start_y + 0.8 < bridge_height < dimension_y + 0.8:
                    bridge_gaps.add(line_x - tip_x)
    # The first segment stays below the upper dimension chain. The vertical
    # segment runs outside the dimension extents, so the dimension lanes keep
    # their measured endpoints, offsets, and complete extension lines.
    note = replace(
        note,
        offset_mm=(max(0.0, bridge_x + 5.0) - tip_x, text_y - tip_y),
        elbows_mm=((bridge_x - tip_x, bridge_y - tip_y), (bridge_x - tip_x, text_y - tip_y)),
        bridge_gaps_mm=tuple(sorted(bridge_gaps)),
    )
    return replace(view, leaders=(note,))


def side_view_offset(drawing: ModuleDrawing) -> float:
    if drawing.side_view is None:
        return 0.0
    denominator = drawing.scale_denominator
    return max(
        drawing.front_view.outline.bounds[2] / denominator + SIDE_VIEW_GAP_MM,
        view_bounds(drawing.front_view, drawing.scale_denominator)[2] - view_bounds(drawing.side_view, drawing.scale_denominator)[0] + VIEW_CLEARANCE_MM,
    )


def _content_floor(drawing: ModuleDrawing) -> float:
    if drawing.use_left_footer_space:
        return LEFT_FOOTER_FLOOR_MM
    return TITLE_BLOCK_TOP_MM + DETAIL_TITLE_CLEARANCE_MM


def view_placement(drawing: ModuleDrawing) -> ViewPlacement:
    denominator = drawing.scale_denominator
    upper = [view_bounds(drawing.front_view, denominator)]
    if drawing.side_view is not None:
        upper.append(view_bounds(drawing.side_view, drawing.scale_denominator))
    upper_bottom = min(box[1] for box in upper)
    upper_top = max(box[3] for box in upper)
    _, board_bottom, _, board_top = view_bounds(drawing.board_view, drawing.scale_denominator)
    ceiling = PAGE_HEIGHT_MM - FRAME_INSET_MM - 2.0
    floor = _content_floor(drawing)
    available = ceiling - floor
    views_span = upper_top - upper_bottom + board_top - board_bottom
    detail_height = _detail_block_height(drawing)
    below_height = detail_height + DETAIL_VIEW_CLEARANCE_MM if detail_height else 0.0
    below_gap = min(VIEW_CLEARANCE_MM, max(MIN_VERTICAL_VIEW_CLEARANCE_MM, available - views_span - below_height))
    detail_on_side = bool(detail_height and views_span + below_gap + below_height > available + 1e-6)
    view_gap = VIEW_CLEARANCE_MM if detail_on_side else below_gap
    view_height = views_span + view_gap
    outline_bottom = drawing.board_view.outline.bounds[1] / denominator
    if detail_on_side:
        # The side text starts at the outline bottom, above any lower dimensions.
        side_height = outline_bottom - board_bottom + detail_height
        view_gap_extra = min(6.0, max(0.0, available - max(view_height, side_height)) / 3)
        occupied = max(view_height + view_gap_extra, side_height)
        board_y = min(floor + (available - occupied) / 2, ceiling - view_height) - board_bottom
        detail_y = max(floor, board_y + outline_bottom)
    else:
        spare = max(0.0, available - view_height - below_height)
        view_gap_extra = min(6.0, spare / (4 if detail_height else 3))
        detail_gap_extra = min(4.0, spare / 4) if detail_height else 0.0
        margin = (available - view_height - below_height - view_gap_extra - detail_gap_extra) / 2
        detail_y = floor + margin + detail_height
        board_y = floor + margin + below_height + detail_gap_extra - board_bottom
    top_y = board_y + board_top + view_gap + view_gap_extra - upper_bottom
    return ViewPlacement(top_y, board_y, side_view_offset(drawing), detail_y, detail_on_side)


def outline_width(view, denominator: int = 10) -> float:
    min_x, _min_y, max_x, _max_y = view.outline.bounds
    return (max_x - min_x) * VIEW_SCALE * 10 / denominator


def top_row_width(drawing: ModuleDrawing) -> float:
    width = outline_width(drawing.front_view, drawing.scale_denominator)
    if drawing.side_view is not None:
        width = side_view_offset(drawing) + outline_width(drawing.side_view, drawing.scale_denominator)
    return width


def details_width(drawing: ModuleDrawing) -> float:
    units = [_text_width(line, 0.47, 0.76) for line in _detail_rows(drawing)]
    return min(
        PAGE_CONTENT_WIDTH_MM - PANEL_INNER_MARGIN_MM * 2,
        max(units, default=0.0),
    )


def _text_width(line: str, ascii_width: float, cjk_width: float) -> float:
    return sum(0.33 if char.isspace() else ascii_width if char.isascii() else cjk_width
               for char in line) * DETAIL_TEXT_SIZE_MM


def _detail_rows(drawing: ModuleDrawing) -> tuple[str, ...]:
    return tuple("\n".join(drawing.details).splitlines())


def _detail_block_height(drawing: ModuleDrawing) -> float:
    rows = len(_detail_rows(drawing))
    if rows == 0:
        return 0.0
    return (DETAIL_TEXT_SIZE_MM + (rows - 1) * DETAIL_LINE_HEIGHT_MM) * annotation_factor(drawing.scale_denominator) + 1.0


def _detail_row_width(line: str) -> float:
    # Budget for the wider Song-style fallback as well as the SHX plot fonts.
    return _text_width(line, 0.82, 1.39)


def _preferred_detail_width(drawing: ModuleDrawing, measure: Callable[[str], float] | None) -> float:
    longest = max(map(measure or _detail_row_width, _detail_rows(drawing)), default=0.0)
    return longest * annotation_factor(drawing.scale_denominator) + DETAIL_WIDTH_CLEARANCE_MM


def _drawing_right(drawing: ModuleDrawing) -> float:
    right = max(view_bounds(drawing.front_view, drawing.scale_denominator)[2], view_bounds(drawing.board_view, drawing.scale_denominator)[2])
    if drawing.side_view is not None:
        right = max(right, side_view_offset(drawing) + view_bounds(drawing.side_view, drawing.scale_denominator)[2])
    return right


def _side_details(drawing: ModuleDrawing) -> bool:
    return view_placement(drawing).detail_on_side


def _side_detail_width(drawing: ModuleDrawing, measure: Callable[[str], float] | None) -> float:
    available = (PAGE_CONTENT_WIDTH_MM - _drawing_right(drawing) - SIDE_DETAIL_GAP_MM
                 - _panel_inner_margin(drawing) - SIDE_DETAIL_RIGHT_MARGIN_MM)
    return max(1.0, min(_preferred_detail_width(drawing, measure), available))


def geometry_width(drawing: ModuleDrawing, measure: Callable[[str], float] | None = None) -> float:
    width = max(top_row_width(drawing), outline_width(drawing.board_view, drawing.scale_denominator))
    if _side_details(drawing):
        return _drawing_right(drawing) + SIDE_DETAIL_GAP_MM + _side_detail_width(drawing, measure)
    return width


def _panel_inner_margin(drawing: ModuleDrawing) -> float:
    left = min(view_bounds(drawing.front_view, drawing.scale_denominator)[0], view_bounds(drawing.board_view, drawing.scale_denominator)[0])
    return max(PANEL_INNER_MARGIN_MM, 0.5 - left)


def _view_right_edge(drawing: ModuleDrawing, outline_span: float) -> float:
    return max(outline_span + PANEL_INNER_MARGIN_MM, _drawing_right(drawing) + 0.5)


def panel_gap(left: ModuleDrawing, right: ModuleDrawing) -> float:
    if _side_details(left) and _side_details(right):
        return SIDE_PANEL_GAP_MM
    return PANEL_GAP_MM


def panel_content_left(
    drawing: ModuleDrawing, panel_width: float, content_width: float,
    measure: Callable[[str], float] | None = None,
) -> float:
    left_margin = _panel_inner_margin(drawing)
    if _side_details(drawing):
        return left_margin
    right_limit = panel_width - _view_right_edge(drawing, content_width)
    if not _center_details(drawing):
        content_width = max(content_width, min(_preferred_detail_width(drawing, measure), panel_width))
    return max(left_margin, min((panel_width - content_width) / 2, right_limit))


def module_required_width(
    drawing: ModuleDrawing, measure: Callable[[str], float] | None = None, *, compact: bool = False,
) -> float:
    content_width = geometry_width(drawing, measure)
    margin = _panel_inner_margin(drawing)
    detail_factor = COMPACT_DETAIL_WIDTH_FACTOR if compact else 1.0
    if _side_details(drawing):
        details = _side_detail_width(drawing, measure) * detail_factor
        return max(PANEL_MIN_WIDTH_MM, _drawing_right(drawing) + SIDE_DETAIL_GAP_MM
                   + details + margin + SIDE_DETAIL_RIGHT_MARGIN_MM)
    geometry_span = _view_right_edge(drawing, content_width) + margin
    text_margins = 2 * PANEL_INNER_MARGIN_MM if _center_details(drawing) else margin + PANEL_INNER_MARGIN_MM
    text_span = min(PAGE_CONTENT_WIDTH_MM, _preferred_detail_width(drawing, measure) * detail_factor + text_margins) if drawing.details else 0.0
    return max(PANEL_MIN_WIDTH_MM, geometry_span, text_span)


def fits_sheet_height(drawing: ModuleDrawing) -> bool:
    placement = view_placement(drawing)
    lower = placement.board_y + view_bounds(drawing.board_view, drawing.scale_denominator)[1]
    return lower >= _content_floor(drawing) - 1e-6


def _center_details(drawing: ModuleDrawing) -> bool:
    left, _, right, _ = drawing.front_view.outline.bounds
    return right - left <= CENTERED_MODULE_MAX_LENGTH_MM


def detail_box(placed: PlacedModule) -> tuple[float, float]:
    drawing = placed.drawing
    if _side_details(drawing):
        left = placed.content_x_mm + _drawing_right(drawing) + SIDE_DETAIL_GAP_MM
        available = placed.x_mm + placed.panel_width_mm - SIDE_DETAIL_RIGHT_MARGIN_MM - left
        return left, available
    right = placed.x_mm + placed.panel_width_mm - PANEL_INNER_MARGIN_MM
    if _center_details(drawing):
        center = placed.content_x_mm + max(top_row_width(drawing), outline_width(drawing.board_view, drawing.scale_denominator)) / 2
        ideal_left = center - details_width(drawing) / 2
        preferred_width = _preferred_detail_width(drawing, placed.measure_detail)
        left = max(placed.x_mm + PANEL_INNER_MARGIN_MM, min(ideal_left, right - preferred_width))
    else:
        left = placed.content_x_mm
    available = right - left
    return left, available


def detail_vertical_anchor(placed: PlacedModule) -> tuple[float, bool]:
    placement = view_placement(placed.drawing)
    return placement.detail_y, placement.detail_on_side


def detail_lines(placed: PlacedModule) -> tuple[str, ...]:
    return _detail_rows(placed.drawing)


def detail_line_width_factor(line: str, available: float, measure: Callable[[str], float] | None = None,
                             text_scale: float = 1.0) -> float:
    usable = max(1.0, available - DETAIL_WIDTH_CLEARANCE_MM)
    # The default width is a layout estimate, so keep a small margin for the
    # actual glyph advances of the fallback font used when plotting the DXF.
    width = (measure(line) if measure else _detail_row_width(line) * 1.07) * text_scale
    return usable / width if width > usable else 1.0
