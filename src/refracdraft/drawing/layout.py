from __future__ import annotations

from refracdraft.drawing.model import ModuleDrawing


VIEW_SCALE = 0.0992
SIDE_VIEW_GAP_MM = 14.0
TOP_VIEW_BOTTOM_MM = 150.0
BOARD_VIEW_BOTTOM_MM = 106.17
PAGE_LEFT_MM = 7.0
PAGE_CONTENT_WIDTH_MM = 283.0
PANEL_INNER_MARGIN_MM = 8.0
PANEL_GAP_MM = 6.0
PANEL_MIN_WIDTH_MM = 58.0
DETAIL_TEXT_SIZE_MM = 3.60
DETAIL_BASELINES_MM = (82.90, 76.20, 69.55, 62.79, 56.36, 49.71, 44.15, 38.95)


def outline_width(view) -> float:
    min_x, _min_y, max_x, _max_y = view.outline.bounds
    return (max_x - min_x) * VIEW_SCALE


def top_row_width(drawing: ModuleDrawing) -> float:
    width = outline_width(drawing.front_view)
    if drawing.side_view is not None:
        width += SIDE_VIEW_GAP_MM + outline_width(drawing.side_view)
    return width


def _detail_text_width(text: str, size_mm: float, horizontal_scale: float) -> float:
    # ReportLab's CJK font advances are narrower after the drawing's horizontal squeeze.
    units = sum(0.32 if ord(char) < 128 else 0.58 for char in text)
    return units * size_mm * horizontal_scale


def details_width(drawing: ModuleDrawing) -> float:
    widths = [_detail_text_width(line, DETAIL_TEXT_SIZE_MM, 0.67) for line in drawing.details]
    return max(widths, default=0.0)


def module_content_width(drawing: ModuleDrawing) -> float:
    return max(
        top_row_width(drawing),
        outline_width(drawing.board_view),
        details_width(drawing),
    )


def module_required_width(drawing: ModuleDrawing) -> float:
    content_width = module_content_width(drawing)
    return max(PANEL_MIN_WIDTH_MM, content_width + PANEL_INNER_MARGIN_MM * 2.0)


def detail_baseline(index: int) -> float:
    if index < len(DETAIL_BASELINES_MM):
        return DETAIL_BASELINES_MM[index]
    return DETAIL_BASELINES_MM[-1] - (index - 6) * 5.2
