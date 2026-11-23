from __future__ import annotations

from collections.abc import Callable

from pathlib import Path

import ezdxf
from ezdxf.addons.importer import Importer
from ezdxf.enums import TextEntityAlignment

from refracdraft.drawing.layout import (
    DETAIL_LINE_SPACING,
    TITLE_BLOCK_LEFT_MM,
    DETAIL_TEXT_SIZE_MM,
    FILENAME_LABEL_HEIGHT_MM,
    FILENAME_LABEL_POSITION,
    FILENAME_LABEL_WIDTH_MM,
    DIMENSION_ARROW_SIZE_MM,
    DIMENSION_TEXT_SIZE_MM,
    SEPARATOR_BOTTOM_MM,
    SEPARATOR_TOP_MM,
    PAGE_WIDTH_MM,
    PAGE_HEIGHT_MM,
    annotation_factor,
    detail_box,
    page_model_origins,
    leader_text_height,
    detail_line_width_factor,
    detail_lines,
    detail_vertical_anchor,
    view_label_position,
    view_placement,
)
from refracdraft.drawing.model import DrawingDocument, ViewDrawing, linetype_role


LAYER_COLORS = {
    "OUTLINE": 7,
    "DIMENSIONS": 4,
    "HIDDEN": 7,
    "ANCHORS": 5,
    "CENTER": 1,
    "TEXT": 7,
    "FRAME": 7,
}

TEXT_STYLE = "大字体"
MODEL_SCALE = 10.0
DETAIL_TEXT_HEIGHT = DETAIL_TEXT_SIZE_MM * MODEL_SCALE
VALUE_TEXT_HEIGHT = 40.0
DIMENSION_OVERRIDE = {
    "dimtxsty": TEXT_STYLE,
    "dimclrd": 4,
    "dimclre": 4,
    "dimclrt": 3,
    "dimtad": 1,
    "dimjust": 0,
    "dimtih": 0,
    "dimtoh": 0,
}
DIMENSION_FALLBACK = {
    "dimscale": 20.0,
    "dimtad": 1,
}


def _detail_mtext(
    lines: tuple[str, ...], available_width: float, measure: Callable[[str], float] | None = None,
    text_scale: float = 1.0,
) -> str:
    paragraphs = []
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
        factor = detail_line_width_factor(line, available_width, measure, text_scale)
        if factor < 1.0:
            escaped = rf"{{\W{factor:.6f};{escaped}}}"
        paragraphs.append(escaped)
    return r"\P".join(paragraphs)


def _ensure_text_styles(doc) -> None:
    for name in ("工程字", TEXT_STYLE):
        if name in doc.styles:
            style = doc.styles.get(name)
        else:
            style = doc.styles.new(name)
        style.dxf.font = "gbenor.shx"
        style.dxf.bigfont = "gbcbig.shx"


def _ensure_dimension_style(doc, source=None, denominator: int = 10) -> None:
    name = f"_{denominator}"
    attributes = {**DIMENSION_FALLBACK, **DIMENSION_OVERRIDE}
    if source is not None:
        try:
            source_style = source.dimstyles.get(name)
            attributes.update({
                key: value
                for key, value in source_style.dxf.all_existing_dxf_attribs().items()
                if key not in {"handle", "owner"}
            })
            attributes.update(DIMENSION_OVERRIDE)
        except (KeyError, ValueError):
            pass
    scale = attributes["dimscale"] or 1
    attributes["dimtxt"] = DIMENSION_TEXT_SIZE_MM * annotation_factor(denominator) * denominator / scale
    attributes["dimasz"] = DIMENSION_ARROW_SIZE_MM * denominator / scale
    attributes["dimgap"] = 0.6 * denominator / scale
    attributes["dimexo"] = 0.9 * denominator / scale
    attributes["dimexe"] = 0.8 * denominator / scale
    if name in doc.dimstyles:
        style = doc.dimstyles.get(name)
        for key, value in attributes.items():
            style.dxf.set(key, value)
    else:
        doc.dimstyles.new(name, dxfattribs=attributes)


