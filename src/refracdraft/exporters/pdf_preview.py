from __future__ import annotations

import pymupdf


def render_pdf_preview(pdf_bytes: bytes, page_index: int) -> bytes:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        return pdf[page_index].get_pixmap(dpi=180, alpha=False).tobytes("png")
