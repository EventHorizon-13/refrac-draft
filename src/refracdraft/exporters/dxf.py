from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.addons.importer import Importer

from refracdraft.drawing.model import DrawingDocument, ViewDrawing


LAYER_COLORS = {
    "OUTLINE": 7,
    "DIMENSIONS": 3,
    "ANCHORS": 5,
    "CENTER": 1,
    "TEXT": 7,
    "FRAME": 7,
}


def _add_polyline(msp, points, closed=True, layer="OUTLINE"):
    if len(points) >= 2:
        msp.add_lwpolyline(points, close=closed, dxfattribs={"layer": layer})


def _add_dimension(msp, x1, y1, x2, y2, label, horizontal=True, offset=6.0):
    color_layer = "DIMENSIONS"
    tick = 1.2
    if horizontal:
        dim_y = y1 + offset
        msp.add_line((x1, y1), (x1, dim_y - 1.0), dxfattribs={"layer": color_layer})
        msp.add_line((x2, y2), (x2, dim_y - 1.0), dxfattribs={"layer": color_layer})
        msp.add_line((x1, dim_y), (x2, dim_y), dxfattribs={"layer": color_layer})
        for x in (x1, x2):
            msp.add_line((x - tick, dim_y - tick), (x + tick, dim_y + tick), dxfattribs={"layer": color_layer})
        msp.add_text(label, dxfattribs={"insert": ((x1 + x2) / 2.0, dim_y + 1.6), "height": 2.5,
                                        "style": "工程字", "layer": color_layer, "halign": 1,
                                        "align_point": ((x1 + x2) / 2.0, dim_y + 1.6)})
    else:
        dim_x = x1 - offset
        msp.add_line((x1, y1), (dim_x - 1.0, y1), dxfattribs={"layer": color_layer})
        msp.add_line((x2, y2), (dim_x - 1.0, y2), dxfattribs={"layer": color_layer})
        msp.add_line((dim_x, y1), (dim_x, y2), dxfattribs={"layer": color_layer})
        for y in (y1, y2):
            msp.add_line((dim_x - tick, y - tick), (dim_x + tick, y + tick), dxfattribs={"layer": color_layer})
        msp.add_text(label, dxfattribs={"insert": (dim_x - 2.0, (y1 + y2) / 2.0), "height": 2.5,
                                        "rotation": 90, "style": "工程字", "layer": color_layer})


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
    for symbol in view.anchor_symbols:
        pts = [(ox + x * scale, oy + y * scale) for x, y in symbol.points]
        _add_polyline(msp, pts, symbol.closed, "ANCHORS")
    for x, y in view.anchor_points:
        cx, cy = ox + x * scale, oy + y * scale
        msp.add_circle((cx, cy), 0.6, dxfattribs={"layer": "CENTER"})
        msp.add_line((cx - 1.5, cy), (cx + 1.5, cy), dxfattribs={"layer": "CENTER"})
    msp.add_text(module_id, dxfattribs={"insert": (ox + width * scale / 2.0, oy + height * scale / 2.0),
                                        "height": 4.0, "style": "工程字", "layer": "TEXT", "halign": 1,
                                        "align_point": (ox + width * scale / 2.0, oy + height * scale / 2.0)})
    if view.note:
        msp.add_text(view.note, dxfattribs={"insert": (ox + width * scale / 2.0, oy + height * scale / 2.0),
                                            "height": 3.5, "style": "工程字", "layer": "TEXT", "halign": 1,
                                            "align_point": (ox + width * scale / 2.0, oy + height * scale / 2.0)})


def export_dxf(document: DrawingDocument, output_path: str | Path, reference_dxf: str | Path | None = None) -> Path:
    output_path = Path(output_path)
    doc = ezdxf.new("R2018")
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4
    doc.styles.new("工程字", dxfattribs={"font": "gbenor.shx", "bigfont": "gbcbig.shx"})
    for name, color in LAYER_COLORS.items():
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": color})

    # Import the original A4 frame and title block definitions without modifying the source.
    if reference_dxf and Path(reference_dxf).exists():
        source = ezdxf.readfile(reference_dxf)
        importer = Importer(source, doc)
        for block_name in ("图框-A4", "标题栏"):
            if block_name in source.blocks:
                importer.import_block(block_name, rename=False)
        importer.finalize()

    msp = doc.modelspace()
    for page in document.pages:
        page_y = -(page.page_number - 1) * 230.0
        if "图框-A4" in doc.blocks:
            msp.add_blockref("图框-A4", (0, page_y), dxfattribs={"layer": "FRAME"})
        else:
            _add_polyline(msp, [(0, page_y), (297, page_y), (297, page_y + 210), (0, page_y + 210)], True, "FRAME")
        if "标题栏" in doc.blocks:
            title = msp.add_blockref("标题栏", (168.7, page_y + 6.0), dxfattribs={"xscale": 0.102, "yscale": 0.102, "zscale": 0.102})
            title.add_auto_attribs({"图名": document.project_name, "图号": "", "批准": "", "审定": "",
                                    "项目经理": "", "校核": "", "设计": "", "制图": "",
                                    "订单编号": "", "项目单位": "", "图纸": "A4"})
        for col in range(1, page.column_count):
            x = 7.0 + col * (283.0 / page.column_count)
            msp.add_line((x, page_y + 7), (x, page_y + 203), dxfattribs={"layer": "FRAME"})

        for placed in page.modules:
            drawing = placed.drawing
            px = placed.x_mm
            panel_w = placed.panel_width_mm
            scale = 0.1
            if drawing.side_view:
                front_w = (drawing.front_view.outline.bounds[2] - drawing.front_view.outline.bounds[0]) * scale
                side_w = (drawing.side_view.outline.bounds[2] - drawing.side_view.outline.bounds[0]) * scale
                total = front_w + side_w + 18.0
                x0 = px + max(4.0, (panel_w - total) / 2.0)
                _add_view(msp, drawing.front_view, (x0, page_y + 146), drawing.module_id, scale)
                _add_view(msp, drawing.side_view, (x0 + front_w + 18.0, page_y + 146), drawing.module_id, scale)
            else:
                fw = (drawing.front_view.outline.bounds[2] - drawing.front_view.outline.bounds[0]) * scale
                x0 = px + (panel_w - fw) / 2.0
                _add_view(msp, drawing.front_view, (x0, page_y + 146), drawing.module_id, scale)
            bw = (drawing.board_view.outline.bounds[2] - drawing.board_view.outline.bounds[0]) * scale
            bx = px + (panel_w - bw) / 2.0
            _add_view(msp, drawing.board_view, (bx, page_y + 105), drawing.module_id, scale)
            for line_no, text in enumerate(drawing.details):
                msp.add_text(text, dxfattribs={"insert": (px + 7.0, page_y + 83 - line_no * 5.2),
                                              "height": 3.2, "style": "工程字", "layer": "TEXT"})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output_path)
    return output_path