def _resolve_linetype(doc, linetype: str | None) -> str | None:
    if not linetype:
        return None
    name = linetype.upper()
    if name in {"BYLAYER", "BYBLOCK", "CONTINUOUS"}:
        return None
    if name in doc.linetypes:
        return name
    return {"center": "CENTER2", "hidden": "HIDDEN"}.get(linetype_role(name))


def _add_polyline(msp, points, closed=True, layer="OUTLINE", color=None, lineweight=None,
                  linetype=None, linetype_scale=None, bulges=()):
    if len(points) >= 2:
        attrs = {"layer": layer}
        if color is not None:
            attrs["color"] = int(color)
        if lineweight is not None:
            attrs["lineweight"] = int(lineweight)
        resolved_linetype = _resolve_linetype(msp.doc, linetype)
        if resolved_linetype:
            attrs["linetype"] = resolved_linetype
            if linetype_scale is not None:
                attrs["ltscale"] = float(linetype_scale)
        if any(bulges):
            msp.add_lwpolyline(
                [(x, y, bulge) for (x, y), bulge in zip(points, bulges)],
                format="xyb", close=closed, dxfattribs=attrs,
            )
        else:
            msp.add_lwpolyline(points, close=closed, dxfattribs=attrs)


def _ensure_anchor_linetypes(doc) -> None:
    patterns = {
        "CENTER2": [28.575, 19.05, -3.175, 3.175, -3.175],
        "CENTER": [50.8, 31.75, -6.35, 6.35, -6.35],
        "DASHED": [6.35, 3.175, -3.175],
        "HIDDEN": [18.0, 12.0, -6.0],
    }
    for name, pattern in patterns.items():
        if name not in doc.linetypes:
            doc.linetypes.add(name, pattern=pattern, description="RefracDraft reference center line")


def _add_dimension(msp, x1, y1, x2, y2, label, horizontal=True, offset=6.0,
                   denominator=10, short_witness_mm=None):
    # The endpoint direction determines which side ezdxf places the text on.
    if (x1 > x2 if horizontal else y1 > y2):
        x1, y1, x2, y2 = x2, y2, x1, y1
    if horizontal:
        base = ((x1 + x2) / 2.0, max(y1, y2) + offset)
        angle = 0
    else:
        base = (min(x1, x2) - offset, (y1 + y2) / 2.0)
        angle = 90
    style_name = f"_{denominator}"
    override = DIMENSION_OVERRIDE
    if short_witness_mm is not None:
        dimscale = msp.doc.dimstyles.get(style_name).dxf.dimscale or 1.0
        override = {**override, "dimfxlon": 1, "dimfxl": short_witness_mm * denominator / dimscale}
    dimension = msp.add_linear_dim(
        base=base,
        p1=(x1, y1),
        p2=(x2, y2),
        text=label,
        angle=angle,
        dimstyle=style_name,
        override=override,
    )
    dimension.dimension.dxf.layer = "DIMENSIONS"
    dimension.render()


