from __future__ import annotations

from collections.abc import Callable

from dataclasses import dataclass, replace

from refracdraft.drawing.model import Dimension, DrawingDocument, LeaderNote, ModuleDrawing, PlacedModule, ViewDrawing
from refracdraft.geometry.primitives import point_in_outline


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
    detail_x: float | None = None


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


def _leader_text_bounds(note: LeaderNote, denominator: int) -> tuple[float, float, float, float]:
    dx, dy = note.offset_mm
    x, y = note.tip[0] / denominator + dx, note.tip[1] / denominator + dy
    height = leader_text_height(denominator)
    width = sum(0.9 if char.isascii() else 1.39 for char in note.text) * height
    return (x - width, y, x, y + height) if note.align_right else (x, y, x + width, y + height)


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
        x1, y1, x2, y2 = _leader_text_bounds(leader, denominator)
        left, right = min(left, x, x1), max(right, x, x2)
        bottom, top = min(bottom, y, y1), max(top, y, y2)
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


def place_machining_dimensions(view: ViewDrawing, denominator: int) -> ViewDrawing:
    """Keep machining dimensions and their witnesses away from the anchors."""
    if not any(dim.machining for dim in view.dimensions):
        return view
    boxes = [line.bounds for line in view.anchor_symbols]
    boxes.extend((x - 1.5 * denominator, y - 1.5 * denominator,
                  x + 1.5 * denominator, y + 1.5 * denominator) for x, y in view.anchor_points)
    if not boxes:
        return _space_cut_dimension_lanes(view, denominator)

    clearance = ANNOTATION_CLEARANCE_MM * annotation_factor(denominator) * denominator
    dimensions = list(view.dimensions)
    for index, dim in enumerate(dimensions):
        if not dim.machining:
            continue
        axis = 0 if dim.orientation == "horizontal" else 1
        cross = 1 - axis
        low, high = sorted((dim.start[axis], dim.end[axis]))
        obstacles = [(box[axis], box[axis + 2], box[cross], box[cross + 2]) for box in boxes]

        def line_clear(lane: float) -> bool:
            return not any(
                a - clearance < high and b + clearance > low and c - clearance < lane < d + clearance
                for a, b, c, d in obstacles
            )

        def witnesses_clear(lane: float) -> bool:
            margin = 0.6 * denominator
            return not any(
                a - margin <= point[axis] <= b + margin
                and min(point[cross], lane) <= d + margin and max(point[cross], lane) >= c - margin
                for point in (dim.start, dim.end) for a, b, c, d in obstacles
            )

        position = dim.line_position
        if line_clear(position) and witnesses_clear(position):
            continue
        other_lanes = [
            other.line_position for j, other in enumerate(dimensions)
            if j != index and other.orientation == dim.orientation
            and min(other.start[axis], other.end[axis]) < high + clearance
            and max(other.start[axis], other.end[axis]) > low - clearance
        ]
        bounds = view.outline.bounds
        left = min(bounds[cross], *other_lanes, *(box[2] for box in obstacles)) - clearance
        right = max(bounds[cross + 2], *other_lanes, *(box[3] for box in obstacles)) + clearance
        lane = min((left, right), key=lambda value: (not witnesses_clear(value), abs(value - position)))
        dimensions[index] = replace(
            dim,
            offset=dim.offset + (lane - position) * (1 if axis == 0 else -1),
            short_witness_mm=None if witnesses_clear(lane) else 1.6,
        )
    return _space_cut_dimension_lanes(replace(view, dimensions=tuple(dimensions)), denominator)


