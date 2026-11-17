from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf
import pymupdf
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
from ezdxf.fonts import fonts
from ezdxf.math import BoundingBox2d

from refracdraft.drawing.model import DrawingDocument
from refracdraft.exporters.dxf import export_dxf
from refracdraft.resources import resource_path


PAGE_WIDTH_MM = 297.0
PAGE_HEIGHT_MM = 210.0
PAGE_STRIDE_MM = 230.0
MODEL_SCALE = 10.0
PDF_FONT_CANDIDATES = (
    Path(os.environ.get("REFRACDRAFT_CJK_FONT", "")),
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
    resource_path("assets/fonts/SourceHanSansSC-Regular.otf"),
    resource_path("assets/fonts/SourceHanSansSC-Regular.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)


def _find_pdf_font() -> Path | None:
    for path in PDF_FONT_CANDIDATES:
        if path and path.is_file():
            return path
    return None


def _reference_dxf_path(reference_dxf: str | Path | None) -> Path | None:
    if reference_dxf:
        path = Path(reference_dxf)
        if path.is_file():
            return path
    bundled = resource_path("references/示例.dxf")
    return bundled if bundled.is_file() else None


def _configure_cjk_fonts(context: RenderContext, font_path: Path | None) -> None:
    if font_path is None:
        return
    # The DXF keeps the approved gbenor/gbcbig styles. For PDF plotting only,
    # map those styles to a bundled TrueType font because AutoCAD SHX files are
    # not installed on every machine that runs the portable build.
    fonts.font_manager.scan_folder(font_path.parent)
    font_face = fonts.FontFace(filename=font_path.name)
    for style_name in tuple(context.fonts):
        context.fonts[style_name] = font_face
    context.fonts["standard"] = font_face
    context.fonts["工程字"] = font_face
    context.fonts["大字体"] = font_face


def _render_page(doc, page_index: int, font_path: Path | None) -> bytes:
    page_y = -page_index * PAGE_STRIDE_MM * MODEL_SCALE
    render_box = BoundingBox2d(
        [(0, page_y), (PAGE_WIDTH_MM * MODEL_SCALE, page_y + PAGE_HEIGHT_MM * MODEL_SCALE)]
    )
    backend = PyMuPdfBackend()
    context = RenderContext(doc)
    _configure_cjk_fonts(context, font_path)
    frontend = Frontend(
        context,
        backend,
        config=Configuration(
            background_policy=BackgroundPolicy.WHITE,
            color_policy=ColorPolicy.COLOR,
        ),
    )
    frontend.draw_layout(doc.modelspace(), finalize=True)
    return backend.get_pdf_bytes(
        layout.Page(
            PAGE_WIDTH_MM,
            PAGE_HEIGHT_MM,
            layout.Units.mm,
            margins=layout.Margins(0, 0, 0, 0),
        ),
        settings=layout.Settings(
            fit_page=True,
            scale=1.0,
            crop_at_margins=True,
            page_alignment=layout.PageAlignment.TOP_LEFT,
        ),
        render_box=render_box,
    )


def _add_searchable_text_layer(page, document: DrawingDocument, page_index: int,
                               font_path: Path | None) -> None:
    """Keep the DXF plot paths visual while exposing source text in PDF search."""
    if font_path is None or page_index >= len(document.pages):
        return
    sheet = document.pages[page_index]
    lines = [line for placed in sheet.modules for line in placed.drawing.details]
    # Text is intentionally invisible; the visible glyphs come from the DXF plot.
    y = 8.0
    for line in lines:
        if y > page.rect.height - 8.0:
            break
        try:
            page.insert_text(
                (6.0, y),
                line,
                fontsize=5.5,
                fontname="RefracDraftCJK",
                fontfile=str(font_path),
                color=None,
                render_mode=3,
            )
        except Exception:
            # A missing glyph in a user-supplied font must not break the plot.
            break
        y += 7.0


def export_pdf(
    document: DrawingDocument,
    output_path: str | Path,
    reference_pdf: str | Path | None = None,
    *,
    reference_dxf: str | Path | None = None,
    dxf_path: str | Path | None = None,
) -> Path:
    """Render a PDF from the same DXF that is exported to the customer.

    ``reference_pdf`` is retained as a compatibility argument for callers from
    earlier releases. The PDF is no longer assembled by overlaying a reference
    PDF; the frame and title block come from the generated DXF block references.
    """
    del reference_pdf
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_path = _find_pdf_font()
    source_dxf = Path(dxf_path) if dxf_path is not None else None

    with TemporaryDirectory(prefix="refracdraft-pdf-", dir=output_path.parent) as temp_dir:
        if source_dxf is None:
            source_dxf = Path(temp_dir) / "drawing.dxf"
            export_dxf(document, source_dxf, _reference_dxf_path(reference_dxf))
        elif not source_dxf.is_file():
            raise FileNotFoundError(f"DXF 文件不存在: {source_dxf}")

        dxf = ezdxf.readfile(source_dxf)
        merged = pymupdf.open()
        for page_index in range(len(document.pages)):
            page_bytes = _render_page(dxf, page_index, font_path)
            with pymupdf.open(stream=page_bytes, filetype="pdf") as one_page:
                merged.insert_pdf(one_page)

        for page_index, page in enumerate(merged):
            _add_searchable_text_layer(page, document, page_index, font_path)

        merged.set_metadata(
            {
                "title": document.project_name,
                "author": "RefracDraft",
                "creator": "RefracDraft DXF renderer",
                "producer": "ezdxf / PyMuPDF",
            }
        )
        temporary_pdf = Path(temp_dir) / "rendered.pdf"
        merged.save(str(temporary_pdf), garbage=4, deflate=True)
        merged.close()
        temporary_pdf.replace(output_path)

    return output_path
