from __future__ import annotations

import argparse
import json
from pathlib import Path

from refracdraft.domain.models import Project
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import export_pdf
from refracdraft.importers.excel import import_project_xlsx
from refracdraft.reference.library import ReferenceLibrary


def _load_project(path: Path) -> Project:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return import_project_xlsx(path)
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="refrac-draft", description="二维耐火材料模块加工图生成器")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="从 JSON/Excel 参数生成 DXF 和 PDF")
    gen.add_argument("input", type=Path)
    gen.add_argument("--outdir", type=Path, default=Path("output"))
    gen.add_argument("--reference-dxf", type=Path, default=Path("references/示例.dxf"))
    gen.add_argument("--reference-pdf", type=Path, default=Path("references/江阴铁包-11098-qf.pdf"))
    analyze = sub.add_parser("analyze-reference", help="读取参考 DXF 并输出夹板面模板目录")
    analyze.add_argument("--dxf", type=Path, default=Path("references/示例.dxf"))
    analyze.add_argument("--output", type=Path, default=Path("output/board_face_catalog.json"))
    args = parser.parse_args()

    if args.command == "analyze-reference":
        library = ReferenceLibrary(args.dxf)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(library.board_face_catalog(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"模板目录已写入: {args.output}")
        return

    project = _load_project(args.input)
    library = ReferenceLibrary(args.reference_dxf) if args.reference_dxf.exists() else None
    drawing = DrawingGenerator(library).generate(project)
    args.outdir.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem
    dxf_path = export_dxf(drawing, args.outdir / f"{stem}.dxf", args.reference_dxf)
    pdf_path = export_pdf(drawing, args.outdir / f"{stem}.pdf", args.reference_pdf)
    print(f"DXF: {dxf_path}\nPDF: {pdf_path}")
    for warning in drawing.warnings:
        print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
