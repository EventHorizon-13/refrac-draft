from __future__ import annotations

import sys


def _smoke_test(window) -> None:
    """Exercise the frozen reference files and both vector exporters on Windows."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    import ezdxf
    import fitz

    from refracdraft.domain.models import Project
    from refracdraft.drawing.generator import DrawingGenerator
    from refracdraft.exporters.dxf import export_dxf
    from refracdraft.exporters.pdf import export_pdf
    from refracdraft.reference.library import ReferenceLibrary
    from refracdraft.resources import resource_path

    input_path = resource_path("examples/b2_positive_tap.json")
    for path in (input_path, window.reference_dxf, window.reference_pdf):
        if not path.is_file():
            raise FileNotFoundError(f"便携版缺少资源文件: {path}")
    project = Project.model_validate_json(input_path.read_text(encoding="utf-8"))
    drawing = DrawingGenerator(ReferenceLibrary(window.reference_dxf)).generate(project)
    with TemporaryDirectory(prefix="refracdraft-smoke-") as temp_dir:
        dxf_path = export_dxf(drawing, Path(temp_dir) / "smoke.dxf", window.reference_dxf)
        pdf_path = export_pdf(drawing, Path(temp_dir) / "smoke.pdf", window.reference_pdf)
        if not list(ezdxf.readfile(dxf_path).modelspace()):
            raise ValueError("DXF 无可编辑实体")
        with fitz.open(pdf_path) as pdf:
            if len(pdf) != 1 or not pdf[0].get_drawings():
                raise ValueError("PDF 未生成矢量图纸")


def main() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit("桌面界面需要安装 PySide6：pip install 'refrac-draft[ui]' ") from exc
    from refracdraft.ui.main_window import MainWindow

    smoke = "--smoke-test" in sys.argv
    app = QApplication([sys.argv[0]] if smoke else sys.argv)
    app.setApplicationName("RefracDraft")
    window = MainWindow()
    if smoke:
        try:
            _smoke_test(window)
        except Exception:
            from pathlib import Path
            import traceback

            Path("RefracDraft-smoke-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1)
        return
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

