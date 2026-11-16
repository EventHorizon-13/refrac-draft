from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import Color, black, blue, cyan, green, red, yellow
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
import fitz
import os

from refracdraft.drawing.model import DrawingDocument, ModuleDrawing, ViewDrawing

PAGE_W, PAGE_H = landscape(A4)
MM = 72.0 / 25.4
PDF_FONT_NAME: str | None = None


def _xy(x_mm: float, y_mm: float) -> tuple[float, float]:
    return x_mm * MM, y_mm * MM


def _line(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float,
          color=black, width: float = 0.18) -> None:
    c.setStrokeColor(color)
    c.setLineWidth(width * MM)
    c.line(*_xy(x1, y1), *_xy(x2, y2))


def _text(c: canvas.Canvas, text: str, x: float, y: float, size: float = 2.5,
          color=black, align: str = "left") -> None:
    c.setFillColor(color)
    c.setFont(PDF_FONT_NAME or "STSong-Light", size * MM)
    px, py = _xy(x, y)
    if align == "center":
        c.drawCentredString(px, py, text)
    elif align == "right":
        c.drawRightString(px, py, text)
    else:
        c.drawString(px, py, text)


def _dimension(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float,
               label: str, horizontal: bool, offset: float) -> None:
    col = green
    tick = 1.15
    if horizontal:
        dy = max(y1, y2) + offset
        _line(c, x1, y1, x1, dy - 1.0, col, 0.18)
        _line(c, x2, y2, x2, dy - 1.0, col, 0.18)
        _line(c, x1, dy, x2, dy, col, 0.18)
        _line(c, x1 - tick, dy - tick, x1 + tick, dy + tick, col, 0.18)
        _line(c, x2 - tick, dy - tick, x2 + tick, dy + tick, col, 0.18)
        _text(c, label, (x1 + x2) / 2.0, dy + 1.4, 2.7, col, "center")
    else:
        dx = x1 - offset
        _line(c, x1, y1, dx - 1.0, y1, col, 0.18)
        _line(c, x2, y2, dx - 1.0, y2, col, 0.18)
        _line(c, dx, y1, dx, y2, col, 0.18)
        _line(c, dx - tick, y1 - tick, dx + tick, y1 + tick, col, 0.18)
        _line(c, dx - tick, y2 - tick, dx + tick, y2 + tick, col, 0.18)
        c.saveState()
        c.translate(*_xy(dx - 2.0, (y1 + y2) / 2.0))
        c.rotate(90)
        _text(c, label, 0, 0, 2.7, col, "center")
        c.restoreState()


def _draw_view(c: canvas.Canvas, view: ViewDrawing, origin: tuple[float, float], module_id: str,
               scale: float = 0.1, board_label: bool = False) -> None:
    ox, oy = origin
    pts = [(ox + x * scale, oy + y * scale) for x, y in view.outline.points]
    c.setStrokeColor(black)
    c.setLineWidth(0.24 * MM)
    p = c.beginPath()
    p.moveTo(*_xy(*pts[0]))
    for point in pts[1:]:
        p.lineTo(*_xy(*point))
    if view.outline.closed:
        p.close()
    c.drawPath(p, stroke=1, fill=0)

    for dim in view.dimensions:
        _dimension(
            c,
            ox + dim.start[0] * scale, oy + dim.start[1] * scale,
            ox + dim.end[0] * scale, oy + dim.end[1] * scale,
            dim.label, dim.orientation == "horizontal", dim.offset * scale,
        )
    min_x, min_y, max_x, max_y = view.outline.bounds
    width, height = max_x - min_x, max_y - min_y

    c.setStrokeColor(black)
    c.setLineWidth(0.24 * MM)
    for cutout in view.cutouts:
        if len(cutout.points) < 2:
            continue
        path = c.beginPath()
        path.moveTo(*_xy(ox + cutout.points[0][0] * scale, oy + cutout.points[0][1] * scale))
        for x, y in cutout.points[1:]:
            path.lineTo(*_xy(ox + x * scale, oy + y * scale))
        if cutout.closed:
            path.close()
        c.drawPath(path, stroke=1, fill=0)

    c.setStrokeColor(black)
    c.setLineWidth(0.24 * MM)
    for line in view.internal_lines:
        if len(line.points) < 2:
            continue
        a, b = line.points[0], line.points[-1]
        _line(c, ox + a[0] * scale, oy + a[1] * scale,
              ox + b[0] * scale, oy + b[1] * scale, black, 0.24)

    # Anchor linework is taken from the supplied reference DXF block geometry.
    c.setStrokeColor(blue)
    c.setLineWidth(0.22 * MM)
    for symbol in view.anchor_symbols:
        if len(symbol.points) < 2:
            continue
        path = c.beginPath()
        path.moveTo(*_xy(ox + symbol.points[0][0] * scale, oy + symbol.points[0][1] * scale))
        for x, y in symbol.points[1:]:
            path.lineTo(*_xy(ox + x * scale, oy + y * scale))
        if symbol.closed:
            path.close()
        c.drawPath(path, stroke=1, fill=0)
    for x, y in view.anchor_points:
        cx, cy = ox + x * scale, oy + y * scale
        c.setStrokeColor(red)
        c.setFillColor(yellow)
        c.circle(*_xy(cx, cy), 0.75 * MM, stroke=1, fill=1)
        _line(c, cx - 1.5, cy, cx + 1.5, cy, red, 0.16)

    label = view.note or module_id
    label_y = height * 0.5
    if view.view_type != "board-face" and (view.anchor_symbols or view.anchor_points):
        label_y = height * 0.05
    _text(c, label, ox + width * scale / 2.0, oy + label_y * scale - 1.0, 4.0, black, "center")


