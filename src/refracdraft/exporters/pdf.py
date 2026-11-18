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
    Path(r"C:\Windows\Fonts\simsun.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    resource_path("assets/fonts/SourceHanSansSC-Regular.otf"),
    resource_path("assets/fonts/SourceHanSansSC-Regular.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)
PDF_FONT_SUFFIXES = {".otf", ".ttf", ".ttc"}
PDF_FONT_PREFERRED_STEMS = (
    "sourcehansanssc",
    "notosanscjk",
    "sourcehansans",
    "microsoftyahei",
    "msyh",
    "simhei",
    "simsun",
)


def _font_score(path: Path) -> tuple[int, str]:
    stem = path.stem.lower().replace("-", "").replace("_", "").replace(" ", "")
    for index, preferred in enumerate(PDF_FONT_PREFERRED_STEMS):
        if preferred in stem:
            return index, str(path).lower()
    return len(PDF_FONT_PREFERRED_STEMS), str(path).lower()


def _fonts_in_directory(directory: Path | None) -> list[Path]:
    if directory is None or not directory.is_dir():
        return []
    found: list[Path] = []
    for root in (directory, *directory.glob("*")):
        try:
            if root.is_file() and root.suffix.lower() in PDF_FONT_SUFFIXES:
                found.append(root)
            elif root.is_dir():
                found.extend(
                    path
                    for path in root.rglob("*")
                    if path.is_file() and path.suffix.lower() in PDF_FONT_SUFFIXES
                )
        except OSError:
            continue
    return sorted(set(found), key=_font_score)


def _find_pdf_font(
    font_directory: str | Path | None = None,
    font_path: str | Path | None = None,
) -> Path | None:
    if font_path:
        explicit = Path(font_path).expanduser()
        if explicit.is_file():
            return explicit
    if font_directory:
        external = _fonts_in_directory(Path(font_directory).expanduser())
        if external:
            return external[0]
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
    # A user-selected PDF font should own every text style in the plot. This
    # avoids mixed glyphs when the title block carries its own style table.
    font_face = fonts.FontFace(filename=font_path.name)
    for style_name in tuple(context.fonts):
        context.fonts[style_name] = font_face
    context.fonts["standard"] = font_face


def _render_page(
    doc,
    page_index: int,
    font_path: Path | None,
    font_directory: Path | None = None,
) -> bytes:
    page_y = -page_index * PAGE_STRIDE_MM * MODEL_SCALE
    render_box = BoundingBox2d(
        [(0, page_y), (PAGE_WIDTH_MM * MODEL_SCALE, page_y + PAGE_HEIGHT_MM * MODEL_SCALE)]
    )
    backend = PyMuPdfBackend()
    for folder in (font_directory, font_path.parent if font_path else None):
        if folder and folder.is_dir():
            fonts.font_manager.scan_folder(folder)
    # Export mode honors each layer's plot flag, so text/geometry on a
    # non-printing layer (for example the source DXF's 不打印 layer) stays out
    # of the PDF while remaining visible and editable in the DXF.
    context = RenderContext(doc, export_mode=True)
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
    font_directory: str | Path | None = None,
    font_path: str | Path | None = None,
) -> Path:
    """Render a PDF from the same DXF that is exported to the customer.

    ``reference_pdf`` is retained as a compatibility argument for callers from
    earlier releases. The PDF is no longer assembled by overlaying a reference
    PDF; the frame and title block come from the generated DXF block references.
    """
    del reference_pdf
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    external_font_directory = (
        Path(font_directory).expanduser() if font_directory else None
    )
    selected_font_path = _find_pdf_font(external_font_directory, font_path)
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
            page_bytes = _render_page(
                dxf,
                page_index,
                selected_font_path,
                external_font_directory,
            )
            with pymupdf.open(stream=page_bytes, filetype="pdf") as one_page:
                merged.insert_pdf(one_page)

        for page_index, page in enumerate(merged):
            _add_searchable_text_layer(page, document, page_index, selected_font_path)

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
