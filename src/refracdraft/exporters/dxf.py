from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.addons.importer import Importer

from refracdraft.drawing.layout import (
    BOARD_VIEW_BOTTOM_MM,
    DETAIL_TEXT_SIZE_MM,
    SIDE_VIEW_GAP_MM,
    TOP_VIEW_BOTTOM_MM,
    detail_baseline,
)
from refracdraft.drawing.model import DrawingDocument, ViewDrawing


LAYER_COLORS = {
    "OUTLINE": 7,
    "DIMENSIONS": 4,
    "ANCHORS": 5,
    "CENTER": 1,
    "TEXT": 7,
    "FRAME": 7,
}

TEXT_STYLE = "大字体"
DIMENSION_STYLE = "_10"
MODEL_SCALE = 10.0
DETAIL_TEXT_HEIGHT = DETAIL_TEXT_SIZE_MM * MODEL_SCALE
VALUE_TEXT_HEIGHT = 40.0
DIMENSION_OVERRIDE = {
    "dimtxsty": TEXT_STYLE,
    "dimclrd": 4,
    "dimclre": 4,
    "dimclrt": 3,
}
DIMENSION_FALLBACK = {
    "dimscale": 20.0,
    "dimtxt": 1.5,
    "dimasz": 0.8,
    "dimexo": 1.0,
    "dimexe": 1.0,
    "dimgap": 1.0,
    "dimtad": 1,
}


def _ensure_text_styles(doc) -> None:
    for name in ("工程字", TEXT_STYLE):
        if name in doc.styles:
            style = doc.styles.get(name)
        else:
            style = doc.styles.new(name)
        style.dxf.font = "gbenor.shx"
        style.dxf.bigfont = "gbcbig.shx"


def _ensure_dimension_style(doc, source=None) -> None:
    attributes = {**DIMENSION_FALLBACK, **DIMENSION_OVERRIDE}
    if source is not None:
        try:
            source_style = source.dimstyles.get(DIMENSION_STYLE)
            attributes.update({
                key: value
                for key, value in source_style.dxf.all_existing_dxf_attribs().items()
                if key not in {"handle", "owner"}
            })
            attributes.update(DIMENSION_OVERRIDE)
        except (KeyError, ValueError):
            pass
    if DIMENSION_STYLE in doc.dimstyles:
        style = doc.dimstyles.get(DIMENSION_STYLE)
        for key, value in attributes.items():
            style.dxf.set(key, value)
    else:
        doc.dimstyles.new(DIMENSION_STYLE, dxfattribs=attributes)


def _resolve_linetype(doc, linetype: str | None) -> str | None:
    if not linetype:
        return None
    name = linetype.upper()
    if name in {"BYLAYER", "BYBLOCK", "CONTINUOUS"}:
        return None
    if name in doc.linetypes:
        return name
    if "CENTER" in name or "中心" in name:
        return "CENTER2"
    if "DASH" in name or "虚线" in name:
        return "DASHED"
    return None


def _add_polyline(msp, points, closed=True, layer="OUTLINE", color=None, lineweight=None,
                  linetype=None, linetype_scale=None):
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
        msp.add_lwpolyline(points, close=closed, dxfattribs=attrs)


def _ensure_anchor_linetypes(doc) -> None:
    patterns = {
        "CENTER2": [28.575, 19.05, -3.175, 3.175, -3.175],
        "CENTER": [50.8, 31.75, -6.35, 6.35, -6.35],
        "DASHED": [6.35, 3.175, -3.175],
    }
    for name, pattern in patterns.items():
        if name not in doc.linetypes:
            doc.linetypes.add(name, pattern=pattern, description="RefracDraft reference center line")


def _add_dimension(msp, x1, y1, x2, y2, label, horizontal=True, offset=6.0):
    if horizontal:
        base = ((x1 + x2) / 2.0, max(y1, y2) + offset)
        angle = 0
    else:
        base = (min(x1, x2) - offset, (y1 + y2) / 2.0)
        angle = 90
    dimension = msp.add_linear_dim(
        base=base,
        p1=(x1, y1),
        p2=(x2, y2),
        text=label,
        angle=angle,
        dimstyle=DIMENSION_STYLE,
        override=DIMENSION_OVERRIDE,
    )
    dimension.render()


