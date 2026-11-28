from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass
import json
from multiprocessing import get_context
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
from ezdxf.fonts.shapefile import GlyphCache, ShapeFileException, readfile as read_shx
from ezdxf.math import BoundingBox2d

from refracdraft.drawing.layout import DETAIL_TEXT_SIZE_MM, PAGE_WIDTH_MM, PAGE_HEIGHT_MM, PAGE_STRIDE_MM, page_model_origins
from refracdraft.drawing.model import DrawingDocument
from refracdraft.exporters.dxf import export_dxf
from refracdraft.resources import resource_path


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


def shx_detail_measure(directory: str | Path | None) -> Callable[[str], float] | None:
    main, big = _resolve_shx_fonts(directory, None, None)
    if main is None or big is None or (main.name.casefold(), big.name.casefold()) != ("gbenor.shx", "gbcbig.shx"):
        return None
    try:
        glyphs = GlyphCache(read_shx(str(main.path)))
    except (OSError, ShapeFileException):
        return None
    advances = {}

    def measure(text: str) -> float:
        for char in set(text) - advances.keys():
            if ord(char) in glyphs.font.shapes:
                advances[char] = 1.05 * glyphs.get_text_length(char, DETAIL_TEXT_SIZE_MM)
            else:
                # The plotted GB bigfont has a square cell. Allow clearance for non-GB fallback glyphs.
                advances[char] = DETAIL_TEXT_SIZE_MM * (1.08 if char.encode("gbk", errors="ignore") else 1.39)
        return sum(advances[char] for char in text)

    return measure


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


def _fit_fallback_template_text(doc, font_path: Path) -> None:
    """Fit reference MTEXT cells when the outline font is wider than the SHX font."""
    fonts.font_manager.scan_folder(font_path.parent)
    for name in ("图框-A4", "标题栏"):
        block = doc.blocks.get(name)
        if block is None:
            continue
        for entity in block.query("MTEXT"):
            width = entity.dxf.width
            if width <= 0:
                continue
            if name == "图框-A4":
                width = min(width, 166.0 - entity.dxf.insert.x) if r"\P" in entity.text else width
            if width <= 0:
                continue
            font = fonts.make_font(font_path.name, entity.dxf.char_height)
            needed = max(map(font.text_width, entity.plain_text(split=True)), default=0.0)
            if needed > width * 0.96:
                factor = width * 0.96 / needed
                paragraphs = entity.text.split(r"\P")
                entity.text = r"\P".join(rf"{{\W{factor:.5f};{text}}}" for text in paragraphs)


def _single_page_dxf(
    source_dxf: Path,
    page_index: int,
    target: Path,
    has_bigfont: bool,
    denominator: int = MODEL_SCALE,
    page_y: float | None = None,
) -> Path:
    doc = ezdxf.readfile(source_dxf)
    if page_y is None:
        page_y = -page_index * PAGE_STRIDE_MM * denominator
    return _write_shx_page_dxf(doc, target, has_bigfont, denominator, page_y, _dxf_vertical_bounds(doc))


def _dxf_vertical_bounds(doc) -> dict[str, tuple[float, float]]:
    bounds = {}
    for entity in doc.modelspace():
        try:
            extents = ezdxf_bbox.extents([entity])
            bounds[entity.dxf.handle] = (extents.extmin.y, extents.extmax.y)
        except Exception:
            continue
    return bounds


def _write_shx_page_dxf(
    doc, target: Path, has_bigfont: bool, denominator: int, page_y: float,
    bounds: dict[str, tuple[float, float]],
) -> Path:
    page_top = page_y + PAGE_HEIGHT_MM * denominator
    msp = doc.modelspace()
    for entity in list(msp):
        extent = bounds.get(entity.dxf.handle)
        if extent is not None and (extent[1] < page_y - 1.0 or extent[0] > page_top + 1.0):
            msp.delete_entity(entity)
    if page_y:
        for entity in list(msp):
            entity.translate(0.0, -page_y, 0.0)
    # The SHX renderer reads MTEXT's direction vector. A translated page already
    # has it, but unshifted DXF dimension blocks can store only the rotation angle.
    for dimension in msp.query("DIMENSION"):
        block = dimension.get_geometry_block()
        if block is None:
            continue
        for text in block.query("MTEXT"):
            text.convert_rotation_to_text_direction()
    _apply_shx_text_style(doc, has_bigfont)
    _normalize_title_fonts(doc)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(target)
    return target


