from __future__ import annotations

from dataclasses import dataclass
import re

from refracdraft.drawing.model import ModuleDrawing, PlacedModule, ViewDrawing


VIEW_SCALE = 0.0992
SIDE_VIEW_GAP_MM = 14.0
VIEW_CLEARANCE_MM = 10.0
TOP_VIEW_BOTTOM_MM = 150.0
BOARD_VIEW_BOTTOM_MM = 106.17
PAGE_HEIGHT_MM = 210.0
PAGE_LEFT_MM = 7.0
PAGE_CONTENT_WIDTH_MM = 283.0
PANEL_INNER_MARGIN_MM = 8.0
PANEL_GAP_MM = 6.0
PANEL_MIN_WIDTH_MM = 58.0
CENTERED_MODULE_MAX_LENGTH_MM = 350.0

# A 150 mm model-space inset is 15 mm on the 1:10 A4 sheet.
FRAME_INSET_MM = 7.0
TITLE_BLOCK_TOP_MM = 37.0
SEPARATOR_MARGIN_MM = 15.0
SEPARATOR_TOP_MM = PAGE_HEIGHT_MM - FRAME_INSET_MM - SEPARATOR_MARGIN_MM
SEPARATOR_BOTTOM_MM = TITLE_BLOCK_TOP_MM + SEPARATOR_MARGIN_MM

DETAIL_TEXT_SIZE_MM = 4.5
DIMENSION_TEXT_SIZE_MM = 3.2
DIMENSION_ARROW_SIZE_MM = 1.3
DETAIL_LINE_SPACING = 0.76
DETAIL_LINE_HEIGHT_MM = DETAIL_TEXT_SIZE_MM * (5 / 3) * DETAIL_LINE_SPACING
DETAIL_TOP_MM = 94.0
DETAIL_TITLE_CLEARANCE_MM = 4.0
ANNOTATION_CLEARANCE_MM = DIMENSION_TEXT_SIZE_MM + 1.6


@dataclass(frozen=True)
class ViewPlacement:
    top_y: float
    board_y: float
    side_x: float
    detail_y: float


def view_bounds(view: ViewDrawing) -> tuple[float, float, float, float]:
    """Conservative paper-space bounds of the visible geometry and its dimensions."""
    geometry = (view.outline, *view.internal_lines, *view.hidden_lines, *view.anchor_symbols, *view.cutouts)
    boxes = [line.bounds for line in geometry]
    left = min(box[0] for box in boxes) / 10
    bottom = min(box[1] for box in boxes) / 10
    right = max(box[2] for box in boxes) / 10
    top = max(box[3] for box in boxes) / 10
    for x, y in view.anchor_points:
        left, right = min(left, x / 10 - 1.5), max(right, x / 10 + 1.5)
        bottom, top = min(bottom, y / 10 - 1.5), max(top, y / 10 + 1.5)
    for dim in view.dimensions:
        x1, y1 = (value / 10 for value in dim.start)
        x2, y2 = (value / 10 for value in dim.end)
        pad = max(1.6, len(dim.label) * DIMENSION_TEXT_SIZE_MM * 0.36)
        if dim.orientation == "horizontal":
            y = dim.line_position / 10
            mid = (x1 + x2) / 2
            left, right = min(left, x1, x2, mid - pad), max(right, x1, x2, mid + pad)
            bottom, top = min(bottom, y1, y2, y - 1.2), max(top, y1, y2, y + ANNOTATION_CLEARANCE_MM)
        else:
            x = dim.line_position / 10
            mid = (y1 + y2) / 2
            left, right = min(left, x1, x2, x - ANNOTATION_CLEARANCE_MM), max(right, x1, x2, x + ANNOTATION_CLEARANCE_MM)
            bottom, top = min(bottom, y1, y2, mid - pad), max(top, y1, y2, mid + pad)
    return left, bottom, right, top


def side_view_offset(drawing: ModuleDrawing) -> float:
    if drawing.side_view is None:
        return 0.0
    return max(
        drawing.front_view.outline.bounds[2] / 10 + SIDE_VIEW_GAP_MM,
        view_bounds(drawing.front_view)[2] - view_bounds(drawing.side_view)[0] + VIEW_CLEARANCE_MM,
    )


def view_placement(drawing: ModuleDrawing) -> ViewPlacement:
    upper = [view_bounds(drawing.front_view)]
    if drawing.side_view is not None:
        upper.append(view_bounds(drawing.side_view))
    upper_bottom = min(box[1] for box in upper)
    upper_top = max(box[3] for box in upper)
    _, board_bottom, _, board_top = view_bounds(drawing.board_view)
    needed_top_y = BOARD_VIEW_BOTTOM_MM + board_top + VIEW_CLEARANCE_MM - upper_bottom
    ceiling = PAGE_HEIGHT_MM - FRAME_INSET_MM - 2.0
    top_y = min(max(TOP_VIEW_BOTTOM_MM, needed_top_y), ceiling - upper_top)
    board_y = min(BOARD_VIEW_BOTTOM_MM, top_y + upper_bottom - VIEW_CLEARANCE_MM - board_top)
    detail_y = min(DETAIL_TOP_MM, board_y + board_bottom - 2.0)
    return ViewPlacement(top_y, board_y, side_view_offset(drawing), detail_y)


def outline_width(view) -> float:
    min_x, _min_y, max_x, _max_y = view.outline.bounds
    return (max_x - min_x) * VIEW_SCALE


def top_row_width(drawing: ModuleDrawing) -> float:
    width = outline_width(drawing.front_view)
    if drawing.side_view is not None:
        width = side_view_offset(drawing) + outline_width(drawing.side_view)
    return width


