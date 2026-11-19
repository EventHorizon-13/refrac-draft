from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from refracdraft.standard_sheet import COLUMN_SPECS


def create_example(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "标准版"
    sheet.append([spec.label for spec in COLUMN_SPECS])
    for number, (length, expansion, folding, material, quantity, taper, small_head, count) in enumerate(
        [
            (300, 300, "折叠", "1430", 1, "", None, 1),
            (450, 350, "半折叠", "1350", 2, "", None, 2),
            (750, 400, "层叠", "1260", 3, "", None, 3),
            (300, 300, "自定义折叠", "1430", 1, "正敲", 220, 1),
            (450, 300, "折叠", "1350", 1, "侧敲", 220, 2),
            (750, 330, "半折叠", "1260", 2, "侧敲", 250, 3),
        ],
        start=1,
    ):
        diamond = number >= 4
        row = {
            "module_id": f"M{number}",
            "length_mm": length,
            "expansion_length_mm": expansion,
            "thickness_mm": 230,
            "structure_type": folding,
            "material": material,
            "density_kg_m3": 220,
            "production_quantity": quantity,
            "taper_enabled": "是" if taper else "否",
            "big_head_mm": expansion if taper else None,
            "small_head_mm": small_head,
            "taper_type": taper,
            "board_exists": "是",
            "board_material": "9厘",
            "anchor_enabled": "是",
            "anchor_position_mm": 150,
            "anchor_spacing_mm": 300,
            "anchor_count": count,
            "anchor_type": "菱形" if diamond else "M型",
            "anchor_length_mm": 230,
            "anchor_material": "304" if diamond else "310",
            "thread_spec": "M8" if diamond else "M10",
            "pin_diameter_mm": None if diamond else 8,
            "hose_spec": "25" if diamond else "32",
            "embedment_depth_mm": 50 if diamond else None,
            "source_note": f"{taper or '普通模块'}示例",
        }
        sheet.append([row[spec.key] for spec in COLUMN_SPECS])

    for index, spec in enumerate(COLUMN_SPECS, start=1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = max(9, round(spec.width / 6))
        choices = ("是", "否") if spec.kind == "check" else spec.options
        if choices:
            validation = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True)
            sheet.add_data_validation(validation)
            validation.add(f"{letter}2:{letter}200")
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


if __name__ == "__main__":
    create_example(Path("examples/standard_example_6_modules.xlsx"))