_PDF_NUMBER = rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_SHX_PAGE_TRANSFORM = re.compile(rb"\A\s*q\s+(" + rb"\s+".join([_PDF_NUMBER] * 6) + rb")\s+cm\b")


def _fix_shx_page_scale(page: pymupdf.Page, denominator: int = MODEL_SCALE) -> None:
    """Keep the model-space A4 origin and scale even if MLightCAD fits the artwork."""
    for xref in page.get_contents():
        stream = page.parent.xref_stream(xref)
        transform = _SHX_PAGE_TRANSFORM.match(stream)
        if transform is None:
            continue
        sx, skew_y, skew_x, sy, _, _ = map(float, transform[1].split())
        if sx <= 0 or sx != sy or skew_x or skew_y:
            break
        scale = 72 / 25.4 / denominator
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
    workers: int,
    page_progress: Callable[[int, int], None],
) -> Path:
    node, script, exporter_dir = exporter
    staged_fonts = temp_dir / "fonts"
    staged_fonts.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(main_font.path, staged_fonts / "gbenor.shx")
    if bigfont is not None:
        shutil.copyfile(bigfont.path, staged_fonts / "gbcbig.shx")

    origins = page_model_origins(document)
    page_count = len(origins)

    def prepare_pages():
        if not origins:
            return
        progress("正在分析 DXF 图元范围…")
        page_doc = ezdxf.readfile(source_dxf)
        bounds = _dxf_vertical_bounds(page_doc)
        for number, (page, page_y) in enumerate(zip(document.pages, origins), 1):
            progress(f"正在准备第 {number}/{page_count} 页 DXF…")
            if number > 1:
                page_doc = ezdxf.readfile(source_dxf)
            denominator = page.scale_denominator
            page_dxf = _write_shx_page_dxf(
                page_doc, temp_dir / f"page-{number}.dxf", bigfont is not None,
                denominator, page_y, bounds,
            )
            page_pdf = temp_dir / f"page-{number}.pdf"
            manifest_path = temp_dir / f"page-{number}.json"
            manifest = {
                "inputs": [str(page_dxf)],
                "output": str(page_pdf),
                "fontDirectory": str(staged_fonts),
                "builtInFont": str(built_in_font) if built_in_font else "",
                "fitBox": {
                    "min": {"x": 0.0, "y": 0.0},
                    "max": {
                        "x": PAGE_WIDTH_MM * denominator,
                        "y": PAGE_HEIGHT_MM * denominator,
                    },
                },
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            yield manifest_path, page_pdf, denominator

    def render(job):
        manifest_path, page_pdf, _denominator = job
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

    jobs = []
    completed = 0
    if workers > 1 and page_count > 1:
        with ThreadPoolExecutor(max_workers=min(workers, page_count)) as pool:
            pending = set()
            for job in prepare_pages():
                if not jobs:
                    page_progress(0, page_count)
                if pending:
                    done, pending = wait(
                        pending, timeout=None if len(pending) >= workers else 0, return_when=FIRST_COMPLETED
                    )
                    for future in done:
                        future.result()
                        completed += 1
                        page_progress(completed, page_count)
                jobs.append(job)
                pending.add(pool.submit(render, job))
            for future in as_completed(pending):
                future.result()
                completed += 1
                page_progress(completed, page_count)
    else:
        for completed, job in enumerate(prepare_pages(), 1):
            if not jobs:
                page_progress(0, page_count)
            jobs.append(job)
            render(job)
            page_progress(completed, page_count)

    progress("正在合并并保存 PDF…")
    temporary_pdf = temp_dir / "rendered-shx.pdf"
    with pymupdf.open() as merged:
        for _manifest_path, page_pdf, denominator in jobs:
            with pymupdf.open(page_pdf) as one_page:
                _fix_shx_page_scale(one_page[0], denominator)
                merged.insert_pdf(one_page)
        merged.set_metadata({
            "title": document.project_name,
            "author": "RefracDraft",
            "creator": "RefracDraft SHX renderer",
            "producer": "MLightCAD / PDF",
        })
        merged.save(str(temporary_pdf), garbage=4, deflate=True)
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
    denominator: int = MODEL_SCALE,
    page_y: float | None = None,
) -> bytes:
    if page_y is None:
        page_y = -page_index * PAGE_STRIDE_MM * denominator
    render_box = BoundingBox2d(
        [(0, page_y), (PAGE_WIDTH_MM * denominator, page_y + PAGE_HEIGHT_MM * denominator)]
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


def _load_render_dxf(source_dxf: Path, font_path: Path | None):
    dxf = ezdxf.readfile(source_dxf)
    _normalize_title_fonts(dxf)
    if font_path is not None:
        _fit_fallback_template_text(dxf, font_path)
    return dxf


_FALLBACK_DXF = None


def _init_fallback_worker(source_dxf, font_path):
    global _FALLBACK_DXF
    _FALLBACK_DXF = _load_render_dxf(source_dxf, font_path)


def _render_fallback_page(font_path, font_directory, page, scratch):
    page_index, denominator, page_y = page
    destination = scratch / f"fallback-page-{page_index + 1}.pdf"
    destination.write_bytes(
        _render_page(_FALLBACK_DXF, page_index, font_path, font_directory, denominator, page_y)
    )
    return destination


def _render_fallback_pages(source_dxf, font_path, font_directory, pages, workers, page_progress, scratch):
    page_progress(0, len(pages))
    if workers < 2 or len(pages) < 2:
        dxf = _load_render_dxf(source_dxf, font_path)
        for completed, (page_index, denominator, page_y) in enumerate(pages, 1):
            page_bytes = _render_page(dxf, page_index, font_path, font_directory, denominator, page_y)
            page_progress(completed, len(pages))
            yield page_bytes
        return
    workers = min(workers, len(pages))
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=get_context("spawn"),
        initializer=_init_fallback_worker, initargs=(source_dxf, font_path),
    ) as pool:
        futures = [pool.submit(_render_fallback_page, font_path, font_directory, page, scratch) for page in pages]
        for completed, future in enumerate(as_completed(futures), 1):
            future.result()
            page_progress(completed, len(pages))
        for future in futures:
            yield future.result().read_bytes()


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
    page_progress: Callable[[int, int], None] | None = None,
    workers: int = 1,
) -> Path:
    """Render a PDF from the same DXF that is exported to the customer.

    ``reference_pdf`` is retained as a compatibility argument for callers from
    earlier releases. The PDF is no longer assembled by overlaying a reference
    PDF; the frame and title block come from the generated DXF block references.
    """
    del reference_pdf
    report = progress or (lambda _text: None)
    report_page = page_progress or (lambda done, total: report(f"正在渲染 PDF {done}/{total}…"))
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
                workers,
                report_page,
            )

        pages = [(index, document.pages[index].scale_denominator, page_y)
                 for index, page_y in enumerate(page_model_origins(document))]
        temporary_pdf = Path(temp_dir) / "rendered.pdf"
        with pymupdf.open() as merged:
            for page_bytes in _render_fallback_pages(
                source_dxf, selected_font_path, external_font_directory, pages, workers, report_page, Path(temp_dir)
            ):
                with pymupdf.open(stream=page_bytes, filetype="pdf") as one_page:
                    merged.insert_pdf(one_page)
            report("正在保存 PDF…")
            for page_index, page in enumerate(merged):
                _add_searchable_text_layer(page, document, page_index, selected_font_path)
            merged.set_metadata({
                "title": document.project_name,
                "author": "RefracDraft",
                "creator": "RefracDraft DXF renderer",
                "producer": "ezdxf / PyMuPDF",
            })
            merged.save(str(temporary_pdf), garbage=4, deflate=True)
        temporary_pdf.replace(output_path)

    return output_path