def _add_view(msp, view: ViewDrawing, origin: tuple[float, float], module_id: str, denominator: int):
    ox, oy = origin
    points = [(ox + x, oy + y) for x, y in view.outline.points]
    _add_polyline(msp, points, view.outline.closed, "OUTLINE")
    for dim in view.dimensions:
        _add_dimension(
            msp,
            ox + dim.start[0], oy + dim.start[1],
            ox + dim.end[0], oy + dim.end[1],
            dim.label, dim.orientation == "horizontal", dim.offset, denominator, dim.short_witness_mm,
        )
    for leader in view.leaders:
        x, y = leader.tip
        for path in leader.paths_mm:
            vertices = [(ox + x + u * denominator, oy + y + v * denominator) for u, v in path]
            msp.add_leader(vertices, dimstyle=f"_{denominator}", override={"dimclrd": 7},
                           dxfattribs={"layer": "TEXT", "has_arrowhead": 0})
        end = (ox + x + leader.offset_mm[0] * denominator, oy + y + leader.offset_mm[1] * denominator)
        text_entity = msp.add_text(leader.text, dxfattribs={
            "height": leader_text_height(denominator) * denominator,
            "style": TEXT_STYLE,
            "layer": "TEXT",
            "insert": end,
        })
        if leader.align_right:
            text_entity.set_placement(end, align=TextEntityAlignment.RIGHT)
    for cutout in view.cutouts:
        pts = [(ox + x, oy + y) for x, y in cutout.points]
        _add_polyline(msp, pts, cutout.closed, "OUTLINE")
    for line in view.internal_lines:
        pts = [(ox + x, oy + y) for x, y in line.points]
        _add_polyline(msp, pts, line.closed, "OUTLINE")
    for line in view.hidden_lines:
        pts = [(ox + x, oy + y) for x, y in line.points]
        _add_polyline(msp, pts, line.closed, "HIDDEN", lineweight=13, linetype="HIDDEN")
    for symbol_index, symbol in enumerate(view.anchor_symbols):
        pts = [(ox + x, oy + y) for x, y in symbol.points]
        aci = view.anchor_symbol_colors[symbol_index] if symbol_index < len(view.anchor_symbol_colors) else None
        lineweight = view.anchor_symbol_lineweights[symbol_index] if symbol_index < len(view.anchor_symbol_lineweights) else 22
        linetype = view.anchor_symbol_linetypes[symbol_index] if symbol_index < len(view.anchor_symbol_linetypes) else None
        _add_polyline(msp, pts, symbol.closed, "ANCHORS", color=aci, lineweight=lineweight,
                      linetype=linetype, linetype_scale=1.0, bulges=symbol.bulges)
    for x, y in view.anchor_points:
        cx, cy = ox + x, oy + y
        if view.anchor_marker_style == "target":
            msp.add_circle((cx, cy), 0.75 * denominator, dxfattribs={"layer": "CENTER", "color": 1})
            msp.add_line((cx - 1.5 * denominator, cy), (cx + 1.5 * denominator, cy),
                         dxfattribs={"layer": "CENTER", "color": 1})
        else:
            msp.add_line((cx - 1.5 * denominator, cy), (cx + 1.5 * denominator, cy),
                         dxfattribs={"layer": "CENTER", "color": 1})
            msp.add_line((cx, cy - 1.5 * denominator), (cx, cy + 1.5 * denominator),
                         dxfattribs={"layer": "CENTER", "color": 1})
    label = view.note or module_id
    board_face = view.view_type == "board-face"
    label_x, label_y = view_label_position(view, module_id, denominator)
    label_point = (ox + label_x * denominator, oy + label_y * denominator)
    alignment = TextEntityAlignment.MIDDLE_CENTER if board_face else TextEntityAlignment.CENTER
    msp.add_text(
        label, dxfattribs={"height": VALUE_TEXT_HEIGHT * denominator / MODEL_SCALE * annotation_factor(denominator), "style": TEXT_STYLE, "layer": "TEXT"}
    ).set_placement(label_point, align=alignment)


