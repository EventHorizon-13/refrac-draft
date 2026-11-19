from __future__ import annotations

from refracdraft.drawing.model import ModuleDrawing, PlacedModule, ViewDrawing


VIEW_SCALE = 0.0992
SIDE_VIEW_GAP_MM = 14.0
TOP_VIEW_BOTTOM_MM = 150.0
BOARD_VIEW_BOTTOM_MM = 106.17
VIEW_VERTICAL_GAP_MM = 10.0
VIEW_ANNOTATION_PADDING_MM = 1.5
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
DETAIL_LINE_SPACING = 0.76
DETAIL_LINE_HEIGHT_MM = DETAIL_TEXT_SIZE_MM * (5 / 3) * DETAIL_LINE_SPACING
DETAIL_TOP_MM = 94.0
def view_visual_bounds(view: ViewDrawing) -> tuple[float, float, float, float]:
    """Return local model-space bounds including visible linework and dimensions."""
    min_x, min_y, max_x, max_y = view.outline.bounds

    def include(points) -> None:
        nonlocal min_x, min_y, max_x, max_y
        for x, y in points:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

    for line in (*view.internal_lines, *view.cutouts, *view.anchor_symbols):
        include(line.flattened_points())

    for dimension in view.dimensions:
        x1, y1 = dimension.start
        x2, y2 = dimension.end
        include(((x1, y1), (x2, y2)))
        if dimension.orientation == "horizontal":
            dimension_y = max(y1, y2) + dimension.offset
            include(((x1, dimension_y), (x2, dimension_y)))
        else:
            dimension_x = min(x1, x2) - dimension.offset
            include(((dimension_x, y1), (dimension_x, y2)))
    return min_x, min_y, max_x, max_y


def top_view_bottom_mm(drawing: ModuleDrawing) -> float:
    """Place the first-angle upper views with clear space above the board face."""
    top_views = (drawing.front_view,) if drawing.side_view is None else (
        drawing.front_view,
        drawing.side_view,
    )
    top_bounds = tuple(view_visual_bounds(view) for view in top_views)
    top_min_y = min(bounds[1] for bounds in top_bounds)
    top_max_y = max(bounds[3] for bounds in top_bounds)
    board_top = BOARD_VIEW_BOTTOM_MM + view_visual_bounds(drawing.board_view)[3] * VIEW_SCALE
    required_bottom = (
        board_top
        + VIEW_VERTICAL_GAP_MM
        + VIEW_ANNOTATION_PADDING_MM * 2.0
        - top_min_y * VIEW_SCALE
    )
    bottom = max(TOP_VIEW_BOTTOM_MM, required_bottom)
    upper_limit = PAGE_HEIGHT_MM - FRAME_INSET_MM
    if bottom + top_max_y * VIEW_SCALE + VIEW_ANNOTATION_PADDING_MM > upper_limit:
        raise ValueError(f"{drawing.module_id}: 第一角法视图超出 A4 图框，请增大图幅或减小模块高度")
    return bottom


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


def panel_content_left(drawing: ModuleDrawing, panel_width: float, content_width: float) -> float:
    left, _, right, _ = drawing.front_view.outline.bounds
    if right - left > CENTERED_MODULE_MAX_LENGTH_MM:
        content_width = max(geometry_width(drawing), details_width(drawing))
    return max(PANEL_INNER_MARGIN_MM, (panel_width - content_width) / 2)


def module_required_width(drawing: ModuleDrawing) -> float:
    content_width = max(geometry_width(drawing), details_width(drawing))
    return max(PANEL_MIN_WIDTH_MM, content_width + PANEL_INNER_MARGIN_MM * 2.0)


def detail_box(placed: PlacedModule) -> tuple[float, float]:
    width = details_width(placed.drawing)
    left = placed.x_mm + panel_content_left(placed.drawing, placed.panel_width_mm, width)
    return left, placed.x_mm + placed.panel_width_mm - PANEL_INNER_MARGIN_MM - left
