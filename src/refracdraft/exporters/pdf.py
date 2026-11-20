from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Callable

import ezdxf
import pymupdf
from ezdxf import bbox as ezdxf_bbox
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
    resource_path("assets/fonts/SourceHanSerifSC-Regular.otf"),
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


@dataclass(frozen=True)
class ShxFontInfo:
    name: str
    path: Path
    is_bigfont: bool


def _is_bigfont_shx(path: Path) -> bool:
    try:
        header = path.read_bytes()[:128].lower()
    except OSError:
        return False
    return b"bigfont" in header


def list_shx_fonts(directory: str | Path | None) -> list[ShxFontInfo]:
    if not directory:
        return []
    root = Path(directory).expanduser()
    if not root.is_dir():
        return []
    found: dict[str, ShxFontInfo] = {}
    try:
        paths = root.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix.lower() != ".shx":
                continue
            name = path.name
            key = name.lower()
            info = ShxFontInfo(name, path, _is_bigfont_shx(path))
            previous = found.get(key)
            if previous is None or len(path.parts) < len(previous.path.parts):
                found[key] = info
    except OSError:
        return []
    return sorted(found.values(), key=lambda info: info.name.lower())


def _resolve_shx_fonts(
    directory: str | Path | None,
    font_name: str | None,
    bigfont_name: str | None,
) -> tuple[ShxFontInfo | None, ShxFontInfo | None]:
    infos = list_shx_fonts(directory)
    if not infos:
        return None, None
    by_name = {info.name.lower(): info for info in infos}
    main = by_name.get((font_name or "").lower())
    if main is None:
        main = by_name.get("gbenor.shx")
    if main is None:
        main = next((info for info in infos if not info.is_bigfont), infos[0])

    if bigfont_name is not None and not bigfont_name.strip():
        return main, None
    bigfont = by_name.get((bigfont_name or "").lower()) if bigfont_name else None
    if bigfont is None and bigfont_name is None:
        bigfont = by_name.get("gbcbig.shx")
    if bigfont is None and bigfont_name is None:
        bigfont = next((info for info in infos if info.is_bigfont), None)
    return main, bigfont


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


def _pdf_exporter_paths() -> tuple[Path, Path, Path] | None:
    candidates: list[Path] = []
    override = os.environ.get("REFRACDRAFT_PDF_EXPORTER_DIR", "").strip()
    if override:
        candidates.append(Path(override).expanduser().resolve())
    candidates.append(resource_path("assets/pdf-exporter").resolve())
    for directory in candidates:
        if not directory.is_dir():
            continue
        script = directory / "pdf-exporter.bundle.mjs"
        if not script.is_file():
            continue
        node = directory / ("node.exe" if os.name == "nt" else "node")
        if not node.is_file():
            executable = shutil.which("node")
            if not executable:
                continue
            node = Path(executable)
        return node, script, directory
    return None


def _apply_shx_text_style(doc, has_bigfont: bool) -> None:
    for style in doc.styles:
        style.dxf.font = "gbenor.shx"
        style.dxf.bigfont = "gbcbig.shx" if has_bigfont else ""


_TITLE_INLINE_FONT = re.compile(r"(?<!\\)\\[fF][^;]*;")


def _normalize_title_fonts(doc) -> None:
    """Use the plot font in the template's title block and its nested logo."""
    pending = ["标题栏"]
    visited: set[str] = set()
    while pending:
        name = pending.pop()
        if name.casefold() in visited:
            continue
        visited.add(name.casefold())
        block = doc.blocks.get(name)
        if block is None:
            continue
        for entity in block.query("MTEXT INSERT"):
            if entity.dxftype() == "INSERT":
                pending.append(entity.dxf.name)
            else:
                entity.text = _TITLE_INLINE_FONT.sub("", entity.text).replace(r"\~", " ")


def _single_page_dxf(
    source_dxf: Path,
    page_index: int,
    target: Path,
    has_bigfont: bool,
) -> Path:
    doc = ezdxf.readfile(source_dxf)
    page_y = -page_index * PAGE_STRIDE_MM * MODEL_SCALE
    page_top = page_y + PAGE_HEIGHT_MM * MODEL_SCALE
    msp = doc.modelspace()
    for entity in list(msp):
        try:
            extents = ezdxf_bbox.extents([entity])
        except Exception:
            continue
        if extents.extmax.y < page_y - 1.0 or extents.extmin.y > page_top + 1.0:
            msp.delete_entity(entity)
    if page_y:
        for entity in list(msp):
            entity.translate(0.0, -page_y, 0.0)
    _apply_shx_text_style(doc, has_bigfont)
    _normalize_title_fonts(doc)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(target)
    return target


_PDF_NUMBER = rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_SHX_PAGE_TRANSFORM = re.compile(rb"\A\s*q\s+(" + rb"\s+".join([_PDF_NUMBER] * 6) + rb")\s+cm\b")


