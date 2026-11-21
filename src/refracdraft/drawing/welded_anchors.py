from __future__ import annotations

import re

from refracdraft.domain.models import AnchorParameters, AnchorType
from refracdraft.geometry.primitives import Polyline, rectangle
from refracdraft.reference.library import ReferenceLibrary, SymbolGeometry


def _bolt_diameter(anchor: AnchorParameters) -> float:
    thread = re.match(r"M(\d+(?:\.\d+)?)", anchor.thread_spec, flags=re.IGNORECASE)
    return float(thread[1]) if thread else 8.0


def welded_bolt_symbol(
    reference: ReferenceLibrary, anchor: AnchorParameters, exposure: float, embedded: float,
) -> SymbolGeometry:
    """Place the source L-foot and tip at their specified axial positions."""
    parts = []
    foot_y = -embedded
    if anchor.anchor_type == AnchorType.WELDED_DIAMOND:
        shoe = reference.welded_diamond_shoe.polylines
        shoe_top = max(line.bounds[3] for line in shoe)
        parts.extend(line.transformed(ty=foot_y - shoe_top) for line in shoe)

    size = _bolt_diameter(anchor) / 8
    profile = reference.welded_bolt_profile
    source_tip = min(y for line in profile for _, y in line.points)
    # Between the bend tangent and the start of the tip, the shaft is straight.
    bend_end, tip_start = 10.25, 78.0
    span = exposure - foot_y
    minimum_span = (bend_end - source_tip - tip_start) * size
    if span <= minimum_span:
        raise ValueError("螺栓长度不足以容纳 L 形折弯和端部")

    def axial(y: float) -> float:
        y = -y
        if y <= bend_end:
            return foot_y + y * size
        if y >= tip_start:
            return exposure - (-source_tip - y) * size
        return foot_y + bend_end * size + (y - bend_end) / (tip_start - bend_end) * (span - minimum_span)

    # Both coordinates are reversed (a 180° rotation). The bend bulge and end
    # proportions survive, including when the exterior length changes.
    parts.extend(
        Polyline(tuple((-x * size, axial(y)) for x, y in line.points), line.closed, line.bulges)
        for line in profile
    )
    center = Polyline(((0.0, foot_y), (0.0, exposure)), closed=False)
    return SymbolGeometry(
        (*parts, center),
        (7,) * len(parts) + (1,),
        (13,) * (len(parts) + 1),
        ("CONTINUOUS",) * len(parts) + ("CENTER2",),
    )


def welded_side_symbol(
    reference: ReferenceLibrary, anchor: AnchorParameters, mounting_x: float, center_y: float,
    exposure: float, embedded: float,
) -> SymbolGeometry:
    """Project the anchor body and the bolt, looking along the L-foot."""
    shape = AnchorType.M_SHAPE if anchor.anchor_type == AnchorType.WELDED_M else AnchorType.DIAMOND
    body = reference.side_anchor_symbol(shape.value)
    start = min(line.bounds[0] for line in body.polylines)
    bottom = min(line.bounds[1] for line in body.polylines)
    top = max(line.bounds[3] for line in body.polylines)
    scale_y = anchor.length_mm / (top - bottom) if anchor.length_mm else 1.0
    joint = mounting_x + embedded
    body_lines = tuple(line.transformed(
        sy=scale_y, tx=joint - start, ty=center_y - (bottom + top) / 2 * scale_y,
    ) for line in body.polylines)

    diameter = _bolt_diameter(anchor)
    tip = mounting_x - exposure
    shank = rectangle(exposure + embedded, diameter).transformed(tx=tip, ty=center_y - diameter / 2)
    center = Polyline(((tip, center_y), (joint, center_y)), closed=False)
    return SymbolGeometry(
        (*body_lines, shank, center),
        (*body.colors, 7, 1),
        (*body.lineweights, 13, 13),
        (*body.linetypes, "CONTINUOUS", "CENTER2"),
    )