def _add_view(msp, view: ViewDrawing, origin: tuple[float, float], module_id: str, scale: float = 0.1):
    ox, oy = origin
    points = [(ox + x * scale, oy + y * scale) for x, y in view.outline.points]
    _add_polyline(msp, points, view.outline.closed, "OUTLINE")
    for dim in view.dimensions:
        _add_dimension(
            msp,
            ox + dim.start[0] * scale, oy + dim.start[1] * scale,
            ox + dim.end[0] * scale, oy + dim.end[1] * scale,
            dim.label, dim.orientation == "horizontal", dim.offset * scale,
        )
    min_x, min_y, max_x, max_y = view.outline.bounds
    width, height = max_x - min_x, max_y - min_y
    for cutout in view.cutouts:
        pts = [(ox + x * scale, oy + y * scale) for x, y in cutout.points]
        _add_polyline(msp, pts, cutout.closed, "OUTLINE")
    for line in view.internal_lines:
        pts = [(ox + x * scale, oy + y * scale) for x, y in line.points]
        _add_polyline(msp, pts, line.closed, "OUTLINE")
    for symbol_index, symbol in enumerate(view.anchor_symbols):
        pts = [(ox + x * scale, oy + y * scale) for x, y in symbol.points]
        aci = view.anchor_symbol_colors[symbol_index] if symbol_index < len(view.anchor_symbol_colors) else None
        lineweight = view.anchor_symbol_lineweights[symbol_index] if symbol_index < len(view.anchor_symbol_lineweights) else 22
        linetype = view.anchor_symbol_linetypes[symbol_index] if symbol_index < len(view.anchor_symbol_linetypes) else None
        _add_polyline(msp, pts, symbol.closed, "ANCHORS", color=aci, lineweight=lineweight,
                      linetype=linetype, linetype_scale=1.0)
    for x, y in view.anchor_points:
        cx, cy = ox + x * scale, oy + y * scale
        if view.anchor_marker_style == "target":
            msp.add_circle((cx, cy), 0.75 * MODEL_SCALE, dxfattribs={"layer": "CENTER", "color": 1})
            msp.add_line((cx - 1.5 * MODEL_SCALE, cy), (cx + 1.5 * MODEL_SCALE, cy),
                         dxfattribs={"layer": "CENTER", "color": 1})
        else:
            msp.add_line((cx - 1.5 * MODEL_SCALE, cy), (cx + 1.5 * MODEL_SCALE, cy),
                         dxfattribs={"layer": "CENTER", "color": 1})
            msp.add_line((cx, cy - 1.5 * MODEL_SCALE), (cx, cy + 1.5 * MODEL_SCALE),
                         dxfattribs={"layer": "CENTER", "color": 1})
    label = view.note or module_id
    label_y = height / 2.0
    if view.view_type != "board-face" and (view.anchor_symbols or view.anchor_points):
        label_y = (view.outline.points[0][1] + view.outline.points[1][1]) / 2.0 + 5.0 * MODEL_SCALE
    label_point = (ox + width * scale / 2.0, oy + label_y * scale)
    msp.add_text(label, dxfattribs={"insert": label_point, "height": VALUE_TEXT_HEIGHT, "style": TEXT_STYLE,
                                    "layer": "TEXT", "halign": 1, "align_point": label_point})


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
    _ensure_dimension_style(doc, source)

    msp = doc.modelspace()
    for page in document.pages:
        page_y = -(page.page_number - 1) * 230.0 * MODEL_SCALE
        if "图框-A4" in doc.blocks:
            msp.add_blockref(
                "图框-A4",
                (0, page_y),
                dxfattribs={"layer": "FRAME", "xscale": MODEL_SCALE, "yscale": MODEL_SCALE, "zscale": MODEL_SCALE},
            )
        else:
            _add_polyline(
                msp,
                [(0, page_y), (297 * MODEL_SCALE, page_y),
                 (297 * MODEL_SCALE, page_y + 210 * MODEL_SCALE), (0, page_y + 210 * MODEL_SCALE)],
                True,
                "FRAME",
            )
        if "标题栏" in doc.blocks:
            title = msp.add_blockref(
                "标题栏",
                (168.7 * MODEL_SCALE, page_y + 6.0 * MODEL_SCALE),
                dxfattribs={"xscale": 1.02, "yscale": 1.02, "zscale": 1.02},
            )
            title.add_auto_attribs({"图名": document.project_name, "图号": "", "批准": "", "审定": "",
                                    "项目经理": "", "校核": "", "设计": "", "制图": "",
                                    "订单编号": "", "项目单位": "", "图纸": "A4"})
        for placed in page.modules[1:]:
            msp.add_line(
                (placed.x_mm * MODEL_SCALE, page_y + 7 * MODEL_SCALE),
                (placed.x_mm * MODEL_SCALE, page_y + 203 * MODEL_SCALE),
                dxfattribs={"layer": "FRAME"},
            )

        for placed in page.modules:
            drawing = placed.drawing
            px = placed.content_x_mm * MODEL_SCALE
            scale = 1.0
            if drawing.side_view:
                front_w = drawing.front_view.outline.bounds[2] - drawing.front_view.outline.bounds[0]
                front_y = page_y + TOP_VIEW_BOTTOM_MM * MODEL_SCALE
                _add_view(msp, drawing.front_view, (px, front_y), drawing.module_id, scale)
                _add_view(
                    msp,
                    drawing.side_view,
                    (px + front_w + SIDE_VIEW_GAP_MM * MODEL_SCALE, front_y),
                    drawing.module_id,
                    scale,
                )
            else:
                _add_view(
                    msp,
                    drawing.front_view,
                    (px, page_y + TOP_VIEW_BOTTOM_MM * MODEL_SCALE),
                    drawing.module_id,
                    scale,
                )
            _add_view(
                msp,
                drawing.board_view,
                (px, page_y + BOARD_VIEW_BOTTOM_MM * MODEL_SCALE),
                drawing.module_id,
                scale,
            )
            for line_no, text in enumerate(drawing.details):
                baseline = detail_baseline(line_no)
                msp.add_text(text, dxfattribs={"insert": (px, page_y + baseline * MODEL_SCALE),
                                              "height": DETAIL_TEXT_HEIGHT, "style": TEXT_STYLE, "layer": "TEXT"})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output_path)
    return output_path
