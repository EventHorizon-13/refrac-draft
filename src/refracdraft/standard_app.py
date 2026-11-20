from __future__ import annotations

import os
import sys


def main() -> None:
    from pathlib import Path

    from PySide6.QtCore import QEvent, QPointF, QTimer, Qt
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QKeyEvent, QMouseEvent
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget

    from refracdraft.app import _smoke_test
    from refracdraft.domain.models import Project
    from refracdraft.exporters.pdf import _find_pdf_font
    from refracdraft.importers.excel import import_project_xlsx
    from refracdraft.release import build_time_display
    from refracdraft.resources import resource_path
    from refracdraft.standard import ensure_standard_project
    from refracdraft.ui.about import AboutDialog
    from refracdraft.ui.board_face_dialog import BoardFaceDialog
    from refracdraft.ui.standard_window import COLUMN_INDEX, PROFILE_COLUMN, StandardWindow

    smoke = "--smoke-test" in sys.argv
    trace = Path("RefracDraft-Standard-smoke-trace.txt")
    if smoke:
        trace.write_text("start\n", encoding="utf-8")
    app = QApplication([sys.argv[0]] if smoke else sys.argv)
    app.setOrganizationName("EventHorizon")
    app.setApplicationName("RefracDraft Standard")
    app.setWindowIcon(QIcon(str(resource_path("assets/RefracDraft.png"))))
    app_font_path = resource_path("assets/fonts/SourceHanSansSC-Regular.otf")
    if app_font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(app_font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 9))
    window = StandardWindow()
    if smoke:
        trace.write_text("window created\n", encoding="utf-8")
        try:
            if window.windowIcon().pixmap(32, 32).isNull():
                raise ValueError("便携版缺少可加载的程序图标")
            about = AboutDialog(window)
            expected_version = os.environ.get("REFRACDRAFT_EXPECTED_VERSION")
            version_label = about.findChild(QLabel, "versionLabel")
            if expected_version and (version_label is None or f"v{expected_version} " not in version_label.text()):
                raise ValueError("关于窗口没有显示本次构建的版本号")
            build_time = build_time_display()
            build_label = about.findChild(QLabel, "buildTimeLabel")
            if not build_time or build_label is None or build_time not in build_label.text():
                raise ValueError("关于窗口未显示便携版的编译时间")
            about.deleteLater()
            app.sendPostedEvents(about, QEvent.Type.DeferredDelete)
            if _find_pdf_font() != resource_path("assets/fonts/SourceHanSerifSC-Regular.otf"):
                raise ValueError("缺省 PDF 字体未使用随包思源宋体")
            example_excel = import_project_xlsx(resource_path("examples/standard_example_6_modules.xlsx"))
            if len(example_excel.modules) != 6:
                raise ValueError("随包标准版 Excel 示例无法导入六个模块")
            sample = Project.model_validate_json(
                resource_path("examples/b2_positive_tap.json").read_text(encoding="utf-8")
            )
            ensure_standard_project(sample)
            trace.write_text("sample loaded\n", encoding="utf-8")
            window.project = sample
            window._populate_tables()
            window.generate()
            if window._preview_pdf is None:
                raise ValueError("标准版未生成与导出同源的 PDF 预览")
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
                or window._cell_text(row, "taper_type") != "侧敲"
            ):
                raise ValueError("大小头参数未按 B2 示例载入")
            if not window._cell_bool(row, "anchor_enabled"):
                raise ValueError("锚固件参数未按 B2 示例载入")
            if (
                window._cell_text(row, "material") != "1430"
                or window._cell_text(row, "production_quantity") != "26"
            ):
                raise ValueError("模块材质或数量未按 B2 示例载入")
            if window._cell_text(row, "board_material") != "9厘":
                raise ValueError("夹板类型未按 B2 示例载入")
            if (
                window._cell_text(row, "anchor_material") != "310"
                or window._cell_text(row, "thread_spec") != "M10"
                or window._cell_text(row, "pin_diameter_mm") != "8"
                or window._cell_text(row, "hose_spec") != "32"
            ):
                raise ValueError("锚固件材质、螺栓、插针或胶管未按 B2 示例载入")
            if table.item(row, COLUMN_INDEX["anchor_enabled"]).text():
                raise ValueError("锚固件复选框仍显示是/否文字")
            headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
            if any("(" in label or "mm" in label.lower() for label in headers):
                raise ValueError("参数表头仍包含单位")
            if COLUMN_INDEX["density_kg_m3"] > COLUMN_INDEX["production_quantity"]:
                raise ValueError("容重列未放到前面")
            if not (
                window._filename_stem().startswith("模块加工图_")
                and window._filename_stem().endswith("_")
            ):
                raise ValueError("默认文件名规则不正确")
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

            length_cell = table.item(row, COLUMN_INDEX["length_mm"])
            length_cell.setText("301")
            window.undo()
            if window._cell_text(row, "length_mm") != "300":
                raise ValueError("Ctrl+Z 撤销未恢复参数")
            window.redo()
            if window._cell_text(row, "length_mm") != "301":
                raise ValueError("Ctrl+Y 重做未恢复参数")
            table.item(row, COLUMN_INDEX["length_mm"]).setText("300")
            trace.write_text("undo/redo passed\n", encoding="utf-8")

            profile_button = table.cellWidget(row, PROFILE_COLUMN)
            if profile_button is None:
                raise ValueError("参数行缺少异形模块按钮")
            dialog_errors = []

            def edit_board_profile():
                dialog = app.activeModalWidget()
                try:
                    if not isinstance(dialog, BoardFaceDialog):
                        raise ValueError("异形模块按钮未打开编辑窗口")
                    cut = dialog.cuts[0]
                    initial_outline = dialog.preview.outline
                    cut.dimensions["a"].setText("80")
                    cut.rotate.click()
                    cut.mirror.click()
                    if not dialog.confirm.isEnabled() or dialog.preview.outline == initial_outline:
                        raise ValueError("异形夹板面示意图未随切口参数改变")
                    dialog.confirm.click()
                except Exception as exc:
                    dialog_errors.append(exc)
                    if dialog is not None:
                        dialog.reject()

            QTimer.singleShot(0, edit_board_profile)
            profile_button.click()
            if dialog_errors:
                raise dialog_errors[0]
            profile = window._collect_project().modules[0].board_face_outline
            if not profile or profile.features[0].rotation_deg != 90 or not profile.features[0].mirror_x:
                raise ValueError("异形夹板面参数未进入项目数据")
            window.undo()
            if window._collect_project().modules[0].board_face_outline is not None:
                raise ValueError("撤销未清除异形轮廓")
            window.activateWindow()
            app.processEvents()
            trace.write_text("board profile editor passed\n", encoding="utf-8")

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
            table.setFocus()
            table.setCurrentCell(row, length_column)
            QApplication.sendEvent(table, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier
            ))
            if table.currentRow() != added:
                raise ValueError("选中单元格后方向键未切换到下一行")
            table.setCurrentCell(row, length_column)
            QApplication.sendEvent(table, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_4, Qt.KeyboardModifier.NoModifier, "4"
            ))
            editor = table.focusWidget()
            if not isinstance(editor, QLineEdit) or editor.text() != "4":
                raise ValueError("按键未进入编辑并替换原值")
            editor.setText("456")
            QApplication.sendEvent(editor, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
            ))
            if (
                table.currentRow() != added
                or table.currentColumn() != length_column
                or window._cell_text(row, "length_mm") != "456"
            ):
                raise ValueError("回车未提交并切换到同列下一行")
            structure = COLUMN_INDEX["structure_type"]
            table.setFocus(Qt.FocusReason.OtherFocusReason)
            table.setCurrentCell(row, structure)
            app.processEvents()
            center = table.visualRect(table.currentIndex()).center()
            global_center = table.viewport().mapToGlobal(center)
            for event_type, buttons in (
                (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
            ):
                QApplication.sendEvent(table.viewport(), QMouseEvent(
                    event_type, QPointF(center), QPointF(global_center),
                    Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier,
                ))
            if not table._preset_list.isVisible() or not table.hasFocus():
                raise ValueError(
                    f"预设下拉菜单状态错误，visible={table._preset_list.isVisible()}, "
                    f"table_focus={table.hasFocus()}, active_window={window.isActiveWindow()}"
                )
            presets = table._preset_list
            underlay = QWidget(table.viewport())
            underlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            underlay.setGeometry(presets.geometry())
            underlay.show()

            def capture_preset_area(color):
                underlay.setStyleSheet(f"background-color: {color};")
                return table.viewport().grab(presets.geometry()).toImage()

            try:
                presets.hide()
                if capture_preset_area("#ff00ff") == capture_preset_area("#00ffff"):
                    raise ValueError("下拉菜单背景测试无法绘制对比底层")
                presets.show()
                presets.raise_()
                panel = capture_preset_area("#ff00ff")
                if panel != capture_preset_area("#00ffff"):
                    raise ValueError("预设下拉菜单透出了底层表格")
                if panel.pixelColor(panel.width() // 2, 0) != QColor("#5688c7"):
                    raise ValueError("预设下拉菜单的蓝色边框未绘制")
            finally:
                underlay.hide()
                underlay.deleteLater()
                app.sendPostedEvents(underlay, QEvent.Type.DeferredDelete)
            QApplication.sendEvent(table, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
            ))
            if table.currentRow() != added or table.currentColumn() != structure:
                raise ValueError("预设下拉展开时回车未移到同列下一行")
            QApplication.sendEvent(table, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier
            ))
            if table.currentRow() != row or not table._preset_list.isVisible():
                raise ValueError("预设下拉展开时方向键未切换单元格")
            QApplication.sendEvent(table.viewport(), QMouseEvent(
                QEvent.Type.MouseButtonDblClick, QPointF(center), QPointF(global_center),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            ))
            editor = table.focusWidget()
            if not isinstance(editor, QLineEdit) or table._preset_list.isVisible():
                raise ValueError("双击预设单元格未直接进入自定义编辑")
            QApplication.sendEvent(editor, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
            ))
            if window.preview.geometry() != window.preview.parentWidget().rect():
                raise ValueError("预览浮层占用了图纸视口高度")
            trace.write_text("table keyboard editing passed\n", encoding="utf-8")
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
            window.close()
            window.deleteLater()
            app.sendPostedEvents(window, QEvent.Type.DeferredDelete)
            app.setWindowIcon(QIcon())
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
