from __future__ import annotations

import sys


def main() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit("桌面界面需要安装 PySide6：pip install 'refrac-draft[ui]' ") from exc
    from refracdraft.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("RefracDraft")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