def _fix_shx_page_scale(page: pymupdf.Page) -> None:
    """Keep the model-space A4 origin and scale even if MLightCAD fits the artwork."""
    for xref in page.get_contents():
        stream = page.parent.xref_stream(xref)
        transform = _SHX_PAGE_TRANSFORM.match(stream)
        if transform is None:
            continue
        sx, skew_y, skew_x, sy, _, _ = map(float, transform[1].split())
        if sx <= 0 or sx != sy or skew_x or skew_y:
            break
        scale = 72 / 25.4 / MODEL_SCALE
        fixed = f"{scale:.12f} 0 0 {scale:.12f} 0 0".encode("ascii")
        # Change the vector stream before merging so off-page content can be recovered.
        start, end = transform.span(1)
        page.parent.update_stream(xref, stream[:start] + fixed + stream[end:])
        return
    raise RuntimeError("无法确认 SHX PDF 的图纸比例")


def _export_pdf_with_shx(
    document: DrawingDocument,
    output_path: Path,
    source_dxf: Path,
    temp_dir: Path,
    exporter: tuple[Path, Path, Path],
    main_font: ShxFontInfo,
    bigfont: ShxFontInfo | None,
    built_in_font: Path | None,
    progress: Callable[[str], None],
) -> Path:
    node, script, exporter_dir = exporter
    staged_fonts = temp_dir / "fonts"
    staged_fonts.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(main_font.path, staged_fonts / "gbenor.shx")
    if bigfont is not None:
        shutil.copyfile(bigfont.path, staged_fonts / "gbcbig.shx")

    merged = pymupdf.open()
    page_count = max(1, len(document.pages))
    for page_index in range(page_count):
        progress(f"正在渲染 PDF {page_index + 1}/{page_count}…")
        page_dxf = _single_page_dxf(
            source_dxf,
            page_index,
            temp_dir / f"page-{page_index + 1}.dxf",
            bigfont is not None,
        )
        page_pdf = temp_dir / f"page-{page_index + 1}.pdf"
        manifest_path = temp_dir / f"page-{page_index + 1}.json"
        manifest = {
            "inputs": [str(page_dxf)],
            "output": str(page_pdf),
            "fontDirectory": str(staged_fonts),
            "builtInFont": str(built_in_font) if built_in_font else "",
            "fitBox": {
                "min": {"x": 0.0, "y": 0.0},
                "max": {
                    "x": PAGE_WIDTH_MM * MODEL_SCALE,
                    "y": PAGE_HEIGHT_MM * MODEL_SCALE,
                },
            },
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        result = subprocess.run(
            [str(node), str(script), "--manifest", str(manifest_path)],
            cwd=exporter_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"PDF 渲染器执行失败：{detail or '未知错误'}")
        if not page_pdf.is_file() or page_pdf.stat().st_size < 8:
            raise RuntimeError("PDF 渲染器没有生成有效文件")
        with pymupdf.open(page_pdf) as one_page:
            _fix_shx_page_scale(one_page[0])
            merged.insert_pdf(one_page)

    merged.set_metadata(
        {
            "title": document.project_name,
            "author": "RefracDraft",
            "creator": "RefracDraft SHX renderer",
            "producer": "MLightCAD / PDF",
        }
    )
    temporary_pdf = temp_dir / "rendered-shx.pdf"
    merged.save(str(temporary_pdf), garbage=4, deflate=True)
    merged.close()
    temporary_pdf.replace(output_path)
    return output_path


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
    shx_font: str | Path | None = None,
    shx_bigfont: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Render a PDF from the same DXF that is exported to the customer.

    ``reference_pdf`` is retained as a compatibility argument for callers from
    earlier releases. The PDF is no longer assembled by overlaying a reference
    PDF; the frame and title block come from the generated DXF block references.
    """
    del reference_pdf
    report = progress or (lambda _text: None)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    external_font_directory = (
        Path(font_directory).expanduser() if font_directory else None
    )
    selected_font_path = _find_pdf_font(external_font_directory, font_path)
    source_dxf = Path(dxf_path) if dxf_path is not None else None
    bigfont_argument = None if shx_bigfont is None else str(shx_bigfont)
    main_shx, bigfont_shx = _resolve_shx_fonts(
        external_font_directory,
        str(shx_font) if shx_font else None,
        bigfont_argument,
    )
    exporter = _pdf_exporter_paths()
    if main_shx is not None and exporter is None:
        raise RuntimeError("PDF SHX 渲染器未随程序打包，请完整解压便携版后重试。")

    with TemporaryDirectory(prefix="refracdraft-pdf-", dir=output_path.parent) as temp_dir:
        if source_dxf is None:
            report("正在生成与 PDF 同源的 DXF…")
            source_dxf = Path(temp_dir) / "drawing.dxf"
            export_dxf(document, source_dxf, _reference_dxf_path(reference_dxf))
        elif not source_dxf.is_file():
            raise FileNotFoundError(f"DXF 文件不存在: {source_dxf}")

        if main_shx is not None and exporter is not None:
            return _export_pdf_with_shx(
                document,
                output_path,
                source_dxf,
                Path(temp_dir),
                exporter,
                main_shx,
                bigfont_shx,
                selected_font_path,
                report,
            )

        dxf = ezdxf.readfile(source_dxf)
        _normalize_title_fonts(dxf)
        merged = pymupdf.open()
        for page_index in range(len(document.pages)):
            report(f"正在渲染 PDF {page_index + 1}/{len(document.pages)}…")
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
