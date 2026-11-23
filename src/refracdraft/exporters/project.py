from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory

from openpyxl import Workbook

from refracdraft.domain.models import BoardFaceProfile, Project
from refracdraft.drawing.model import DrawingDocument
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import export_pdf
from refracdraft.standard_sheet import (
    AUTOMATIC, AUTOMATIC_FALLBACK_KEYS, AUTOMATIC_FIELDS, AUTOMATIC_SHEET, COLUMN_SPECS, PROFILE_COLUMNS, PROFILE_SHEET,
    STANDARD_LINK_VERSION, TAPER_LABEL_VERSION, row_values_from_models,
)


def export_standard_excel(project: Project, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "标准版"
    ws.append([spec.label for spec in COLUMN_SPECS])
    ws.freeze_panes = "B2"
    profile_sheet = None
    automatic_sheet = wb.create_sheet(AUTOMATIC_SHEET)
    automatic_sheet.sheet_state = "hidden"
    automatic_sheet.append(("module_id", *AUTOMATIC_FALLBACK_KEYS, "standard_link_version", "taper_label_version"))
    for module in project.modules:
        row = row_values_from_models(module, project.board_for(module.module_id), project.anchor_for(module.module_id))
        automatic_sheet.append([module.module_id, *(row[key] for key in AUTOMATIC_FALLBACK_KEYS),
                                STANDARD_LINK_VERSION, TAPER_LABEL_VERSION])
        for cell in automatic_sheet[automatic_sheet.max_row]:
            if cell.data_type == "f":
                cell.data_type = "s"
        active = project.standard_auto_fields.get(module.module_id, ())
        row.update(dict.fromkeys((key for key in AUTOMATIC_FIELDS if key in active), AUTOMATIC))
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
                                      cut.rotation_deg, cut.mirror_x, cut.cut_depth_mm, cut.cut_start.value,
                                      cut.face.value))
                profile_sheet.cell(profile_sheet.max_row, 1).data_type = "s"
    ws.auto_filter.ref = ws.dimensions
    for cells, spec in zip(ws.columns, COLUMN_SPECS):
        ws.column_dimensions[cells[0].column_letter].width = max(10, spec.width / 7)
    wb.save(path)


def project_output_paths(base_path: Path) -> dict[str, Path]:
    return {ext: base_path.parent / f"{base_path.name}.{ext}" for ext in ("json", "xlsx", "dxf", "pdf")}


def export_complete_project(
    project: Project,
    drawing: DrawingDocument,
    base_path: Path,
    *,
    reference_dxf: Path | None = None,
    font_directory: str | None = None,
    progress: Callable[[str], None],
) -> None:
    targets = project_output_paths(base_path)
    base_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="refracdraft-project-", dir=base_path.parent) as directory:
        stage = Path(directory)
        files = project_output_paths(stage / base_path.name)
        progress("正在写入 JSON 和 Excel…")
        excluded = set()
        if not project.standard_auto_fields:
            excluded.add("standard_auto_fields")
        if project.standard_link_version == 1:
            excluded.add("standard_link_version")
        files["json"].write_text(project.model_dump_json(indent=2, exclude=excluded), encoding="utf-8")
        export_standard_excel(project, files["xlsx"])
        progress("正在生成 DXF…")
        export_dxf(drawing, files["dxf"], reference_dxf)
        export_pdf(drawing, files["pdf"], dxf_path=files["dxf"], font_directory=font_directory, progress=progress)
        progress("正在保存四个项目文件…")
        backup_dir = stage / "previous"
        backup_dir.mkdir()
        with ExitStack() as rollback:
            for ext, target in targets.items():
                if target.exists():
                    backup = backup_dir / f"{ext}.backup"
                    copy2(target, backup)
                    files[ext].replace(target)
                    rollback.callback(backup.replace, target)
                else:
                    files[ext].replace(target)
                    rollback.callback(target.unlink, missing_ok=True)
            rollback.pop_all()