def export_dxf(document: DrawingDocument, output_path: str | Path, reference_dxf: str | Path | None = None) -> Path:
    output_path = Path(output_path)
    doc = ezdxf.new("R2018")
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4
    for name, color in LAYER_COLORS.items():
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": color})
    _ensure_anchor_linetypes(doc)
    _ensure_text_styles(doc)

    # Import the original A4 frame and title block definitions without modifying the source.
    source = None
    if reference_dxf and Path(reference_dxf).exists():
        source = ezdxf.readfile(reference_dxf)
        importer = Importer(source, doc)
        for block_name in ("图框-A4", "标题栏"):
            if block_name in source.blocks:
                importer.import_block(block_name, rename=False)
        importer.finalize()
    for denominator in {page.scale_denominator for page in document.pages} or {MODEL_SCALE}:
        _ensure_dimension_style(doc, source, int(denominator))

    msp = doc.modelspace()
    for page, page_y in zip(document.pages, page_model_origins(document)):
        denominator = page.scale_denominator
        if "图框-A4" in doc.blocks:
            msp.add_blockref(
                "图框-A4",
                (0, page_y),
                dxfattribs={"layer": "FRAME", "xscale": denominator, "yscale": denominator, "zscale": denominator},
            )
        else:
            _add_polyline(
                msp,
                [(0, page_y), (PAGE_WIDTH_MM * denominator, page_y),
                 (PAGE_WIDTH_MM * denominator, page_y + PAGE_HEIGHT_MM * denominator), (0, page_y + PAGE_HEIGHT_MM * denominator)],
                True,
                "FRAME",
            )
        if "标题栏" in doc.blocks:
            title = msp.add_blockref(
                "标题栏",
                (TITLE_BLOCK_LEFT_MM * denominator, page_y + 6.0 * denominator),
                dxfattribs={"xscale": 0.102 * denominator, "yscale": 0.102 * denominator, "zscale": 0.102 * denominator},
            )
            title.add_auto_attribs({"图名": document.project_name, "图号": "", "批准": "", "审定": "",
                                    "项目经理": "", "校核": "", "设计": "", "制图": "",
                                    "订单编号": "", "项目单位": "", "图纸": "A4"})
        x, y = FILENAME_LABEL_POSITION
        page_label = f"第{page.page_number}页 共{len(document.pages)}页"
        # A single TEXT entity keeps the page counter immediately beside the filename
        # in SHX and fallback PDF renderers; estimated glyph widths cannot do that reliably.
        footer_label = (
            f"{document.filename_label}  {page_label}" if document.filename_label else page_label
        )
        reserved_width = len(footer_label) * FILENAME_LABEL_HEIGHT_MM * 1.39
        msp.add_text(footer_label, dxfattribs={
            "layer": "TEXT", "style": TEXT_STYLE, "height": FILENAME_LABEL_HEIGHT_MM * denominator,
            "width": min(1.0, FILENAME_LABEL_WIDTH_MM / reserved_width),
            "insert": (x * denominator, page_y + y * denominator),
        })
        for placed in page.modules[1:]:
            msp.add_line(
                (placed.x_mm * denominator, page_y + SEPARATOR_BOTTOM_MM * denominator),
                (placed.x_mm * denominator, page_y + SEPARATOR_TOP_MM * denominator),
                dxfattribs={"layer": "FRAME"},
            )

        for placed in page.modules:
            drawing = placed.drawing
            px = placed.content_x_mm * denominator
            placement = view_placement(drawing)
            front_y = page_y + placement.top_y * denominator
            _add_view(msp, drawing.front_view, (px, front_y), drawing.module_id, denominator)
            if drawing.side_view:
                _add_view(
                    msp,
                    drawing.side_view,
                    (px + placement.side_x * denominator, front_y),
                    drawing.module_id,
                    denominator,
                )
            _add_view(
                msp,
                drawing.board_view,
                (px, page_y + placement.board_y * denominator),
                drawing.module_id,
                denominator,
            )
            if drawing.details:
                left, available_width = detail_box(placed)
                anchor_y, align_bottom = detail_vertical_anchor(placed)
                msp.add_mtext(
                    _detail_mtext(detail_lines(placed), available_width, placed.measure_detail,
                                  annotation_factor(denominator)),
                    dxfattribs={
                        "insert": (left * denominator, page_y + anchor_y * denominator),
                        "char_height": DETAIL_TEXT_HEIGHT * denominator / MODEL_SCALE * annotation_factor(denominator),
                        "width": 0.0,
                        "style": TEXT_STYLE,
                        "layer": "TEXT",
                        "attachment_point": 7 if align_bottom else 1,
                        "line_spacing_style": 2,
                        "line_spacing_factor": DETAIL_LINE_SPACING,
                    },
                )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output_path)
    return output_path