def details_width(drawing: ModuleDrawing) -> float:
    units = [_text_width(line, 0.47, 0.76) for line in drawing.details]
    return min(
        PAGE_CONTENT_WIDTH_MM - PANEL_INNER_MARGIN_MM * 2,
        max(units, default=0.0),
    )


def _text_width(line: str, ascii_width: float, cjk_width: float) -> float:
    return sum(0.33 if char.isspace() else ascii_width if char.isascii() else cjk_width
               for char in line) * DETAIL_TEXT_SIZE_MM


def _wrapped_details(drawing: ModuleDrawing, width: float) -> tuple[str, ...]:
    rows = []
    for line in "\n".join(drawing.details).splitlines():
        current = ""
        for word in re.findall(r"[A-Za-z0-9.*×φ/³-]+|.", line):
            tokens = (word,) if _text_width(word, 0.76, 1.25) <= width else word
            for token in tokens:
                if current and _text_width(current + token, 0.76, 1.25) > width:
                    rows.append(current.rstrip())
                    current = ""
                current += token if current else token.lstrip()
        rows.append(current)
    return tuple(rows)


def _detail_height(drawing: ModuleDrawing, width: float) -> float:
    return len(_wrapped_details(drawing, width)) * DETAIL_LINE_HEIGHT_MM + 1.0


def _under_detail_width(drawing: ModuleDrawing) -> float:
    longest = max((_text_width(line, 0.76, 1.25) for line in drawing.details), default=0.0)
    return min(100.0, longest + 2)


def _drawing_right(drawing: ModuleDrawing) -> float:
    right = max(view_bounds(drawing.front_view)[2], view_bounds(drawing.board_view)[2])
    if drawing.side_view is not None:
        right = max(right, side_view_offset(drawing) + view_bounds(drawing.side_view)[2])
    return right


def _side_details(drawing: ModuleDrawing) -> bool:
    if not drawing.details:
        return False
    placement = view_placement(drawing)
    return placement.detail_y - _detail_height(drawing, _under_detail_width(drawing)) < (
        TITLE_BLOCK_TOP_MM + DETAIL_TITLE_CLEARANCE_MM
    )


def _side_detail_width(drawing: ModuleDrawing) -> float:
    return max(32.0, min(56.0, details_width(drawing) + 9, PAGE_CONTENT_WIDTH_MM - _drawing_right(drawing)
                        - VIEW_CLEARANCE_MM - 2 * _panel_inner_margin(drawing)))


def geometry_width(drawing: ModuleDrawing) -> float:
    width = max(top_row_width(drawing), outline_width(drawing.board_view))
    if _side_details(drawing):
        return _drawing_right(drawing) + VIEW_CLEARANCE_MM + _side_detail_width(drawing)
    return width


def _panel_inner_margin(drawing: ModuleDrawing) -> float:
    left, _, right, _ = drawing.board_view.outline.bounds
    positions = [dim.line_position for dim in drawing.board_view.dimensions if dim.orientation == "vertical"]
    outside = max(left - min(positions, default=left), max(positions, default=right) - right)
    return max(PANEL_INNER_MARGIN_MM, outside * VIEW_SCALE + DIMENSION_TEXT_SIZE_MM + 0.5)


def panel_content_left(drawing: ModuleDrawing, panel_width: float, content_width: float) -> float:
    left, _, right, _ = drawing.front_view.outline.bounds
    if right - left > CENTERED_MODULE_MAX_LENGTH_MM:
        content_width = max(geometry_width(drawing), details_width(drawing))
    return max(_panel_inner_margin(drawing), (panel_width - content_width) / 2)


def module_required_width(drawing: ModuleDrawing) -> float:
    content_width = geometry_width(drawing)
    if drawing.details and not _side_details(drawing):
        content_width = max(content_width, 2 * _under_detail_width(drawing) - details_width(drawing))
    return max(PANEL_MIN_WIDTH_MM, content_width + _panel_inner_margin(drawing) * 2.0)


def detail_box(placed: PlacedModule) -> tuple[float, float]:
    drawing = placed.drawing
    if _side_details(drawing):
        left = placed.content_x_mm + _drawing_right(drawing) + VIEW_CLEARANCE_MM
        available = placed.x_mm + placed.panel_width_mm - PANEL_INNER_MARGIN_MM - left
        return left, min(details_width(drawing) + 9, available)
    width = details_width(drawing)
    if drawing.side_view is None or drawing.front_view.outline.bounds[2] <= CENTERED_MODULE_MAX_LENGTH_MM:
        center = placed.content_x_mm + max(top_row_width(drawing), outline_width(drawing.board_view)) / 2
        left = max(placed.x_mm + PANEL_INNER_MARGIN_MM, center - width / 2)
    else:
        left = placed.content_x_mm
    available = placed.x_mm + placed.panel_width_mm - PANEL_INNER_MARGIN_MM - left
    return left, min(_under_detail_width(drawing), available)


def detail_top(placed: PlacedModule) -> float:
    drawing = placed.drawing
    placement = view_placement(drawing)
    if not _side_details(drawing):
        return placement.detail_y
    top = placement.top_y + view_bounds(drawing.front_view)[3]
    bottom = max(TITLE_BLOCK_TOP_MM + DETAIL_TITLE_CLEARANCE_MM,
                 placement.board_y + view_bounds(drawing.board_view)[1])
    height = _detail_height(drawing, detail_box(placed)[1])
    return min(top, (top + bottom + height) / 2)


def detail_lines(placed: PlacedModule) -> tuple[str, ...]:
    return _wrapped_details(placed.drawing, detail_box(placed)[1])
