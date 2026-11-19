from __future__ import annotations

from refracdraft.drawing.model import ModuleDrawing, PlacedModule


VIEW_SCALE = 0.0992
SIDE_VIEW_GAP_MM = 14.0
TOP_VIEW_BOTTOM_MM = 150.0
BOARD_VIEW_BOTTOM_MM = 106.17
PAGE_HEIGHT_MM = 210.0
PAGE_LEFT_MM = 7.0
PAGE_CONTENT_WIDTH_MM = 283.0
PANEL_INNER_MARGIN_MM = 8.0
PANEL_GAP_MM = 6.0
PANEL_MIN_WIDTH_MM = 58.0

# A 150 mm model-space inset is 15 mm on the 1:10 A4 sheet.
FRAME_INSET_MM = 7.0
TITLE_BLOCK_TOP_MM = 37.0
SEPARATOR_MARGIN_MM = 15.0
SEPARATOR_TOP_MM = PAGE_HEIGHT_MM - FRAME_INSET_MM - SEPARATOR_MARGIN_MM
SEPARATOR_BOTTOM_MM = TITLE_BLOCK_TOP_MM + SEPARATOR_MARGIN_MM

DETAIL_TEXT_SIZE_MM = 4.5
DIMENSION_TEXT_SIZE_MM = 3.2
DETAIL_LINE_SPACING = 0.76
DETAIL_LINE_HEIGHT_MM = DETAIL_TEXT_SIZE_MM * (5 / 3) * DETAIL_LINE_SPACING
DETAIL_TOP_MM = 94.0


def outline_width(view) -> float:
    min_x, _min_y, max_x, _max_y = view.outline.bounds
    return (max_x - min_x) * VIEW_SCALE


def top_row_width(drawing: ModuleDrawing) -> float:
    width = outline_width(drawing.front_view)
    if drawing.side_view is not None:
        width += SIDE_VIEW_GAP_MM + outline_width(drawing.side_view)
    return width


def details_width(drawing: ModuleDrawing) -> float:
    # Estimate advances conservatively for the SHX font pair and font fallbacks.
    units = [
        sum(0.4 if char.isspace() else 0.65 if char.isascii() else 0.95 for char in line)
        for line in drawing.details
    ]
    return min(
        PAGE_CONTENT_WIDTH_MM - PANEL_INNER_MARGIN_MM * 2,
        max(units, default=0.0) * DETAIL_TEXT_SIZE_MM,
    )


def geometry_width(drawing: ModuleDrawing) -> float:
    return max(top_row_width(drawing), outline_width(drawing.board_view))


def module_required_width(drawing: ModuleDrawing) -> float:
    content_width = max(geometry_width(drawing), details_width(drawing))
    return max(PANEL_MIN_WIDTH_MM, content_width + PANEL_INNER_MARGIN_MM * 2.0)


def detail_box(placed: PlacedModule) -> tuple[float, float]:
    width = details_width(placed.drawing)
    left = placed.x_mm + max(PANEL_INNER_MARGIN_MM, (placed.panel_width_mm - width) / 2)
    return left, placed.x_mm + placed.panel_width_mm - PANEL_INNER_MARGIN_MM - left
