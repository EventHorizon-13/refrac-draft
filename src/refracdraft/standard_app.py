from __future__ import annotations

import sys


def main() -> None:
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from refracdraft.app import _smoke_test
    from refracdraft.domain.models import AnchorType, Project
    from refracdraft.resources import resource_path
    from refracdraft.standard import ensure_standard_project
    from refracdraft.ui.standard_window import StandardWindow

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
            trace.write_text("editor populated\n", encoding="utf-8")
            if len(window.rows) != 1:
                raise ValueError("B2 示例未生成单个模块行")
            row = window.rows[0]
            if row.module_id_edit.text() != "B2":
                raise ValueError("模块编号未载入")
            if (
                row.length_combo.currentText() != "300"
                or row.thickness_combo.currentText() != "230"
            ):
                raise ValueError("长度或厚度未按 B2 示例载入")
            if not row.taper_check.isChecked() or row.big_combo.currentText() != "289":
                raise ValueError("大小头参数未按 B2 示例载入")
            if not row.anchor_check.isChecked():
                raise ValueError("锚固件参数未按 B2 示例载入")
            if row.material_combo.currentText() != "1430材质" or row.quantity_spin.value() != 26:
                raise ValueError("模块材质或数量未按 B2 示例载入")
            if row.board_type_combo.currentText() != "9厘夹板":
                raise ValueError("夹板类型未按 B2 示例载入")
            if (
                row.anchor_material_combo.currentText() != "310"
                or row.thread_combo.currentText() != "M10"
                or row.pin_diameter_combo.currentText() != "8"
                or row.hose_combo.currentText() != "32胶管"
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

            row.anchor_check.setChecked(False)
            if not row.anchor_fields.isHidden():
                raise ValueError("取消锚固件后相关选项仍然显示")
            row.anchor_check.setChecked(True)
            diamond_index = row.anchor_type_combo.findData(AnchorType.DIAMOND)
            row.anchor_type_combo.setCurrentIndex(diamond_index)
            if row.embedment_field.isHidden():
                raise ValueError("菱形锚固件未显示嵌入深度")
            m_shape_index = row.anchor_type_combo.findData(AnchorType.M_SHAPE)
            row.anchor_type_combo.setCurrentIndex(m_shape_index)
            if not row.embedment_field.isHidden():
                raise ValueError("非菱形锚固件仍显示嵌入深度")
            trace.write_text("conditional fields passed\n", encoding="utf-8")

            row.module_id_edit.setText("B2X")
            added = window._add_module()
            window._activate_row(row)
            if row.module_id_edit.text() != "B2X":
                raise ValueError("切换模块后编辑内容丢失")
            row.module_id_edit.setText("B2")
            window._activate_row(added)
            window._remove_selected_module()
            if len(window.rows) != 1:
                raise ValueError("添加与删除模块失败")
            trace.write_text("module add/remove passed\n", encoding="utf-8")
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
