from __future__ import annotations

import sys


def main() -> None:
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from refracdraft.app import _smoke_test
    from refracdraft.domain.models import Project
    from refracdraft.resources import resource_path
    from refracdraft.standard import ensure_standard_project
    from refracdraft.ui.standard_window import COLUMN_INDEX, StandardWindow

    smoke = "--smoke-test" in sys.argv
    trace = Path("RefracDraft-Standard-smoke-trace.txt")
    if smoke:
        trace.write_text("start\n", encoding="utf-8")
    app = QApplication([sys.argv[0]] if smoke else sys.argv)
    app.setApplicationName("RefracDraft Standard")
    window = StandardWindow()
    if smoke:
        trace.write_text("window created\n", encoding="utf-8")
        try:
            sample = Project.model_validate_json(
                resource_path("examples/b2_positive_tap.json").read_text(encoding="utf-8")
            )
            ensure_standard_project(sample)
            trace.write_text("sample loaded\n", encoding="utf-8")
            window.project = sample
            window._populate_tables()
            window.resize(1500, 900)
            window.show()
            app.processEvents()
            window.grab().save("RefracDraft-Standard-ui.png")
            trace.write_text("editor populated\n", encoding="utf-8")
            if len(window.rows) != 1:
                raise ValueError("B2 示例未生成单个模块行")
            row = window.rows[0]
            table = window.parameter_table
            if window._cell_text(row, "module_id") != "B2":
                raise ValueError("模块编号未载入")
            if (
                window._cell_text(row, "length_mm") != "300"
                or window._cell_text(row, "thickness_mm") != "230"
            ):
                raise ValueError("长度或厚度未按 B2 示例载入")
            if (
                not window._cell_bool(row, "taper_enabled")
                or window._cell_text(row, "big_head_mm") != "289"
            ):
                raise ValueError("大小头参数未按 B2 示例载入")
            if not window._cell_bool(row, "anchor_enabled"):
                raise ValueError("锚固件参数未按 B2 示例载入")
            if (
                window._cell_text(row, "material") != "1430材质"
                or window._cell_text(row, "production_quantity") != "26"
            ):
                raise ValueError("模块材质或数量未按 B2 示例载入")
            if window._cell_text(row, "board_material") != "9厘夹板":
                raise ValueError("夹板类型未按 B2 示例载入")
            if (
                window._cell_text(row, "anchor_material") != "310"
                or window._cell_text(row, "thread_spec") != "M10"
                or window._cell_text(row, "pin_diameter_mm") != "8"
                or window._cell_text(row, "hose_spec") != "32胶管"
            ):
                raise ValueError("锚固件材质、螺栓、插针或胶管未按 B2 示例载入")
            roundtrip = window._collect_project()
            module = roundtrip.modules[0]
            if module.front_width_mm != 300 or module.board_face_height_mm != 230:
                raise ValueError("单行参数未正确映射到模块尺寸")
            if module.front_left_height_mm != 289 or module.front_right_height_mm != 220:
                raise ValueError("大小头尺寸映射错误")
            if module.material != "1430材质" or module.production_quantity != 26:
                raise ValueError("模块材质或数量映射错误")
            if roundtrip.boards[0].material != "9厘夹板":
                raise ValueError("夹板类型映射错误")
            if (
                roundtrip.anchors[0].material != "310"
                or roundtrip.anchors[0].thread_spec != "M10"
                or roundtrip.anchors[0].diameter_mm != 8
                or roundtrip.anchors[0].hose_spec != "32胶管"
            ):
                raise ValueError("锚固件明细参数映射错误")
            trace.write_text("row mapping passed\n", encoding="utf-8")
            from refracdraft.drawing.generator import DrawingGenerator
            from refracdraft.reference.library import ReferenceLibrary

            DrawingGenerator(ReferenceLibrary(window.reference_dxf)).generate(roundtrip)
            trace.write_text("mapped drawing passed\n", encoding="utf-8")

            anchor_cell = table.item(row, COLUMN_INDEX["anchor_enabled"])
            anchor_cell.setCheckState(Qt.CheckState.Unchecked)
            if not table.isColumnHidden(COLUMN_INDEX["anchor_position_mm"]):
                raise ValueError("取消锚固件后相关选项仍然显示")
            anchor_cell.setCheckState(Qt.CheckState.Checked)
            type_cell = table.item(row, COLUMN_INDEX["anchor_type"])
            type_cell.setText("菱形")
            if table.isColumnHidden(COLUMN_INDEX["embedment_depth_mm"]):
                raise ValueError("菱形锚固件未显示嵌入深度")
            type_cell.setText("M型")
            if not table.isColumnHidden(COLUMN_INDEX["embedment_depth_mm"]):
                raise ValueError("非菱形锚固件仍显示嵌入深度")
            trace.write_text("conditional fields passed\n", encoding="utf-8")

            table.item(row, COLUMN_INDEX["module_id"]).setText("B2X")
            added = window._add_module()
            table.setCurrentCell(row, 0)
            if window._cell_text(row, "module_id") != "B2X":
                raise ValueError("切换模块后编辑内容丢失")
            table.item(0, COLUMN_INDEX["module_id"]).setText("B2")
            table.clearSelection()
            table.setCurrentCell(added, 0)
            window._remove_selected_module()
            if len(window.rows) != 1:
                raise ValueError("添加与删除模块失败")
            trace.write_text("module add/remove passed\n", encoding="utf-8")

            added = window._add_module()
            length_column = COLUMN_INDEX["length_mm"]
            table.item(0, length_column).setText("456")
            table.item(added, length_column).setText("300")
            table._apply_fill((0, length_column, 0, length_column), (added, length_column))
            if table.item(added, length_column).text() != "456":
                raise ValueError("拖动填充未复制参数")
            table.clearSelection()
            table.setCurrentCell(added, 0)
            window._remove_selected_module()
            trace.write_text("fill handle passed\n", encoding="utf-8")
            _smoke_test(window)
            trace.write_text("exporters passed\n", encoding="utf-8")
        except Exception:
            import traceback

            Path("RefracDraft-Standard-smoke-error.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            raise SystemExit(1)
        return
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
