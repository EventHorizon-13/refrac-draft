from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import Workbook


def create_template(path: Path) -> None:
    wb = Workbook()
    modules = wb.active
    modules.title = "模块参数"
    modules.append(["模块编号", "模块名称", "结构类型", "几何类型", "正面宽度", "正面高度", "正面左高", "正面右高",
                    "侧面长度", "侧面左高", "侧面右高", "夹板面宽度", "夹板面高度", "夹板面类型", "材质", "容重", "数量"])
    modules.append(["B2", "折叠模块", "折叠模块", "正敲", 300, 289, 289, 220, None, None, None,
                    300, 230, "rectangular", "1430材质", 220, 26])
    boards = wb.create_sheet("夹板参数")
    boards.append(["模块编号", "是否有夹板", "夹板材质", "夹板厚度", "开口模式", "自定义开口坐标"])
    boards.append(["B2", "有", "9厘夹板", 9, "无开口", None])
    anchors = wb.create_sheet("锚固件参数")
    anchors.append(["模块编号", "是否有锚固件", "锚固件类型", "锚固件材质", "螺纹规格", "直径", "锚固件长度",
                    "锚固件数量", "布置方式", "锚固件坐标", "端部留边", "锚固件间距", "胶管规格"])
    anchors.append(["B2", "有", "M型", "310", "M10", 8, 180, 1, "指定坐标",
                    '[{"x_mm":150,"y_mm":180}]', 50, None, "32胶管"])
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            letter = col[0].column_letter
            ws.column_dimensions[letter].width = max(12, min(24, max(len(str(c.value or "")) for c in col) + 2))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("examples/参数导入模板.xlsx"))
    args = parser.parse_args()
    create_template(args.output)
    print(f"Excel template written to {args.output}")


if __name__ == "__main__":
    main()
