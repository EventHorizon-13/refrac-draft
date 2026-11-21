from __future__ import annotations

from collections.abc import Callable

from dataclasses import dataclass, field

from refracdraft.geometry.primitives import Polyline


def linetype_role(value: str | None) -> str:
    """Classify imported CAD line styles for both preview and export."""
    name = (value or "").upper()
    if any(token in name for token in ("DASHDOT", "CENTER", "中心", "点划")):
        return "center"
    if any(token in name for token in ("DASH", "HIDDEN", "隐藏", "虚线")):
        return "hidden"
    return "continuous"


@dataclass(frozen=True)
class Dimension:
    start: tuple[float, float]
    end: tuple[float, float]
    label: str
    orientation: str = "horizontal"
    offset: float = 8.0

    @property
    def line_position(self) -> float:
        if self.orientation == "horizontal":
            return max(self.start[1], self.end[1]) + self.offset
        return min(self.start[0], self.end[0]) - self.offset


@dataclass(frozen=True)
class LeaderNote:
    tip: tuple[float, float]
    text: str
    offset_mm: tuple[float, float]


@dataclass(frozen=True)
class ViewDrawing:
    view_type: str
    label: str
    outline: Polyline
    dimensions: tuple[Dimension, ...] = ()
    anchor_symbols: tuple[Polyline, ...] = ()
    anchor_points: tuple[tuple[float, float], ...] = ()
    note: str = ""
    cutouts: tuple[Polyline, ...] = ()
    internal_lines: tuple[Polyline, ...] = ()
    # ACI color for each corresponding anchor polyline; preserves source-DXF layer colors.
    anchor_symbol_colors: tuple[int, ...] = ()
    # DXF lineweight in hundredths of a millimetre for each anchor polyline.
    anchor_symbol_lineweights: tuple[int, ...] = ()
    # Source-DXF linetype for each corresponding anchor polyline.
    anchor_symbol_linetypes: tuple[str, ...] = ()
    anchor_marker_style: str = "target"
    hidden_lines: tuple[Polyline, ...] = ()
    leaders: tuple[LeaderNote, ...] = ()


@dataclass(frozen=True)
class ModuleDrawing:
    module_id: str
    name: str
    details: tuple[str, ...]
    front_view: ViewDrawing
    side_view: ViewDrawing | None
    board_view: ViewDrawing
    warnings: tuple[str, ...] = ()
    scale_denominator: int = 10


@dataclass(frozen=True)
class PlacedModule:
    drawing: ModuleDrawing
    x_mm: float
    panel_width_mm: float
    panel_index: int
    # Shared left edge of the front and board-face views.
    content_x_mm: float = 0.0
    measure_detail: Callable[[str], float] | None = None


@dataclass(frozen=True)
class SheetPage:
    page_number: int
    modules: tuple[PlacedModule, ...]
    column_count: int
    scale_denominator: int = 10


@dataclass(frozen=True)
class DrawingDocument:
    project_name: str
    pages: tuple[SheetPage, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    filename_label: str = ""
