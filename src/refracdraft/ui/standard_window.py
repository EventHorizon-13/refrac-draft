from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import re

import pymupdf
from PySide6.QtCore import (
    QEvent, QEventLoop, QRect, QRegularExpression, QSettings, QSignalBlocker,
    QStandardPaths, Qt, Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDoubleValidator,
    QImage,
    QIntValidator,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QStyle,
    QStyleOption,
    QStyleOptionButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from refracdraft.domain.models import (
    AnchorParameters,
    AnchorType,
    BoardParameters,
    ModuleParameters,
    Project,
)
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import export_pdf
from refracdraft.release import app_version
from refracdraft.resources import application_directory
from refracdraft.reference.library import ReferenceLibrary
from refracdraft.standard import ensure_standard_project
from refracdraft.standard_sheet import COLUMN_SPECS, DEFAULT_ROW, build_standard_row, row_values_from_models
from refracdraft.ui.about import AboutDialog
from refracdraft.ui.main_window import DrawingPreview, MainWindow, PageSpinBox


@dataclass(frozen=True)
class TableState:
    rows: tuple[dict[str, str | bool], ...]
    bases: tuple[object, ...]


COLUMN_INDEX = {spec.key: index for index, spec in enumerate(COLUMN_SPECS)}
COLUMN_BY_KEY = {spec.key: spec for spec in COLUMN_SPECS}
TAPER_SETTING_KEYS = ("big_head_mm", "small_head_mm", "taper_type")
ANCHOR_SETTING_KEYS = (
    "anchor_position_mm",
    "anchor_spacing_mm",
    "anchor_count",
    "anchor_type",
    "anchor_length_mm",
    "anchor_material",
    "thread_spec",
    "pin_diameter_mm",
    "hose_spec",
    "embedment_depth_mm",
)

def _default_filename_stem() -> str:
    return f"模块加工图_{datetime.now():%m%d}_"


def _short_rule() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedWidth(32)
    line.setFixedHeight(1)
    return line


class OperationProgress(QDialog):
    def __init__(self, parent: QWidget, text: str, steps: int):
        super().__init__(parent)
        self.setWindowTitle("正在处理")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        self.label = QLabel(text)
        self.bar = QProgressBar()
        self.bar.setRange(0, steps)
        self.bar.setValue(0)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        self.show()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def update_stage(self, text: str, completed: int) -> None:
        self.label.setText(text)
        self.bar.setValue(completed)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def advance(self, text: str) -> None:
        self.update_stage(text, self.bar.value() + 1)

    def finish(self, text: str) -> None:
        self.update_stage(text, self.bar.maximum())


def _preset_button_rect(cell_rect: QRect) -> QRect:
    return QRect(cell_rect.right() - 15, cell_rect.top(), 16, cell_rect.height() - 7)


class ParameterDelegate(QStyledItemDelegate):
    """Editable preset editor used by the spreadsheet-style module table."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

    def createEditor(self, parent: QWidget, option, index):
        spec = COLUMN_SPECS[index.column()]
        if spec.kind == "check":
            return None
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setMaxLength(180)
        editor.setAutoFillBackground(True)
        editor.setStyleSheet(
            "QLineEdit { background: palette(base); color: palette(text);"
            " border: 1px solid #3b82f6; padding: 0 4px;"
            " selection-background-color: #3b82f6; selection-color: white; }"
        )
        if spec.kind == "number":
            validator = QDoubleValidator(0.0, 1_000_000.0, 2, editor)
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            editor.setValidator(validator)
        elif spec.kind == "integer":
            validator = QIntValidator(0, 1_000_000, editor)
            editor.setValidator(validator)
        elif spec.kind == "enum" and "自定义" not in spec.options:
            choices = QRegularExpression("|".join(QRegularExpression.escape(value) for value in spec.options))
            editor.setValidator(QRegularExpressionValidator(choices, editor))
        return editor

    def eventFilter(self, editor, event) -> bool:
        if (
            isinstance(editor, QLineEdit)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            if editor.hasAcceptableInput():
                self.parent()._commit_and_move_down(editor)
            return True
        return super().eventFilter(editor, event)

    def setEditorData(self, editor, index) -> None:
        value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if isinstance(editor, QLineEdit):
            editor.setText(str(value))
            editor.selectAll()

    def setModelData(self, editor, model, index) -> None:
        if isinstance(editor, QLineEdit):
            model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect)

    def paint(self, painter, option, index):
        spec = COLUMN_SPECS[index.column()]
        item = self.parent().item(index.row(), index.column())
        background = (
            option.palette.alternateBase()
            if index.row() % 2
            else option.palette.base()
        )
        if option.state & QStyle.StateFlag.State_Selected:
            background = option.palette.highlight()
        if item is not None and not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            painter.fillRect(option.rect, background)
            return
        if spec.kind == "check":
            painter.save()
            painter.fillRect(option.rect, background)
            control = QStyleOptionButton()
            control.initFrom(self.parent())
            control.rect = QRect(
                option.rect.center().x() - 8,
                option.rect.center().y() - 8,
                16,
                16,
            )
            control.state = QStyle.StateFlag.State_Enabled | (
                QStyle.StateFlag.State_On
                if item is not None and item.checkState() == Qt.CheckState.Checked
                else QStyle.StateFlag.State_Off
            )
            self.parent().style().drawControl(
                QStyle.ControlElement.CE_CheckBox,
                control,
                painter,
                self.parent(),
            )
            painter.restore()
            return
        super().paint(painter, option, index)
        if spec.options:
            button = QStyleOption()
            button.initFrom(self.parent())
            button.rect = _preset_button_rect(option.rect).adjusted(4, 0, -4, 0)
            self.parent().style().drawPrimitive(
                QStyle.PrimitiveElement.PE_IndicatorArrowDown, button, painter, self.parent()
            )


class ParameterTable(QTableWidget):
    """QTableWidget with an Excel-style fill handle and multi-cell paste."""

    changed = Signal()
    rowsRequired = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(0, len(COLUMN_SPECS), parent)
        self._fill_source: tuple[int, int, int, int] | None = None
        self._fill_target: tuple[int, int] | None = None
        self._fill_dragging = False
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._preset_list = QListWidget(self.viewport())
        self._preset_list.setObjectName("parameterPresetList")
        self._preset_list.viewport().setAutoFillBackground(True)
        self._preset_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preset_list.setMouseTracking(True)
        self._preset_list.hide()
        self._preset_list.itemClicked.connect(self._select_preset)
        self.currentCellChanged.connect(self._preset_list.hide)
        self.horizontalScrollBar().valueChanged.connect(self._preset_list.hide)
        self.verticalScrollBar().valueChanged.connect(self._preset_list.hide)

    def _visible_selected_range(self) -> tuple[int, int, int, int] | None:
        indexes = [index for index in self.selectionModel().selectedIndexes()
                   if not self.isColumnHidden(index.column())]
        if not indexes:
            return None
        rows = [index.row() for index in indexes]
        columns = [index.column() for index in indexes]
        return min(rows), min(columns), max(rows), max(columns)

    def _handle_rect(self) -> QRect:
        selected = self._visible_selected_range()
        if selected is None:
            return QRect()
        top, left, bottom, right = selected
        corner = self.visualRect(self.model().index(bottom, right))
        return QRect(corner.right() - 5, corner.bottom() - 5, 6, 6)

    def _edit_cell(self, row: int, column: int) -> None:
        self._preset_list.hide()
        index = self.model().index(row, column)
        if index.isValid():
            self.setCurrentIndex(index)
            self.edit(index)

    def _move_current_cell(self, row_step: int, column_step: int) -> None:
        self._preset_list.hide()
        row = self.currentRow()
        column = self.currentColumn()
        if row < 0 or column < 0:
            return
        row += row_step
        column += column_step
        while 0 <= row < self.rowCount() and 0 <= column < self.columnCount():
            item = self.item(row, column)
            if (
                not self.isRowHidden(row)
                and not self.isColumnHidden(column)
                and item is not None
                and item.flags() & Qt.ItemFlag.ItemIsEnabled
            ):
                self.clearSelection()
                self.setCurrentCell(row, column)
                self.setFocus()
                self._show_cell_menu(row, column)
                return
            row += row_step
            column += column_step

    def _commit_and_move_down(self, editor: QLineEdit) -> None:
        self.commitData(editor)
        self.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        self._move_current_cell(1, 0)

    def _show_cell_menu(self, row: int, column: int) -> None:
        self._preset_list.hide()
        item = self.item(row, column)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        spec = COLUMN_SPECS[column]
        if not spec.options:
            return
        choices = self._preset_list
        choices.clear()
        current = item.text().strip()
        for option in spec.options:
            if option == "自定义":
                continue
            entry = QListWidgetItem(option, choices)
            entry.setData(Qt.ItemDataRole.UserRole, option)
            if current == option:
                choices.setCurrentItem(entry)
        if spec.kind != "enum" or "自定义" in spec.options:
            QListWidgetItem("自定义…", choices)
        rect = self.visualRect(self.model().index(row, column))
        viewport = self.viewport()
        width = min(viewport.width(), max(rect.width(), choices.sizeHintForColumn(0) + 32))
        desired_height = choices.sizeHintForRow(0) * choices.count() + 2 * choices.frameWidth()
        below = viewport.height() - rect.bottom() - 1
        above = rect.top()
        height = min(desired_height, max(above, below))
        if height <= 0:
            return
        left = max(0, min(rect.left(), viewport.width() - width))
        top = rect.bottom() + 1 if below >= height else above - height
        choices.setGeometry(left, top, width, height)
        choices.show()
        choices.raise_()

    def _select_preset(self, entry: QListWidgetItem) -> None:
        value = entry.data(Qt.ItemDataRole.UserRole)
        self._preset_list.hide()
        row, column = self.currentRow(), self.currentColumn()
        item = self.item(row, column)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        if value is None:
            self._edit_cell(row, column)
        else:
            item.setText(value)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._fill_dragging and self._fill_source and self._fill_target:
            row, column = self._fill_target
            top, left, bottom, right = self._fill_source
            bounds = (min(top, row), min(left, column), max(bottom, row), max(right, column))
            start = self.visualRect(self.model().index(bounds[0], bounds[1]))
            end = self.visualRect(self.model().index(bounds[2], bounds[3]))
            if start.isValid() and end.isValid():
                painter = QPainter(self.viewport())
                painter.setPen(QPen(QColor("#3b82f6"), 1.0, Qt.PenStyle.DashLine))
                painter.setBrush(QColor(59, 130, 246, 32))
                painter.drawRect(QRect(start.topLeft(), end.bottomRight()))
                painter.end()
        selected = self._visible_selected_range()
        if selected is None:
            return
        handle = self._handle_rect()
        if not handle.isEmpty():
            painter = QPainter(self.viewport())
            painter.fillRect(handle, QColor("#3b82f6"))
            painter.setPen(QPen(QColor("#ffffff"), 1.0))
            painter.drawRect(handle.adjusted(0, 0, -1, -1))
            painter.end()

    def mousePressEvent(self, event) -> None:
        self._preset_list.hide()
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            target = self.indexAt(position)
            handle = self._handle_rect()
            if not handle.isEmpty() and handle.contains(position):
                self._fill_source = self._visible_selected_range()
                self._fill_target = (target.row(), target.column()) if target.isValid() else None
                self._fill_dragging = self._fill_source is not None
                self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
                event.accept()
                return
            if target.isValid():
                item = self.item(target.row(), target.column())
                spec = COLUMN_SPECS[target.column()]
                if item is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled and spec.kind == "check":
                    self.setCurrentCell(target.row(), target.column())
                    next_state = (
                        Qt.CheckState.Unchecked
                        if item.checkState() == Qt.CheckState.Checked
                        else Qt.CheckState.Checked
                    )
                    item.setCheckState(next_state)
                    event.accept()
                    return
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if target.isValid() and target == self.currentIndex():
                self._show_cell_menu(target.row(), target.column())

    def mouseDoubleClickEvent(self, event) -> None:
        target = self.indexAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and target.isValid():
            spec = COLUMN_SPECS[target.column()]
            item = self.item(target.row(), target.column())
            if spec.options and item is not None and item.flags() & Qt.ItemFlag.ItemIsEditable:
                self._edit_cell(target.row(), target.column())
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event) -> None:
        self._preset_list.hide()
        super().focusOutEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._fill_dragging:
            target = self.indexAt(event.position().toPoint())
            if target.isValid() and not self.isColumnHidden(target.column()):
                self._fill_target = (target.row(), target.column())
                self.viewport().update()
            event.accept()
            return
        if self._handle_rect().adjusted(-2, -2, 2, 2).contains(event.position().toPoint()):
            self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._fill_dragging and event.button() == Qt.MouseButton.LeftButton:
            if self._fill_source and self._fill_target:
                target = self.indexAt(event.position().toPoint())
                if target.isValid():
                    self._fill_target = (target.row(), target.column())
                    self._apply_fill(self._fill_source, self._fill_target)
            self._fill_dragging = False
            self._fill_source = None
            self._fill_target = None
            self.viewport().unsetCursor()
            self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _copy_item(self, target: QTableWidgetItem, source: QTableWidgetItem) -> None:
        target.setText(source.text())
        if source.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            target.setCheckState(source.checkState())

    def _apply_fill(self, source: tuple[int, int, int, int],
                    target: tuple[int, int]) -> None:
        top, left, bottom, right = source
        target_row, target_column = target
        target_bounds = (
            min(top, target_row),
            min(left, target_column),
            max(bottom, target_row),
            max(right, target_column),
        )
        if target_bounds == source:
            return
        source_height = bottom - top + 1
        source_width = right - left + 1
        self.blockSignals(True)
        try:
            for row in range(target_bounds[0], target_bounds[2] + 1):
                for column in range(target_bounds[1], target_bounds[3] + 1):
                    if top <= row <= bottom and left <= column <= right:
                        continue
                    if self.isColumnHidden(column):
                        continue
                    source_row = top + (row - top) % source_height
                    source_column = left + (column - left) % source_width
                    source_item = self.item(source_row, source_column)
                    target_item = self.item(row, column)
                    if source_item is not None and target_item is not None:
                        self._copy_item(target_item, source_item)
        finally:
            self.blockSignals(False)
        self.setCurrentCell(target_bounds[2], target_bounds[3])
        self.changed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._move_current_cell(1, 0)
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_Down
            and event.modifiers() == Qt.KeyboardModifier.AltModifier
            and self.currentIndex().isValid()
        ):
            self._show_cell_menu(self.currentRow(), self.currentColumn())
            event.accept()
            return
        self._preset_list.hide()
        directions = {
            Qt.Key.Key_Left: (0, -1),
            Qt.Key.Key_Right: (0, 1),
            Qt.Key.Key_Up: (-1, 0),
            Qt.Key.Key_Down: (1, 0),
        }
        if (
            event.key() in directions
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self.state() != QAbstractItemView.State.EditingState
        ):
            row_step, column_step = directions[event.key()]
            self._move_current_cell(row_step, column_step)
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_clipboard()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Delete):
            self._clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _clear_selection(self) -> None:
        self.blockSignals(True)
        try:
            for index in self.selectionModel().selectedIndexes():
                item = self.item(index.row(), index.column())
                if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    continue
                item.setText("")
        finally:
            self.blockSignals(False)
        self.changed.emit()

    def _paste_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        rows = text.replace("\r", "").split("\n")
        if rows and rows[-1] == "":
            rows.pop()
        matrix = [row.split("\t") for row in rows]
        if not matrix:
            return
        start_row = max(0, self.currentRow())
        start_column = max(0, self.currentColumn())
        while start_column < self.columnCount() and self.isColumnHidden(start_column):
            start_column += 1
        if start_column >= self.columnCount():
            return
        missing_rows = start_row + len(matrix) - self.rowCount()
        if missing_rows > 0:
            self.rowsRequired.emit(missing_rows)
        self.blockSignals(True)
        try:
            for row_offset, values in enumerate(matrix):
                row = start_row + row_offset
                if row >= self.rowCount():
                    break
                visible_columns = [
                    column
                    for column in range(start_column, self.columnCount())
                    if not self.isColumnHidden(column)
                ]
                all_columns = list(range(start_column, self.columnCount()))
                columns = all_columns if len(values) > len(visible_columns) else visible_columns
                column_index = 0
                for value in values:
                    if column_index >= len(columns):
                        break
                    column = columns[column_index]
                    item = self.item(row, column)
                    if item is not None:
                        spec = COLUMN_SPECS[column]
                        if spec.kind == "check":
                            checked = value.strip().lower() in {"1", "是", "yes", "true", "y"}
                            item.setCheckState(
                                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                            )
                            item.setText("")
                        elif item.flags() & Qt.ItemFlag.ItemIsEditable:
                            item.setText(value.strip())
                    column_index += 1
        finally:
            self.blockSignals(False)
        self.changed.emit()


class StandardWindow(MainWindow):
    def __init__(self):
        self._preview_pdf: tuple[str | None, bytes] | None = None
        self._settings = QSettings("EventHorizon", "RefracDraft Standard")
        self._history_ready = False
        self._history_restoring = False
        self._undo_stack: list[TableState] = []
        self._redo_stack: list[TableState] = []
        self._history_state: TableState | None = None
        super().__init__()
        self._history_ready = True
        self._reset_history()
        self.setWindowTitle(f"RefracDraft Standard v{app_version()} — 模块加工图生成器")
        self.statusBar().showMessage("修改参数后点击「预览」；可拖动选区右下角批量填充。")

    def _build_ui(self) -> None:
        self._row_bases: list[
            tuple[ModuleParameters | None, BoardParameters | None, AnchorParameters | None]
        ] = []
        self._updating_table = False

        toolbar = QToolBar("主工具栏")
        self.addToolBar(toolbar)
        for label, callback, shortcut in (
            ("新建", self.new_project, "Ctrl+N"),
            ("打开", self.open_json, "Ctrl+O"),
            ("导入 Excel", self.import_excel, "Ctrl+I"),
            ("保存", self.save_json, "Ctrl+S"),
        ):
            action = QAction(label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            toolbar.addAction(action)
        toolbar.addSeparator()
        generate_action = QAction("预览", self)
        generate_action.setShortcut(QKeySequence("F5"))
        generate_action.triggered.connect(self.generate)
        toolbar.addAction(generate_action)
        self.undo_action = QAction("撤销", self)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.undo_action.triggered.connect(self.undo)
        toolbar.addAction(self.undo_action)
        self.redo_action = QAction("重做", self)
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.redo_action.triggered.connect(self.redo)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        about = QAction("关于", self)
        about.triggered.connect(self._show_about)
        toolbar.addAction(about)

        splitter = QSplitter(Qt.Orientation.Vertical)

        parameter_panel = QWidget()
        parameter_layout = QVBoxLayout(parameter_panel)
        parameter_layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        title = QLabel("模块参数")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        add_button = QPushButton("添加模块")
        remove_button = QPushButton("删除模块")
        add_button.clicked.connect(lambda _checked=False: self._add_module())
        remove_button.clicked.connect(lambda _checked=False: self._remove_selected_module())
        header.addWidget(add_button)
        header.addWidget(remove_button)
        self.row_count_label = QLabel("0 个模块")
        header.addWidget(self.row_count_label)
        header.addStretch(1)
        parameter_layout.addLayout(header)

        self.parameter_table = ParameterTable()
        self.module_table = self.parameter_table
        self.tables = {"modules": self.parameter_table}
        table = self.parameter_table
        table.setObjectName("moduleParameterTable")
        table.setHorizontalHeaderLabels([spec.label for spec in COLUMN_SPECS])
        table.setItemDelegate(ParameterDelegate(table))
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setShowGrid(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.AnyKeyPressed)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setMinimumSectionSize(44)
        table.verticalHeader().setDefaultSectionSize(31)
        table.verticalHeader().setMinimumWidth(34)
        table.setMinimumHeight(185)
        for column, spec in enumerate(COLUMN_SPECS):
            table.setColumnWidth(column, spec.width)
            header_item = table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(spec.label)
                header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.horizontalHeader().sectionDoubleClicked.connect(self._edit_whole_column)
        table.itemChanged.connect(self._table_item_changed)
        table.currentCellChanged.connect(self._current_cell_changed)
        table.changed.connect(self._table_bulk_changed)
        table.rowsRequired.connect(self._ensure_row_count)
        parameter_layout.addWidget(table)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_splitter = QSplitter(Qt.Orientation.Horizontal)

        output_panel = QFrame()
        output_panel.setObjectName("outputPanel")
        output_panel.setMinimumWidth(245)
        output_panel.setMaximumWidth(365)
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(12, 10, 12, 10)
        output_layout.setSpacing(7)
        output_title = QLabel("输出设置")
        output_title.setStyleSheet("font-weight: 600;")
        output_layout.addWidget(output_title)
        output_layout.addWidget(_short_rule())

        output_layout.addWidget(QLabel("工作目录"))
        directory_row = QHBoxLayout()
        self.output_directory_edit = QLineEdit()
        self.output_directory_edit.setPlaceholderText("选择保存目录")
        self.working_directory_edit = self.output_directory_edit
        self.browse_directory_button = QPushButton("选择")
        self.browse_directory_button.setFixedWidth(58)
        self.browse_directory_button.clicked.connect(self._choose_output_directory)
        directory_row.addWidget(self.output_directory_edit, 1)
        directory_row.addWidget(self.browse_directory_button)
        output_layout.addLayout(directory_row)

        output_layout.addWidget(QLabel("自定义文件名"))
        self.output_filename_edit = QLineEdit(_default_filename_stem())
        self.output_filename_edit.setPlaceholderText("不含扩展名")
        output_layout.addWidget(self.output_filename_edit)

        self.output_path_label = QLabel()
        self.output_path_label.setProperty("role", "fieldLabel")
        self.output_path_label.setWordWrap(True)
        output_layout.addWidget(self.output_path_label)
        output_layout.addStretch(1)

        self.preview_button = QPushButton("预览")
        self.preview_button.setProperty("primary", True)
        self.preview_button.clicked.connect(self.generate)
        output_layout.addWidget(self.preview_button)

        self.output_dxf_button = QPushButton("导出 DXF")
        self.output_pdf_button = QPushButton("导出 PDF")
        self.output_dxf_button.setProperty("primary", True)
        self.output_pdf_button.setProperty("primary", True)
        self.output_dxf_button.clicked.connect(self.export_dxf_file)
        self.output_pdf_button.clicked.connect(self.export_pdf_file)
        output_layout.addWidget(self.output_dxf_button)
        output_layout.addWidget(self.output_pdf_button)

        preview_canvas = QWidget()
        canvas_layout = QGridLayout(preview_canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = DrawingPreview()
        self.preview.page_step_requested.connect(self._preview_page_step)
        self.preview.zoom_requested.connect(self._preview_zoom)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        canvas_layout.addWidget(self.preview, 0, 0)

        preview_title = QLabel("图纸预览")
        preview_title.setObjectName("previewTitle")
        preview_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        canvas_layout.addWidget(
            preview_title, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        page_controls = QFrame()
        page_controls.setObjectName("previewPageControls")
        page_row = QHBoxLayout(page_controls)
        page_row.setContentsMargins(9, 5, 9, 5)
        page_row.addWidget(QLabel("预览页"))
        self.page_spin = PageSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._show_selected_page)
        page_row.addWidget(self.page_spin)
        canvas_layout.addWidget(
            page_controls, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )

        preview_splitter.addWidget(output_panel)
        preview_splitter.addWidget(preview_canvas)
        preview_splitter.setStretchFactor(0, 0)
        preview_splitter.setStretchFactor(1, 1)
        preview_splitter.setSizes([280, 1040])
        preview_layout.addWidget(preview_splitter)

        splitter.addWidget(parameter_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 570])
        self.setCentralWidget(splitter)

        remembered_directory = str(self._settings.value("output/last_directory", ""))
        preferred_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        output_directory = (
            remembered_directory
            if remembered_directory and Path(remembered_directory).expanduser().is_dir()
            else preferred_directory or str(Path.cwd())
        )
        self.output_directory_edit.setText(output_directory)
        self.output_directory_edit.textChanged.connect(self._update_output_preview)
        self.output_filename_edit.textChanged.connect(self._update_output_preview)
        self.output_directory_edit.editingFinished.connect(self._save_output_settings)
        self._update_output_preview()

        self.setStyleSheet(
            "QTableWidget#moduleParameterTable {"
            " gridline-color: palette(mid); alternate-background-color: palette(alternate-base); }"
            "QTableWidget#moduleParameterTable QHeaderView::section {"
            " padding: 4px 6px; background-color: palette(button); color: palette(button-text);"
            " border: 0; border-right: 1px solid palette(mid); border-bottom: 1px solid palette(mid); }"
            "QFrame#outputPanel { border: 1px solid palette(mid); border-radius: 4px; }"
            "QLabel#previewTitle, QFrame#previewPageControls {"
            " background: palette(window); color: palette(window-text);"
            " border: 1px solid palette(mid); border-radius: 4px; margin: 5px; }"
            "QLabel#previewTitle { padding: 4px 7px; }"
            "QListWidget#parameterPresetList {"
            " background-color: palette(base); color: palette(text);"
            " border: 2px solid #5688c7; }"
            "QListWidget#parameterPresetList::item {"
            " background-color: palette(base); color: palette(text); padding: 4px 7px; }"
            "QListWidget#parameterPresetList::item:hover, QListWidget#parameterPresetList::item:selected {"
            " background: palette(highlight); color: palette(highlighted-text); }"
            "QPushButton[primary='true'] { background: #2f6fde; color: white;"
            " border: 1px solid #245bb8; border-radius: 4px; padding: 6px 10px; }"
            "QPushButton[primary='true']:hover { background: #3b7bea; }"
            "QLabel[role='fieldLabel'] { font-size: 11px; color: palette(mid); }"
        )

    def _add_empty_rows(self) -> None:
        self._add_module()

    def _show_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def _default_output_directory(self) -> Path:
        text = self.output_directory_edit.text().strip() if hasattr(self, "output_directory_edit") else ""
        if text:
            return Path(text).expanduser()
        return Path.cwd()

    def _choose_output_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择输出工作目录",
            str(self._default_output_directory()),
        )
        if directory:
            self.output_directory_edit.setText(directory)
            self._save_output_settings()

    def _save_output_settings(self, *_args) -> None:
        if not hasattr(self, "output_directory_edit"):
            return
        self._settings.setValue(
            "output/last_directory", self.output_directory_edit.text().strip()
        )

    def closeEvent(self, event) -> None:
        self._save_output_settings()
        super().closeEvent(event)

    def _filename_stem(self) -> str:
        value = self.output_filename_edit.text().strip() if hasattr(self, "output_filename_edit") else ""
        if value.lower().endswith((".dxf", ".pdf")):
            value = Path(value).stem
        value = re.sub(r'[<>:"/\\|?*]+', "-", value).strip(" .")
        return value or _default_filename_stem()

    def _update_output_preview(self, *_args) -> None:
        if not hasattr(self, "output_path_label"):
            return
        directory = self.output_directory_edit.text().strip() or "当前工作目录"
        stem = self._filename_stem()
        self.output_path_label.setText(f"{directory}\n{stem}.dxf  /  {stem}.pdf")

    def _output_target(self, suffix: str) -> Path | None:
        self._save_output_settings()
        directory_text = self.output_directory_edit.text().strip()
        if not directory_text:
            path, _ = QFileDialog.getSaveFileName(
                self,
                f"导出 {suffix.removeprefix('.').upper()}",
                f"{self._filename_stem()}{suffix}",
                f"{suffix.removeprefix('.').upper()} 文件 (*{suffix})",
            )
            return Path(path) if path else None
        directory = Path(directory_text).expanduser()
        target = directory / f"{self._filename_stem()}{suffix}"
        if target.exists():
            answer = QMessageBox.question(
                self,
                "覆盖文件",
                f"文件已存在，是否覆盖？\n{target}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
        return target

    @property
    def rows(self) -> list[int]:
        return list(range(self.parameter_table.rowCount()))

    def _next_unique_module_id(self, base: str, used: set[str]) -> str:
        match = re.match(r"^(.*?)(\d+)$", base.strip())
        if match:
            prefix, number_text = match.groups()
            number = int(number_text)
            width = len(number_text)
            while True:
                number += 1
                candidate = f"{prefix}{number:0{width}d}"
                if candidate not in used:
                    return candidate
        candidate = f"{base}-2"
        index = 2
        while candidate in used:
            index += 1
            candidate = f"{base}-{index}"
        return candidate

    def _write_row(self, row: int, values: dict[str, str | bool]) -> None:
        table = self.parameter_table
        for column, spec in enumerate(COLUMN_SPECS):
            value = values.get(spec.key, DEFAULT_ROW.get(spec.key, ""))
            item = QTableWidgetItem()
            if spec.kind == "check":
                if isinstance(value, str):
                    checked = value.strip().lower() in {"1", "是", "yes", "true", "y"}
                else:
                    checked = bool(value)
                item.setText("")
                item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                item.setText("" if value is None else str(value))
                item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsEditable
                )
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, column, item)

    def _sheet_values(self, row: int) -> dict[str, str | bool]:
        values: dict[str, str | bool] = {}
        for column, spec in enumerate(COLUMN_SPECS):
            item = self.parameter_table.item(row, column)
            if item is None:
                values[spec.key] = False if spec.kind == "check" else ""
            elif spec.kind == "check":
                values[spec.key] = item.checkState() == Qt.CheckState.Checked
            else:
                values[spec.key] = item.text().strip()
        return values

    def _add_module(
        self,
        source: tuple[ModuleParameters, BoardParameters, AnchorParameters] | None = None,
    ) -> int:
        table = self.parameter_table
        base: tuple[ModuleParameters | None, BoardParameters | None, AnchorParameters | None]
        if source is not None:
            module, board, anchor = source
            values = row_values_from_models(module, board, anchor)
            base = source
        elif table.rowCount():
            values = self._sheet_values(table.rowCount() - 1)
            used = {
                str(self._sheet_values(row).get("module_id", "")).strip()
                for row in range(table.rowCount())
            }
            base_id = str(values.get("module_id", "M1")).strip() or "M1"
            values["module_id"] = self._next_unique_module_id(base_id, used)
            base = (None, None, None)
        else:
            values = dict(DEFAULT_ROW)
            base = (None, None, None)

        row = table.rowCount()
        self._updating_table = True
        table.blockSignals(True)
        try:
            table.insertRow(row)
            self._write_row(row, values)
            self._row_bases.append(base)
        finally:
            table.blockSignals(False)
            self._updating_table = False
        self._update_row_count()
        self._update_conditional_states()
        table.clearSelection()
        table.setCurrentCell(row, 0)
        self._record_history()
        return row

    def _ensure_row_count(self, extra: int) -> None:
        for _ in range(max(0, int(extra))):
            self._add_module()

    def _remove_selected_module(self) -> None:
        table = self.parameter_table
        rows = sorted({index.row() for index in table.selectionModel().selectedIndexes()}, reverse=True)
        if not rows:
            current = table.currentRow()
            if current >= 0:
                rows = [current]
        if not rows:
            return
        table.blockSignals(True)
        try:
            for row in rows:
                table.removeRow(row)
                if 0 <= row < len(self._row_bases):
                    self._row_bases.pop(row)
        finally:
            table.blockSignals(False)
        if table.rowCount() == 0:
            self._add_module()
        else:
            table.clearSelection()
            table.setCurrentCell(min(rows[-1], table.rowCount() - 1), 0)
        self._update_row_count()
        self._update_conditional_states()
        self._record_history()

    def _update_row_count(self) -> None:
        count = self.parameter_table.rowCount()
        self.row_count_label.setText(f"{count} 个模块")

    def _clear_rows(self) -> None:
        self.parameter_table.blockSignals(True)
        try:
            self.parameter_table.setRowCount(0)
            self._row_bases.clear()
        finally:
            self.parameter_table.blockSignals(False)
        self._update_row_count()
        self._update_conditional_states()

    def _set_cell_text(self, row: int, key: str, text: str) -> None:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        if item is not None:
            item.setText(text)

    def _cell_text(self, row: int, key: str) -> str:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        return item.text().strip() if item is not None else ""

    def _cell_bool(self, row: int, key: str) -> bool:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def _sync_expansion_length(self, row: int) -> None:
        if self._cell_bool(row, "taper_enabled"):
            big = self._cell_text(row, "big_head_mm")
            if big:
                self._set_cell_text(row, "expansion_length_mm", big)

    def _set_cell_enabled(self, row: int, key: str, enabled: bool) -> None:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        if item is None:
            return
        flags = item.flags()
        if enabled:
            flags |= Qt.ItemFlag.ItemIsEnabled
            if COLUMN_BY_KEY[key].kind != "check":
                flags |= Qt.ItemFlag.ItemIsEditable
        else:
            flags &= ~Qt.ItemFlag.ItemIsEnabled
            flags &= ~Qt.ItemFlag.ItemIsEditable
        item.setFlags(flags)

    def _update_conditional_states(self) -> None:
        table = self.parameter_table
        if table.rowCount() == 0:
            for key in ANCHOR_SETTING_KEYS:
                table.setColumnHidden(COLUMN_INDEX[key], True)
            return
        any_anchor = any(self._cell_bool(row, "anchor_enabled") for row in range(table.rowCount()))
        any_diamond = any(
            self._cell_bool(row, "anchor_enabled") and self._cell_text(row, "anchor_type") == "菱形"
            for row in range(table.rowCount())
        )
        any_pin_anchor = any(
            self._cell_bool(row, "anchor_enabled") and self._cell_text(row, "anchor_type") != "菱形"
            for row in range(table.rowCount())
        )
        for key in ANCHOR_SETTING_KEYS:
            table.setColumnHidden(COLUMN_INDEX[key], not any_anchor)
        table.setColumnHidden(COLUMN_INDEX["embedment_depth_mm"], not any_diamond)
        table.setColumnHidden(COLUMN_INDEX["pin_diameter_mm"], not any_pin_anchor)

        was_updating = self._updating_table
        self._updating_table = True
        try:
            for row in range(table.rowCount()):
                taper = self._cell_bool(row, "taper_enabled")
                board = self._cell_bool(row, "board_exists")
                anchor = self._cell_bool(row, "anchor_enabled")
                is_diamond = self._cell_text(row, "anchor_type") == "菱形"
                self._set_cell_enabled(row, "expansion_length_mm", not taper)
                for key in TAPER_SETTING_KEYS:
                    self._set_cell_enabled(row, key, taper)
                self._set_cell_enabled(row, "board_material", board)
                for key in ANCHOR_SETTING_KEYS:
                    enabled = anchor and not (key == "pin_diameter_mm" and is_diamond)
                    enabled = enabled and not (key == "embedment_depth_mm" and not is_diamond)
                    self._set_cell_enabled(row, key, enabled)
                if taper:
                    self._sync_expansion_length(row)
        finally:
            self._updating_table = was_updating

    def _capture_table_state(self) -> TableState:
        rows = tuple(self._sheet_values(row) for row in range(self.parameter_table.rowCount()))
        bases = list(self._row_bases[: self.parameter_table.rowCount()])
        while len(bases) < len(rows):
            bases.append((None, None, None))
        return TableState(rows=rows, bases=tuple(bases))

    def _reset_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_state = self._capture_table_state()
        self._refresh_history_actions()

    def _record_history(self) -> None:
        if not self._history_ready or self._history_restoring:
            return
        current = self._capture_table_state()
        if self._history_state is None:
            self._history_state = current
            return
        if current == self._history_state:
            return
        self._undo_stack.append(self._history_state)
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._history_state = current
        self._refresh_history_actions()

    def _refresh_history_actions(self) -> None:
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(bool(self._undo_stack))
        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(bool(self._redo_stack))

    def _restore_table_state(self, state: TableState) -> None:
        table = self.parameter_table
        self._history_restoring = True
        self._updating_table = True
        table.blockSignals(True)
        try:
            table.setRowCount(0)
            self._row_bases.clear()
            for row, values in enumerate(state.rows):
                table.insertRow(row)
                self._write_row(row, values)
                base = state.bases[row] if row < len(state.bases) else (None, None, None)
                self._row_bases.append(base)
        finally:
            table.blockSignals(False)
            self._updating_table = False
            self._history_restoring = False
        self._update_row_count()
        self._update_conditional_states()
        self._history_state = state
        self._refresh_history_actions()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        current = self._capture_table_state()
        previous = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_table_state(previous)
        self.statusBar().showMessage("已撤销参数修改。")

    def redo(self) -> None:
        if not self._redo_stack:
            return
        current = self._capture_table_state()
        following = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_table_state(following)
        self.statusBar().showMessage("已重做参数修改。")

    def _edit_whole_column(self, column: int) -> None:
        if column < 0 or column >= len(COLUMN_SPECS):
            return
        table = self.parameter_table
        if table.isColumnHidden(column) or table.rowCount() == 0:
            return
        spec = COLUMN_SPECS[column]
        if spec.kind == "check":
            items = [table.item(row, column) for row in range(table.rowCount())]
            target = not all(
                item is not None and item.checkState() == Qt.CheckState.Checked
                for item in items
            )
            table.blockSignals(True)
            try:
                for item in items:
                    if item is None:
                        continue
                    item.setCheckState(
                        Qt.CheckState.Checked if target else Qt.CheckState.Unchecked
                    )
                    item.setText("")
            finally:
                table.blockSignals(False)
            self._table_bulk_changed()
            return

        dialog = QInputDialog(self)
        dialog.setWindowTitle(f"修改整列 - {spec.label}")
        hint = "，".join(spec.options) if spec.options else "输入任意自定义内容"
        dialog.setLabelText(f"将第 {column + 1} 列设置为：\n{hint}")
        if spec.options:
            dialog.setComboBoxItems(list(spec.options))
            dialog.setComboBoxEditable(True)
        table.blockSignals(True)
        try:
            values = {
                table.item(row, column).text().strip()
                for row in range(table.rowCount())
                if table.item(row, column) is not None
            }
        finally:
            table.blockSignals(False)
        if len(values) == 1:
            dialog.setTextValue(next(iter(values)))
        if dialog.exec() != QInputDialog.DialogCode.Accepted:
            return
        value = dialog.textValue().strip()
        if not value:
            return
        table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                item = table.item(row, column)
                if item is not None:
                    item.setText(value)
        finally:
            table.blockSignals(False)
        self._table_bulk_changed()

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.row() >= len(self._row_bases):
            return
        spec = COLUMN_SPECS[item.column()]
        self._updating_table = True
        try:
            if spec.kind == "check":
                checked = item.checkState() == Qt.CheckState.Checked
                item.setText("")
            if spec.key in {"taper_enabled", "big_head_mm"}:
                self._sync_expansion_length(item.row())
        finally:
            self._updating_table = False
        self._update_conditional_states()
        self._record_history()
        self.statusBar().showMessage("参数已修改，点击「预览」更新图纸。")

    def _table_bulk_changed(self) -> None:
        if self._updating_table:
            return
        self._updating_table = True
        try:
            self._ensure_unique_module_ids()
        finally:
            self._updating_table = False
        self._update_row_count()
        self._update_conditional_states()
        self._record_history()
        self.statusBar().showMessage("参数已修改，点击「预览」更新图纸。")

    def _ensure_unique_module_ids(self) -> None:
        used: set[str] = set()
        for row in range(self.parameter_table.rowCount()):
            module_id = self._cell_text(row, "module_id") or "M1"
            if module_id in used:
                module_id = self._next_unique_module_id(module_id, used)
                item = self.parameter_table.item(row, COLUMN_INDEX["module_id"])
                if item is not None:
                    item.setText(module_id)
            used.add(module_id)

    def _current_cell_changed(self, current_row: int, _current_column: int,
                              _previous_row: int, _previous_column: int) -> None:
        if current_row < 0 or current_row >= self.parameter_table.rowCount():
            return
        module_id = self._cell_text(current_row, "module_id") or f"第 {current_row + 1} 行"
        self.statusBar().showMessage(f"当前模块：{module_id}")

    def _populate_tables(self) -> None:
        ensure_standard_project(self.project)
        self.drawing_document = None
        self._preview_pdf = None
        self._clear_rows()
        for module in self.project.modules:
            self._add_module((
                module,
                self.project.board_for(module.module_id),
                self.project.anchor_for(module.module_id),
            ))
        if not self.project.modules:
            self._add_module()
        self._update_row_count()
        self._update_conditional_states()
        self._reset_history()

    def new_project(self) -> None:
        self.project = Project()
        self.drawing_document = None
        self._preview_pdf = None
        self.preview.scene().clear()
        self.page_spin.setMaximum(1)
        self._clear_rows()
        self._add_module()
        self._reset_history()

    def _build_project_row(self, row: int) -> tuple[ModuleParameters, BoardParameters, AnchorParameters]:
        return build_standard_row(self._sheet_values(row), self._row_bases[row])

    def _collect_project(self) -> Project:
        modules: list[ModuleParameters] = []
        boards: list[BoardParameters] = []
        anchors: list[AnchorParameters] = []
        for row in range(self.parameter_table.rowCount()):
            module, board, anchor = self._build_project_row(row)
            modules.append(module)
            boards.append(board)
            anchors.append(anchor)
        project = Project(
            metadata=self.project.metadata,
            modules=modules,
            boards=boards,
            anchors=anchors,
        )
        ensure_standard_project(project)
        return project

    def generate(self) -> None:
        module_count = self.parameter_table.rowCount()
        progress = OperationProgress(self, "正在整理参数…", module_count + 4)
        try:
            self.project = self._collect_project()
            progress.advance("正在读取参考图块…")
            library = ReferenceLibrary(self.reference_dxf) if self.reference_dxf.exists() else None
            progress.advance(f"正在生成模块视图 0/{module_count}…")
            self.drawing_document = DrawingGenerator(library).generate(
                self.project,
                on_module_drawn=lambda count: progress.advance(
                    f"正在生成模块视图 {count}/{module_count}…"
                    if count < module_count else "正在排版…"
                ),
            )
            self._preview_pdf = None
            progress.bar.setMaximum(module_count + len(self.drawing_document.pages) + 5)
            progress.advance("正在准备 PDF 预览…")
            with QSignalBlocker(self.page_spin):
                self.page_spin.setMaximum(max(1, len(self.drawing_document.pages)))
                self.page_spin.setValue(1)
            warnings = list(self.drawing_document.warnings)
            try:
                font_directory = self._pdf_font_directory()
                with TemporaryDirectory(prefix="refracdraft-preview-") as directory:
                    path = self._render_pdf(Path(directory) / "preview.pdf", font_directory, progress)
                    self._preview_pdf = (font_directory, path.read_bytes())
                self._show_selected_page(1)
            except Exception as exc:
                self._preview_pdf = None
                self._show_selected_page(1)
                warnings.append(f"暂用绘图预览，PDF 预览生成失败：{exc}")
            progress.finish("图纸已生成")
            self.statusBar().showMessage("图纸已生成" + ("；" + "；".join(warnings) if warnings else ""))
        except Exception as exc:
            progress.hide()
            QMessageBox.critical(self, "生成失败", str(exc))
        finally:
            progress.hide()
            progress.deleteLater()

    def _show_selected_page(self, value: int) -> None:
        if self._preview_pdf is None:
            super()._show_selected_page(value)
            return
        with pymupdf.open(stream=self._preview_pdf[1], filetype="pdf") as pdf:
            page = pdf[value - 1].get_pixmap(dpi=180, alpha=False)
            samples = page.samples
            image = QImage(
                samples, page.width, page.height, page.stride, QImage.Format.Format_RGB888
            )
            self.preview.show_page_image(QPixmap.fromImage(image))

    def _pdf_font_directory(self) -> str | None:
        directory = application_directory() / "fonts"
        return str(directory) if directory.is_dir() else None

    def _render_pdf(
        self, path: Path, font_directory: str | None, progress: OperationProgress
    ) -> Path:
        return export_pdf(
            self.drawing_document,
            path,
            reference_dxf=self.reference_dxf,
            font_directory=font_directory,
            progress=progress.advance,
        )

    def export_dxf_file(self) -> None:
        if not self.drawing_document:
            self.generate()
        if not self.drawing_document:
            return
        path = self._output_target(".dxf")
        if path is None:
            return
        progress = OperationProgress(self, "正在准备 DXF…", 2)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            progress.advance("正在写入 DXF…")
            export_dxf(self.drawing_document, path, self.reference_dxf)
            progress.finish("DXF 已导出")
            self.statusBar().showMessage(f"DXF 已导出：{path}")
        except Exception as exc:
            progress.hide()
            QMessageBox.critical(self, "DXF 导出失败", str(exc))
        finally:
            progress.hide()
            progress.deleteLater()

    def export_pdf_file(self) -> None:
        if not self.drawing_document:
            self.generate()
        if not self.drawing_document:
            return
        path = self._output_target(".pdf")
        if path is None:
            return
        progress = OperationProgress(self, "正在准备 PDF…", len(self.drawing_document.pages) + 2)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            font_directory = self._pdf_font_directory()
            if self._preview_pdf is not None and self._preview_pdf[0] == font_directory:
                progress.update_stage("正在保存预览 PDF…", progress.bar.maximum() - 1)
                with TemporaryDirectory(prefix="refracdraft-save-", dir=path.parent) as directory:
                    staged = Path(directory) / "drawing.pdf"
                    staged.write_bytes(self._preview_pdf[1])
                    staged.replace(path)
            else:
                self._render_pdf(path, font_directory, progress)
                self._preview_pdf = (font_directory, path.read_bytes())
                self._show_selected_page(self.page_spin.value())
            progress.finish("PDF 已导出")
            self.statusBar().showMessage(f"PDF 已导出：{path}")
        except Exception as exc:
            progress.hide()
            QMessageBox.critical(self, "PDF 导出失败", str(exc))
        finally:
            progress.hide()
            progress.deleteLater()

    def _preview_page_step(self, step: int) -> None:
        if not self.drawing_document:
            return
        page_count = len(self.drawing_document.pages)
        if page_count <= 1:
            return
        next_page = max(1, min(page_count, self.page_spin.value() + step))
        self.page_spin.setValue(next_page)

    def _preview_zoom(self, factor: float) -> None:
        if not self.drawing_document:
            return
        self.preview.scale(factor, factor)
