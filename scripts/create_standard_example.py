from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation


def create_example(path: Path) -> None:
    wb = Workbook()
    modules = wb.active
    modules.title = "模块参数"
    modules.append(
        [
            "模块编号",
            "模块名称",
            "折叠方式",
            "几何类型",
            "正面宽度",
            "正面高度",
            "膨胀长度",
            "正面左高",
            "正面右高",
            "侧面长度",
            "侧面左高",
            "侧面右高",
            "夹板面宽度",
            "夹板面高度",
            "夹板面类型",
            "模块材质",
            "容重",
            "模块数量",
            "备注",
        ]
    )
    modules.append(
        ["M1", "折叠模块M1", "折叠", "普通", 300, 300, 300, None, None, None, None, None,
         300, 230, "rectangular", "1430", 220, 1, "普通模块示例"]
    )
    modules.append(
        ["M2", "半折叠模块M2", "半折叠", "普通", 450, 300, 350, None, None, None, None, None,
         450, 230, "rectangular", "1350", 220, 2, "普通模块示例"]
    )
    modules.append(
        ["M3", "层叠模块M3", "层叠", "普通", 750, 350, 400, None, None, None, None, None,
         750, 230, "rectangular", "1260", 220, 3, "普通模块示例"]
    )
    modules.append(
        ["M4", "自定义折叠M4", "自定义", "正敲", 300, 300, 300, 300, 220, None, None, None,
         300, 230, "rectangular", "1430", 220, 1, "正敲示例"]
    )
    modules.append(
        ["M5", "折叠模块M5", "折叠", "侧敲", 450, 300, 300, None, None, 450, 300, 220,
         450, 230, "rectangular", "1350", 220, 1, "侧敲示例"]
    )
    modules.append(
        ["M6", "半折叠模块M6", "半折叠", "侧敲", 750, 300, 330, None, None, 750, 330, 250,
         750, 230, "rectangular", "1260", 220, 2, "侧敲示例"]
    )

    boards = wb.create_sheet("夹板参数")
    boards.append(["模块编号", "是否有夹板", "夹板材质", "夹板厚度", "开口模式", "备注"])
    for module_id in ("M1", "M2", "M3", "M4", "M5", "M6"):
        boards.append([module_id, "有", "9厘", 9, "无开口", "示例夹板"])

    anchors = wb.create_sheet("锚固件参数")
    anchors.append(
        [
            "模块编号",
            "是否有锚固件",
            "锚固件类型",
            "锚固件材质",
            "螺纹规格",
            "直径",
            "锚固件长度",
            "嵌入深度",
            "锚固件数量",
            "布置方式",
            "端部留边",
            "锚固件间距",
            "胶管规格",
            "备注",
        ]
    )
    for module_id, anchor_type, material, thread, diameter, depth, hose, count in (
        ("M1", "M型", "310", "M10", 8, None, "32", 1),
        ("M2", "M型", "310", "M10", 8, None, "32", 2),
        ("M3", "M型", "310", "M10", 8, None, "32", 3),
        ("M4", "菱形", "304", "M8", None, 50, "25", 1),
        ("M5", "菱形", "304", "M8", None, 50, "25", 2),
        ("M6", "菱形", "304", "M8", None, 50, "25", 3),
    ):
        anchors.append(
            [module_id, "有", anchor_type, material, thread, diameter, 230, depth,
             count, "指定间距", 150, 300, hose, "示例锚固件"]
        )

    folding = DataValidation(
        type="list",
        formula1='"折叠,半折叠,层叠,自定义"',
        allow_blank=False,
    )
    geometry = DataValidation(type="list", formula1='"普通,正敲,侧敲"', allow_blank=False)
    modules.add_data_validation(folding)
    modules.add_data_validation(geometry)
    folding.add("C2:C200")
    geometry.add("D2:D200")

    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for column in ws.columns:
            letter = column[0].column_letter
            ws.column_dimensions[letter].width = max(
                11, min(22, max(len(str(cell.value or "")) for cell in column) + 2)
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


if __name__ == "__main__":
    create_example(Path("examples/standard_example_6_modules.xlsx"))
