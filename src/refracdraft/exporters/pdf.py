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

from refracdraft.drawing.layout import (
    BOARD_VIEW_BOTTOM_MM,
    SIDE_VIEW_GAP_MM,
    TOP_VIEW_BOTTOM_MM,
    VIEW_SCALE,
    detail_baseline,
    outline_width,
)
from refracdraft.drawing.model import DrawingDocument, ModuleDrawing, ViewDrawing

PAGE_W, PAGE_H = landscape(A4)
MM = 72.0 / 25.4
PDF_FONT_NAME: str | None = None
SYMBOL_FONT_NAME: str | None = None


def _xy(x_mm: float, y_mm: float) -> tuple[float, float]:
    return x_mm * MM, y_mm * MM


def _line(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float,
          color=black, width: float = 0.18) -> None:
    c.setStrokeColor(color)
    c.setLineWidth(width * MM)
    c.line(*_xy(x1, y1), *_xy(x2, y2))


def _ensure_symbol_font() -> None:
    global SYMBOL_FONT_NAME
    if SYMBOL_FONT_NAME:
        return
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path(r"C:\\Windows\\Fonts\\arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for font_path in candidates:
        if not font_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("RefracSymbols", str(font_path)))
            SYMBOL_FONT_NAME = "RefracSymbols"
            return
        except Exception:
            continue


def _text(c: canvas.Canvas, text: str, x: float, y: float, size: float = 2.5,
          color=black, align: str = "left", horizontal_scale: float = 1.0) -> None:
    c.setFillColor(color)
    base_font = PDF_FONT_NAME or "STSong-Light"
    font_size = size * MM
    px, py = _xy(x, y)
    if any(char in text for char in ("Ø", "³")):
        _ensure_symbol_font()
    if SYMBOL_FONT_NAME and any(char in text for char in ("Ø", "³")):
        runs: list[tuple[str, str]] = []
        for char in text:
            font = SYMBOL_FONT_NAME if char in ("Ø", "³") else base_font
            if runs and runs[-1][0] == font:
                runs[-1] = (font, runs[-1][1] + char)
            else:
                runs.append((font, char))
        total_width = sum(pdfmetrics.stringWidth(run, font, font_size) for font, run in runs)
        if align == "center":
            px -= total_width * horizontal_scale / 2.0
        elif align == "right":
            px -= total_width * horizontal_scale
        c.saveState()
        c.translate(px, py)
        c.scale(horizontal_scale, 1.0)
        run_x = 0.0
        for font, run in runs:
            c.setFont(font, font_size)
            c.drawString(run_x, 0, run)
            run_x += pdfmetrics.stringWidth(run, font, font_size)
        c.restoreState()
        return
    if horizontal_scale != 1.0:
        width = pdfmetrics.stringWidth(text, base_font, font_size)
        if align == "center":
            px -= width * horizontal_scale / 2.0
        elif align == "right":
            px -= width * horizontal_scale
        c.saveState()
        c.translate(px, py)
        c.scale(horizontal_scale, 1.0)
        c.setFont(base_font, font_size)
        c.drawString(0, 0, text)
        c.restoreState()
        return
    c.setFont(base_font, font_size)
    if align == "center":
        c.drawCentredString(px, py, text)
    elif align == "right":
        c.drawRightString(px, py, text)
    else:
        c.drawString(px, py, text)


def _arrowhead(c: canvas.Canvas, x: float, y: float, ux: float, uy: float, color=cyan) -> None:
    length, half_width = 0.8, 0.12
    base_x, base_y = x - ux * length, y - uy * length
    px, py = -uy * half_width, ux * half_width
    path = c.beginPath()
    path.moveTo(*_xy(x, y))
    path.lineTo(*_xy(base_x + px, base_y + py))
    path.lineTo(*_xy(base_x - px, base_y - py))
    path.close()
    c.setFillColor(color)
    c.setStrokeColor(color)
    c.drawPath(path, stroke=0, fill=1)