def _draw_page_frame(c: canvas.Canvas, column_count: int) -> None:
    c.setStrokeColor(black)
    c.setLineWidth(0.24 * MM)
    c.rect(*_xy(7, 7), 283 * MM, 196 * MM, stroke=1, fill=0)
    # In the source PDFs, panel dividers stop at the top of the title block/footer band.
    for i in range(1, column_count):
        x = 7 + i * (283.0 / column_count)
        _line(c, x, 37, x, 203, black, 0.24)


def _overlay_reference_titleblock(output_path: Path, reference_pdf: str | Path | None) -> None:
    """Copy the title-block/footer strip as vector PDF content from the accepted sample."""
    if not reference_pdf or not Path(reference_pdf).exists():
        return
    source = fitz.open(str(reference_pdf))
    generated = fitz.open(str(output_path))
    merged = fitz.open()
    title_clip = fitz.Rect(470, 490, 842, 595)
    footer_clip = fitz.Rect(0, 575, 470, 595)
    for page_index in range(len(generated)):
        page = merged.new_page(width=842, height=595)
        page.show_pdf_page(page.rect, generated, page_index)
        # Preserve the source title block, company mark, footer, and plotted linework as vectors.
        page.show_pdf_page(title_clip, source, 0, clip=title_clip, overlay=True)
        page.show_pdf_page(footer_clip, source, 0, clip=footer_clip, overlay=True)
    temp_path = output_path.with_suffix(".merged.pdf")
    merged.save(str(temp_path), garbage=4, deflate=True)
    merged.close()
    generated.close()
    source.close()
    temp_path.replace(output_path)


def _ensure_cjk_font() -> None:
    global PDF_FONT_NAME
    if PDF_FONT_NAME:
        return
    try:
        pdfmetrics.getFont("RefracCJK")
        PDF_FONT_NAME = "RefracCJK"
        return
    except KeyError:
        pass
    configured = os.environ.get("REFRACDRAFT_CJK_FONT")
    candidates = [
        Path(configured) if configured else None,
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for font_path in candidates:
        if not font_path or not font_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("RefracCJK", str(font_path), subfontIndex=0))
            PDF_FONT_NAME = "RefracCJK"
            return
        except Exception:
            continue
    # Last-resort built-in CID font; some uncommon glyphs may be substituted.
    try:
        pdfmetrics.getFont("STSong-Light")
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    PDF_FONT_NAME = "STSong-Light"


def export_pdf(document: DrawingDocument, output_path: str | Path,
               reference_pdf: str | Path | None = None) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_cjk_font()
    c = canvas.Canvas(str(output_path), pagesize=landscape(A4), pageCompression=1)
    c.setTitle(document.project_name)

    for page in document.pages:
        _draw_page_frame(c, page.column_count)
        for placed in page.modules:
            drawing = placed.drawing
            px, panel_w = placed.x_mm, placed.panel_width_mm
            scale = 0.1
            if drawing.side_view:
                front_w = (drawing.front_view.outline.bounds[2] - drawing.front_view.outline.bounds[0]) * scale
                side_w = (drawing.side_view.outline.bounds[2] - drawing.side_view.outline.bounds[0]) * scale
                gap = 18.0
                total = front_w + side_w + gap
                x0 = px + max(3.0, (panel_w - total) / 2.0)
                _draw_view(c, drawing.front_view, (x0, 150), drawing.module_id, scale)
                _draw_view(c, drawing.side_view, (x0 + front_w + gap, 150), drawing.module_id, scale)
            else:
                front_w = (drawing.front_view.outline.bounds[2] - drawing.front_view.outline.bounds[0]) * scale
                x0 = px + (panel_w - front_w) / 2.0
                _draw_view(c, drawing.front_view, (x0, 148), drawing.module_id, scale)
            board_w = (drawing.board_view.outline.bounds[2] - drawing.board_view.outline.bounds[0]) * scale
            board_x = px + (panel_w - board_w) / 2.0
            _draw_view(c, drawing.board_view, (board_x, 105), drawing.module_id, scale, board_label=True)
            for line_no, line in enumerate(drawing.details):
                _text(c, line, px + 5.0, 88 - line_no * 6.1, 3.4, black)
        c.showPage()
    c.save()
    _overlay_reference_titleblock(output_path, reference_pdf)
    return output_path