def _space_cut_dimension_lanes(view: ViewDrawing, denominator: int) -> ViewDrawing:
    """Use common lanes for adjoining sizes and separate overlapping spans."""
    bounds = view.outline.bounds
    scale = annotation_factor(denominator) * denominator
    clearance = ANNOTATION_CLEARANCE_MM * scale
    dimensions = list(view.dimensions)
    for axis, orientation in ((0, "horizontal"), (1, "vertical")):
        cross = 1 - axis
        extents = {}
        for index, dim in enumerate(dimensions):
            if dim.orientation == orientation:
                lo, hi = sorted((dim.start[axis], dim.end[axis]))
                center = (lo + hi) / 2
                pad = max(1.6, len(dim.label) * DIMENSION_TEXT_SIZE_MM * 0.36) * scale
                extents[index] = (lo, hi, min(lo, center - pad), max(hi, center + pad))

        for sign, boundary in ((-1, bounds[cross]), (1, bounds[cross + 2])):
            distance = {i: sign * (dimensions[i].line_position - boundary) for i in extents}
            outside = sorted((i for i in extents if distance[i] > 1e-6), key=distance.get)
            inside = {i: d for i, d in distance.items() if d <= 1e-6}
            placed = {}
            for i in outside:
                dim = dimensions[i]
                lo, hi, left, right = extents[i]
                conflicts = [lane for j, lane in (inside | placed).items()
                             if left < extents[j][3] - 1e-6 and right > extents[j][2] + 1e-6]
                clear_of_outline = 4.0 if (axis == 0 and sign < 0) or (axis == 1 and sign > 0) else 1.0
                preferred = max(distance[i], clear_of_outline * scale)
                adjoining = [
                    lane for j, lane in placed.items()
                    if (abs(lo - extents[j][1]) < 1e-6 or abs(hi - extents[j][0]) < 1e-6)
                    and abs(lane - preferred) <= clearance
                    and lane >= clear_of_outline * scale
                    and all(abs(lane - other) >= clearance - 1e-6 for other in conflicts)
                ]
                lane = min(adjoining, key=lambda value: abs(value - preferred)) if adjoining else preferred
                while any(abs(lane - other) < clearance - 1e-6 for other in conflicts):
                    lane = max(other + clearance for other in conflicts if abs(lane - other) < clearance - 1e-6)
                placed[i] = lane
                shift = boundary + sign * lane - dim.line_position
                dimensions[i] = replace(dim, offset=dim.offset + shift * (1 if axis == 0 else -1))
    return replace(view, dimensions=tuple(dimensions))


def _dimension_plot_lines(dim: Dimension, denominator: int):
    axis = 0 if dim.orientation == "horizontal" else 1
    cross = 1 - axis
    lane = dim.line_position / denominator
    low, high = sorted((dim.start[axis] / denominator, dim.end[axis] / denominator))
    yield cross, lane, low, high
    for point in (dim.start, dim.end):
        datum = point[cross] / denominator
        direction = 1 if lane >= datum else -1
        start = lane - direction * dim.short_witness_mm if dim.short_witness_mm else datum + direction * 0.8
        end = lane + direction * 0.8
        yield axis, point[axis] / denominator, min(start, end), max(start, end)


def _dimension_text_boxes(view: ViewDrawing, denominator: int):
    factor = annotation_factor(denominator)
    for dim in view.dimensions:
        x = (dim.start[0] + dim.end[0]) / (2 * denominator)
        y = (dim.start[1] + dim.end[1]) / (2 * denominator)
        lane = dim.line_position / denominator
        pad = max(2.0, len(dim.label) * 1.25 * factor + 0.55)
        height = ANNOTATION_CLEARANCE_MM * factor
        if dim.orientation == "horizontal":
            yield (x - pad, lane - 0.4, x + pad, lane + height)
        else:
            yield (lane - height, y - pad, lane + 0.55, y + pad)


def _dimension_stroke_boxes(view: ViewDrawing, denominator: int):
    for dim in view.dimensions:
        for axis, lane, lo, hi in _dimension_plot_lines(dim, denominator):
            if axis == 0:
                yield (lane - 0.4, lo - 0.25, lane + 0.4, hi + 0.25)
            else:
                yield (lo - 0.25, lane - 0.4, hi + 0.25, lane + 0.4)


def _segment_interval(origin, delta, box) -> tuple[float, float] | None:
    """Return the fraction of a segment contained in a rectangular plot area."""
    enter, leave = 0.0, 1.0
    for axis in (0, 1):
        point, step = origin[axis], delta[axis]
        low, high = box[axis], box[axis + 2]
        if abs(step) < 1e-9:
            if point < low or point > high:
                return None
        else:
            a, b = sorted(((low - point) / step, (high - point) / step))
            enter, leave = max(enter, a), min(leave, b)
            if enter >= leave:
                return None
    return enter, leave


def _leader_with_clear_dimensions(note: LeaderNote, denominator: int, boxes) -> LeaderNote:
    tip = tuple(value / denominator for value in note.tip)
    gaps = sorted(interval for box in boxes if (interval := _segment_interval(tip, note.offset_mm, box)))
    return replace(note, interruptions=tuple(gaps))


def place_bolt_note(view: ViewDrawing, denominator: int) -> ViewDrawing:
    """Aim one straight callout at the clear row above the dimension text."""
    note = next((leader for leader in view.leaders if not leader.machining), None)
    if note is None:
        return view
    tip_x, tip_y = (value / denominator for value in note.tip)
    _, _, _, top = view_bounds(replace(view, leaders=()), denominator)
    rise = top + 1.5 - tip_y
    start = (tip_x, tip_y)
    labels = tuple(_dimension_text_boxes(view, denominator))
    strokes = tuple(_dimension_stroke_boxes(view, denominator))

    def score(run: float):
        delta = (run, rise)
        return (sum(_segment_interval(start, delta, box) is not None for box in labels),
                sum(_segment_interval(start, delta, box) is not None for box in strokes), run)

    run = min((-9.0, -6.0, -3.0, 3.0, 6.0, 9.0), key=score)
    note = _leader_with_clear_dimensions(replace(note, offset_mm=(run, rise)), denominator, (*labels, *strokes))
    return replace(view, leaders=(note, *(leader for leader in view.leaders if leader.machining)))