def _dimension(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float,
               label: str, horizontal: bool, offset: float) -> None:
    col = cyan
    if horizontal:
        dy = max(y1, y2) + offset
        _line(c, x1, y1, x1, dy - 1.0, col, 0.18)
        _line(c, x2, y2, x2, dy - 1.0, col, 0.18)
        _line(c, x1, dy, x2, dy, col, 0.18)
        direction = 1.0 if x2 >= x1 else -1.0
        _arrowhead(c, x1, dy, -direction, 0, col)
        _arrowhead(c, x2, dy, direction, 0, col)
        _text(c, label, (x1 + x2) / 2.0, dy + 2.0, 4.2, green, "center", horizontal_scale=0.93)
    else:
        dx = x1 - offset
        _line(c, x1, y1, dx - 1.0, y1, col, 0.18)
        _line(c, x2, y2, dx - 1.0, y2, col, 0.18)
        _line(c, dx, y1, dx, y2, col, 0.18)
        direction = 1.0 if y2 >= y1 else -1.0
        _arrowhead(c, dx, y1, 0, -direction, col)
        _arrowhead(c, dx, y2, 0, direction, col)
        c.saveState()
        c.translate(*_xy(dx - 2.0, (y1 + y2) / 2.0))
        c.rotate(90)
        _text(c, label, 0, 0, 4.2, green, "center", horizontal_scale=0.93)
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
    aci_colors = {1: red, 2: yellow, 3: green, 4: cyan, 5: blue, 6: Color(1, 0, 1), 7: black,
                  8: Color(0.5, 0.5, 0.5), 9: Color(0.75, 0.75, 0.75)}
    for symbol_index, symbol in enumerate(view.anchor_symbols):
        aci = view.anchor_symbol_colors[symbol_index] if symbol_index < len(view.anchor_symbol_colors) else 5
        lineweight = view.anchor_symbol_lineweights[symbol_index] if symbol_index < len(view.anchor_symbol_lineweights) else 22
        linetype = view.anchor_symbol_linetypes[symbol_index] if symbol_index < len(view.anchor_symbol_linetypes) else "CONTINUOUS"
        c.setStrokeColor(aci_colors.get(aci, black))
        c.setLineWidth((lineweight / 100.0) * MM)
        if any(token in linetype.upper() for token in ("CENTER", "DASH", "HIDDEN")):
            # Scale the source CENTER2 pattern (19.05 + 3.175 + 3.175 + 3.175)
            # from drawing millimetres to the 1:10 paper view.
            c.setDash([5.36, 0.89, 0.89, 0.89])
        else:
            c.setDash()
        if len(symbol.points) < 2:
            continue
        path = c.beginPath()
        path.moveTo(*_xy(ox + symbol.points[0][0] * scale, oy + symbol.points[0][1] * scale))
        for x, y in symbol.points[1:]:
            path.lineTo(*_xy(ox + x * scale, oy + y * scale))
        if symbol.closed:
            path.close()
        c.drawPath(path, stroke=1, fill=0)
    c.setDash()
    for x, y in view.anchor_points:
        cx, cy = ox + x * scale, oy + y * scale
        c.setStrokeColor(red)
        if view.anchor_marker_style == "target":
            c.setFillColor(yellow)
            c.circle(*_xy(cx, cy), 0.75 * MM, stroke=1, fill=1)
            _line(c, cx - 1.5, cy, cx + 1.5, cy, red, 0.25)
        else:
            _line(c, cx - 1.5, cy, cx + 1.5, cy, red, 0.25)
            _line(c, cx, cy - 1.5, cx, cy + 1.5, red, 0.25)

    label = view.note or module_id
    label_y = height * 0.5
    if view.view_type != "board-face" and (view.anchor_symbols or view.anchor_points):
        bottom_mid = (view.outline.points[0][1] + view.outline.points[1][1]) / 2.0
        label_y = bottom_mid + 5.0
    _text(c, label, ox + width * scale / 2.0, oy + label_y * scale - 1.0, 4.0, black, "center")


def _draw_page_frame(c: canvas.Canvas, page) -> None:
    c.setStrokeColor(black)
    c.setLineWidth(0.24 * MM)
    c.rect(*_xy(7, 7), 283 * MM, 196 * MM, stroke=1, fill=0)
    # In the source PDFs, panel dividers stop at the top of the title block/footer band.
    for placed in page.modules[1:]:
        _line(c, placed.x_mm, 37, placed.x_mm, 203, black, 0.24)


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
        _draw_page_frame(c, page)
        for placed in page.modules:
            drawing = placed.drawing
            px = placed.content_x_mm
            scale = VIEW_SCALE
            if drawing.side_view:
                front_w = outline_width(drawing.front_view)
                front_y = TOP_VIEW_BOTTOM_MM
                _draw_view(c, drawing.front_view, (px, front_y), drawing.module_id, scale)
                _draw_view(
                    c,
                    drawing.side_view,
                    (px + front_w + SIDE_VIEW_GAP_MM, front_y),
                    drawing.module_id,
                    scale,
                )
            else:
                _draw_view(
                    c,
                    drawing.front_view,
                    (px, TOP_VIEW_BOTTOM_MM),
                    drawing.module_id,
                    scale,
                )
            _draw_view(
                c,
                drawing.board_view,
                (px, BOARD_VIEW_BOTTOM_MM),
                drawing.module_id,
                scale,
                board_label=True,
            )
            for line_no, line in enumerate(drawing.details):
                baseline = detail_baseline(line_no)
                if line_no < 6:
                    _text(c, line, px, baseline, 5.67, black, horizontal_scale=0.67)
                else:
                    _text(c, line, px, baseline, 4.2, black, horizontal_scale=0.97)
        c.showPage()
    c.save()
    _overlay_reference_titleblock(output_path, reference_pdf)
    return output_path
