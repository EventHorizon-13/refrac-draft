from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from refracdraft.domain.models import BoardFaceProfile, Project
from refracdraft.drawing.model import DrawingDocument
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import export_pdf
from refracdraft.standard_sheet import COLUMN_SPECS, PROFILE_COLUMNS, PROFILE_SHEET, row_values_from_models


def export_standard_excel(project: Project, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "标准版"
    ws.append([spec.label for spec in COLUMN_SPECS])
    ws.freeze_panes = "B2"
    profile_sheet = None
    for module in project.modules:
        row = row_values_from_models(module, project.board_for(module.module_id), project.anchor_for(module.module_id))
        ws.append([row[spec.key] for spec in COLUMN_SPECS])
        for cell in ws[ws.max_row]:
            if cell.data_type == "f":
                cell.data_type = "s"
        profile = module.board_face_outline
        if isinstance(profile, BoardFaceProfile):
            if profile_sheet is None:
                profile_sheet = wb.create_sheet(PROFILE_SHEET)
                profile_sheet.append(PROFILE_COLUMNS)
                profile_sheet.freeze_panes = "B2"
            for cut in profile.features:
                profile_sheet.append((module.module_id, cut.type, cut.a, cut.b, cut.c, cut.d,
                                      cut.rotation_deg, cut.mirror_x))
                profile_sheet.cell(profile_sheet.max_row, 1).data_type = "s"
    ws.auto_filter.ref = ws.dimensions
    for cells, spec in zip(ws.columns, COLUMN_SPECS):
        ws.column_dimensions[cells[0].column_letter].width = max(10, spec.width / 7)
    wb.save(path)


def export_complete_project(
    project: Project,
    drawing: DrawingDocument,
    path: Path,
    *,
    reference_dxf: Path | None = None,
    font_directory: str | None = None,
    progress: Callable[[str], None],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="refracdraft-project-", dir=path.parent) as directory:
        stage = Path(directory)
        files = {ext: stage / f"{path.stem}.{ext}" for ext in ("json", "xlsx", "dxf", "pdf")}
        progress("正在写入 JSON 和 Excel…")
        files["json"].write_text(project.model_dump_json(indent=2), encoding="utf-8")
        export_standard_excel(project, files["xlsx"])
        progress("正在生成 DXF…")
        export_dxf(drawing, files["dxf"], reference_dxf)
        export_pdf(drawing, files["pdf"], dxf_path=files["dxf"], font_directory=font_directory, progress=progress)
        progress("正在打包完整项目…")
        archive = stage / path.name
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zip_file:
            for file in files.values():
                zip_file.write(file, arcname=file.name)
        archive.replace(path)