def _overlaps(a, b) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def view_label_position(view: ViewDrawing, module_id: str, denominator: int) -> tuple[float, float]:
    left, bottom, right, top = (value / denominator for value in view.outline.bounds)
    x, y = (left + right) / 2, (bottom + top) / 2
    board = view.view_type == "board-face"
    if not board and (view.anchor_symbols or view.anchor_points):
        y = (view.outline.points[0][1] + view.outline.points[1][1]) / (2 * denominator) + 5.0
    if view.note:
        return x, y

    font_height = 4.0 * annotation_factor(denominator)
    half_width = max(2.5, 0.43 * font_height * len(module_id))
    boxes = [*(_dimension_text_boxes(view, denominator)),
             *(_leader_text_bounds(note, denominator) for note in view.leaders)]
    for line in (*view.anchor_symbols, *view.cutouts):
        x1, y1, x2, y2 = (value / denominator for value in line.bounds)
        boxes.append((x1 - 0.4, y1 - 0.4, x2 + 0.4, y2 + 0.4))
    boxes.extend((px / denominator - 2.0, py / denominator - 2.0,
                  px / denominator + 2.0, py / denominator + 2.0) for px, py in view.anchor_points)
    step = half_width + 2.0
    for dy in (0.0, 5.0, -5.0, 10.0, -10.0):
        for dx in (0.0, -step, step, -2 * step, 2 * step):
            label_bottom = y + dy - (font_height / 2 if board else 0.5)
            x1, x2 = x + dx - half_width, x + dx + half_width
            label = (x1, label_bottom, x2, label_bottom + font_height + 0.7)
            if any(_overlaps(label, box) for box in boxes):
                continue
            if all(point_in_outline(view.outline, (px * denominator, py * denominator))
                   for px in (label[0], label[2]) for py in (label[1], label[3])):
                return x + dx, y + dy
    return x, y


