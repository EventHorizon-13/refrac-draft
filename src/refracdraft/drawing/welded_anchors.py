from __future__ import annotations

import re

from refracdraft.domain.models import AnchorParameters, AnchorType
from refracdraft.geometry.primitives import Polyline
from refracdraft.reference.library import ReferenceLibrary, SymbolGeometry


def welded_bolt_symbol(
    reference: ReferenceLibrary, anchor: AnchorParameters, exposure: float, embedded: float,
) -> SymbolGeometry:
    """Place the source L-foot and tip at their specified axial positions."""
    parts = []
    foot_y = 0.0
    if anchor.anchor_type == AnchorType.WELDED_DIAMOND:
        shoe = reference.welded_diamond_shoe.polylines
        shoe_bottom = min(line.bounds[1] for line in shoe)
        shoe_top = max(line.bounds[3] for line in shoe)
        foot_y = -embedded + shoe_top - shoe_bottom
        if foot_y > 0:
            raise ValueError("埋入长度不足以容纳焊接菱形底座")
        parts.extend(line.transformed(ty=-embedded - shoe_bottom) for line in shoe)

    thread = re.match(r"M(\d+(?:\.\d+)?)", anchor.thread_spec, flags=re.IGNORECASE)
    size = float(thread[1]) / 8 if thread else 1.0
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
