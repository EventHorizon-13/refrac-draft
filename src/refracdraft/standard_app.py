from __future__ import annotations

import sys


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from refracdraft.app import _smoke_test
    from refracdraft.domain.models import Project
    from refracdraft.resources import resource_path
    from refracdraft.standard import ensure_standard_project
    from refracdraft.ui.standard_window import StandardWindow

    smoke = "--smoke-test" in sys.argv
    app = QApplication([sys.argv[0]] if smoke else sys.argv)
    app.setApplicationName("RefracDraft Standard")
    window = StandardWindow()
    if smoke:
        try:
            sample = Project.model_validate_json(
                resource_path("examples/b2_positive_tap.json").read_text(encoding="utf-8")
            )
            ensure_standard_project(sample)
            window.project = sample
            window._populate_tables()
            roundtrip = window._collect_project()
            if roundtrip.model_dump(mode="json") != sample.model_dump(mode="json"):
                raise ValueError("分组参数编辑器未完整保留 B2 示例参数")
            original_name = window.fields[("modules", "name")].text(1)
            window.fields[("modules", "name")].setText(1, "切换保留测试")
            window._add_module()
            window.module_list.setCurrentRow(0)
            if window.fields[("modules", "name")].text(1) != "切换保留测试":
                raise ValueError("切换模块后编辑内容丢失")
            window.fields[("modules", "name")].setText(1, original_name)
            window.module_list.setCurrentRow(1)
            window._remove_selected_module()
            if window._collect_project().model_dump(mode="json") != sample.model_dump(mode="json"):
                raise ValueError("添加与删除模块后 B2 参数发生变化")
            window.resize(1500, 900)
            window.show()
            app.processEvents()
            if not window.grab().save("RefracDraft-Standard-layout.png", "PNG"):
                raise ValueError("无法保存标准版界面预览图")
            window.hide()
            _smoke_test(window)
        except Exception:
            from pathlib import Path
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