def place_cut_notes(view: ViewDrawing, denominator: int, module_id: str) -> ViewDrawing:
    """Position straight blind-cut leaders in the free space nearest each wall."""
    if not any(note.machining for note in view.leaders):
        return view
    placed = [note for note in view.leaders if not note.machining]
    boxes = [_leader_text_bounds(note, denominator) for note in placed]
    left, bottom, right, top = (value / denominator for value in view.outline.bounds)
    center_x, center_y = (left + right) / 2, (bottom + top) / 2
    label_width = max(4.0, 1.6 * len(view.note or module_id))
    boxes.append((center_x - label_width, center_y - 2.5, center_x + label_width, center_y + 2.5))
    for line in (*view.anchor_symbols, *view.cutouts):
        x1, y1, x2, y2 = (value / denominator for value in line.bounds)
        boxes.append((x1 - 0.5, y1 - 0.5, x2 + 0.5, y2 + 0.5))
    for x, y in view.anchor_points:
        boxes.append((x / denominator - 2, y / denominator - 2, x / denominator + 2, y / denominator + 2))
    labels = tuple(_dimension_text_boxes(view, denominator))
    strokes = tuple(_dimension_stroke_boxes(view, denominator))
    edges = []
    for line in (view.outline, *view.internal_lines, *view.hidden_lines):
        points = line.points
        followers = points[1:] + points[:1] if line.closed else points[1:]
        for (x1, y1), (x2, y2) in zip(points, followers):
            edges.append((min(x1, x2) / denominator - 0.25, min(y1, y2) / denominator - 0.25,
                          max(x1, x2) / denominator + 0.25, max(y1, y2) / denominator + 0.25))

    for note in (item for item in view.leaders if item.machining):
        x, y = (value / denominator for value in note.tip)

        def cost(item: LeaderNote):
            x1, y1, x2, y2 = _leader_text_bounds(item, denominator)
            label = (x1 - 0.5, y1 - 0.5, x2 + 0.5, y2 + 0.5)
            dx, dy = item.offset_mm
            overflow = max(0.0, left - x1, x2 - right) + max(0.0, bottom - y1, y2 - top)
            return (sum(_overlaps(label, box) for box in (*boxes, *labels, *strokes, *edges)),
                    sum(_segment_interval((x, y), (dx, dy), box) is not None for box in (*boxes, *labels)),
                    sum(_segment_interval((x, y), (dx, dy), box) is not None for box in strokes),
                    overflow, abs(dx) + abs(dy))

        candidates = [
            replace(note, offset_mm=(dx, dy), align_right=dx < 0)
            for dx in (left - x - 2.0, -10.0, -6.0, -3.0, -1.0, 1.0, 3.0, 6.0, 10.0, right - x + 2.0)
            for dy in (-18.0, -12.0, -8.0, -5.0, 5.0, 8.0, 12.0, 18.0)
        ]
        candidates.extend(
            replace(note, offset_mm=(end_x - x, dy), align_right=right_aligned)
            for end_x, right_aligned in ((left + 1.2, False), (right - 1.2, True))
            for dy in (5.0, 8.0, 12.0, 18.0)
        )
        selected = min(candidates, key=cost)
        placed.append(_leader_with_clear_dimensions(selected, denominator, (*labels, *strokes)))
        boxes.append(_leader_text_bounds(selected, denominator))
    return replace(view, leaders=tuple(placed))


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
    outline_bottom = drawing.board_view.outline.bounds[1] / denominator
    side_x = side_view_offset(drawing)
    if detail_on_side or (detail_height and drawing.side_view is not None):
        # The side text starts at the outline bottom, above any lower dimensions.
        view_height = views_span + VIEW_CLEARANCE_MM
        side_height = outline_bottom - board_bottom + detail_height
        view_gap_extra = min(6.0, max(0.0, available - max(view_height, side_height)) / 3)
        occupied = max(view_height + view_gap_extra, side_height)
        board_y = min(floor + (available - occupied) / 2, ceiling - view_height) - board_bottom
        detail_y = max(floor, board_y + outline_bottom)
        top_y = board_y + board_top + VIEW_CLEARANCE_MM + view_gap_extra - upper_bottom
        if drawing.side_view is not None:
            below_side = top_y + upper[1][1] - DETAIL_VIEW_CLEARANCE_MM - detail_height
            right_of_board = _front_board_right(drawing) + SIDE_DETAIL_GAP_MM
            if below_side >= floor and right_of_board < _drawing_right(drawing) + SIDE_DETAIL_GAP_MM:
                return ViewPlacement(top_y, board_y, side_x, min(detail_y, below_side), True, right_of_board)
        if detail_on_side:
            return ViewPlacement(top_y, board_y, side_x, detail_y, True, _drawing_right(drawing) + SIDE_DETAIL_GAP_MM)

    view_height = views_span + below_gap
    spare = max(0.0, available - view_height - below_height)
    view_gap_extra = min(6.0, spare / (4 if detail_height else 3))
    detail_gap_extra = min(4.0, spare / 4) if detail_height else 0.0
    margin = (available - view_height - below_height - view_gap_extra - detail_gap_extra) / 2
    detail_y = floor + margin + detail_height
    board_y = floor + margin + below_height + detail_gap_extra - board_bottom
    top_y = board_y + board_top + below_gap + view_gap_extra - upper_bottom
    return ViewPlacement(top_y, board_y, side_x, detail_y, False)


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


def _front_board_right(drawing: ModuleDrawing) -> float:
    return max(view_bounds(drawing.front_view, drawing.scale_denominator)[2],
               view_bounds(drawing.board_view, drawing.scale_denominator)[2])


def _drawing_right(drawing: ModuleDrawing) -> float:
    right = _front_board_right(drawing)
    if drawing.side_view is not None:
        right = max(right, side_view_offset(drawing) + view_bounds(drawing.side_view, drawing.scale_denominator)[2])
    return right


def _side_details(drawing: ModuleDrawing) -> bool:
    return view_placement(drawing).detail_on_side


def _side_detail_width(drawing: ModuleDrawing, detail_x: float, measure: Callable[[str], float] | None) -> float:
    available = (PAGE_CONTENT_WIDTH_MM - detail_x
                 - _panel_inner_margin(drawing) - SIDE_DETAIL_RIGHT_MARGIN_MM)
    return max(1.0, min(_preferred_detail_width(drawing, measure), available))


def geometry_width(drawing: ModuleDrawing, measure: Callable[[str], float] | None = None) -> float:
    width = max(top_row_width(drawing), outline_width(drawing.board_view, drawing.scale_denominator))
    detail_x = view_placement(drawing).detail_x
    if detail_x is not None:
        return max(_drawing_right(drawing), detail_x + _side_detail_width(drawing, detail_x, measure))
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
    detail_x = view_placement(drawing).detail_x
    if detail_x is not None:
        details = _side_detail_width(drawing, detail_x, measure) * detail_factor
        return max(PANEL_MIN_WIDTH_MM, _drawing_right(drawing) + margin + 0.5,
                   detail_x + details + margin + SIDE_DETAIL_RIGHT_MARGIN_MM)
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
    detail_x = view_placement(drawing).detail_x
    if detail_x is not None:
        left = placed.content_x_mm + detail_x
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
