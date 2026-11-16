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
                raise ValueError("统一参数表未完整保留 B2 示例参数")
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

